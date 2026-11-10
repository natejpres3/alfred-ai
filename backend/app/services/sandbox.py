"""Sandboxed execution of student code.

Backends:
* DockerSandbox (default): `docker run --network none --read-only --cap-drop ALL --pids-limit
  --memory --cpus --user`, job passed on stdin, container killed on wall-clock timeout.
* LocalSandbox ("unsafe-local"): runs the runner in a subprocess of this machine with only
  CPU/time limits. Refuses to run unless SANDBOX_ALLOW_UNSAFE_LOCAL=true. For tests and offline dev.

Hidden tests run in a separate invocation from public tests, and the hidden run's stdout and
failure messages are discarded, so student code cannot exfiltrate hidden test content.
"""

from __future__ import annotations

import ast
import json
import secrets
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings

RUNNER = Path(__file__).resolve().parents[2] / "sandbox" / "runner.py"
SAFE_STDLIB = {"math", "typing", "functools", "itertools", "collections", "dataclasses", "random", "statistics", "__future__", "cmath", "fractions"}


class SandboxError(Exception):
    """Infrastructure failure (not a student error). Jobs retry on this."""


@dataclass
class RunResult:
    compile_error: str | None
    missing_functions: list[str]
    tests: list[dict]
    stdout: str = ""
    infra_error: str | None = None


@dataclass
class CodeRunReport:
    public: RunResult
    hidden: RunResult | None
    static_violations: list[str] = field(default_factory=list)

    def summary(self, public_weights: dict[str, float], hidden_weights: dict[str, float]) -> dict:
        """Weighted pass rate. Hidden tests count double (see docs §4 Code)."""
        total = earned = 0.0
        pub = [t for t in self.public.tests]
        hid = self.hidden.tests if self.hidden else []
        for t in pub:
            w = public_weights.get(t["name"], 1.0)
            total += w
            earned += w if t["status"] == "passed" else 0
        for t in hid:
            w = 2 * hidden_weights.get(t["name"], 1.0)
            total += w
            earned += w if t["status"] == "passed" else 0
        return {
            "pass_rate": (earned / total) if total else 0.0,
            "public_passed": sum(t["status"] == "passed" for t in pub),
            "public_total": len(pub),
            "hidden_passed": sum(t["status"] == "passed" for t in hid),
            "hidden_total": len(hid),
        }


def _parse(stdout: str, nonce: str) -> dict:
    marker = f"@@RESULT:{nonce}@@"
    lines = [ln for ln in stdout.splitlines() if ln.startswith(marker)]
    if not lines:
        raise SandboxError("runner produced no result (crashed, killed, or out of memory)")
    return json.loads(lines[-1][len(marker):])


class BaseSandbox:
    def _invoke(self, job: dict, timeout: float) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def run(self, code: str, tests: list[dict], required_functions: list[str], time_limit: int) -> RunResult:
        nonce = secrets.token_hex(16)
        job = {
            "code": code,
            "tests": [{"name": t["name"], "code": t["code"]} for t in tests],
            "required_functions": required_functions,
            "time_limit": time_limit,
            "nonce": nonce,
        }
        # Total wall clock: module import + each test, plus container start overhead.
        timeout = time_limit * (len(tests) + 1) + 15
        try:
            stdout = self._invoke(job, timeout)
        except subprocess.TimeoutExpired:
            return RunResult(compile_error=None, missing_functions=[], tests=[
                {"name": t["name"], "status": "timeout", "message": "sandbox wall-clock limit", "seconds": None} for t in tests
            ], infra_error="timeout")
        data = _parse(stdout, nonce)
        return RunResult(
            compile_error=data["compile_error"],
            missing_functions=data["missing_functions"],
            tests=data["tests"],
            stdout=data.get("stdout", ""),
        )


class DockerSandbox(BaseSandbox):
    def __init__(self) -> None:
        self.settings = get_settings()

    def _invoke(self, job: dict, timeout: float) -> str:
        s = self.settings
        name = f"academy-run-{secrets.token_hex(6)}"
        cmd = [
            "docker", "run", "--rm", "-i", "--name", name,
            "--network", "none",
            "--read-only", "--tmpfs", "/tmp:rw,size=64m",
            "--memory", f"{s.sandbox_memory_mb}m", "--memory-swap", f"{s.sandbox_memory_mb}m",
            "--cpus", "1", "--pids-limit", "64",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "10001:10001",
            s.sandbox_image,
        ]
        try:
            proc = subprocess.run(cmd, input=json.dumps(job), capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", name], capture_output=True)
            raise
        except FileNotFoundError as e:
            raise SandboxError("docker is not installed") from e
        if proc.returncode != 0 and "@@RESULT:" not in proc.stdout:
            raise SandboxError(f"docker run failed ({proc.returncode}): {proc.stderr[-500:]}")
        return proc.stdout


class LocalSandbox(BaseSandbox):
    """NOT a security boundary. Only for tests/offline development."""

    def __init__(self) -> None:
        if not get_settings().sandbox_allow_unsafe_local:
            raise SandboxError("unsafe-local sandbox is disabled; set SANDBOX_ALLOW_UNSAFE_LOCAL=true to use it")

    def _invoke(self, job: dict, timeout: float) -> str:
        def limits():  # pragma: no cover - runs in child
            import resource

            cpu = int(timeout)
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))

        proc = subprocess.run(
            [sys.executable, "-I", str(RUNNER)],
            input=json.dumps(job), capture_output=True, text=True, timeout=timeout,
            preexec_fn=limits, env={"PATH": "/usr/bin:/bin"},
        )
        return proc.stdout


def get_sandbox() -> BaseSandbox:
    return LocalSandbox() if get_settings().sandbox_backend == "unsafe-local" else DockerSandbox()


# ------------------------------------------------------------------ static checks


def static_check(code: str, *, forbidden_imports: list[str], allowed_imports: list[str] | None,
                 forbidden_calls: list[str], required_functions: list[str]) -> list[str]:
    """AST-level checks that run outside the sandbox (parsing only, never executing)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"SyntaxError: {e.msg} (line {e.lineno})"]
    violations: list[str] = []
    aliases: dict[str, str] = {}
    allowed = set(allowed_imports or []) | SAFE_STDLIB
    forbidden_roots = set(forbidden_imports)

    def check_module(mod: str, lineno: int):
        root = mod.split(".")[0]
        if root in forbidden_roots:
            violations.append(f"line {lineno}: import of '{mod}' is not allowed for this task")
        elif allowed_imports is not None and root not in allowed:
            violations.append(f"line {lineno}: import of '{mod}' is not in the allowed list ({', '.join(sorted(allowed_imports)) or 'none'})")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                check_module(a.name, node.lineno)
                aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            check_module(node.module, node.lineno)
            for a in node.names:
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"
        elif isinstance(node, ast.Call) and node.func is not None and isinstance(node.func, ast.Name) and node.func.id in ("__import__", "exec", "eval"):
            violations.append(f"line {node.lineno}: '{node.func.id}' is not allowed")

    def normalize(name: str) -> str:
        head, _, rest = name.partition(".")
        head = aliases.get(head, {"np": "numpy"}.get(head, head))
        return f"{head}.{rest}" if rest else head

    forbidden = {normalize(c) for c in forbidden_calls}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dotted = _dotted(node.func)
            if dotted and normalize(dotted) in forbidden:
                violations.append(f"line {node.lineno}: call to '{dotted}' is not allowed for this task")

    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for f in required_functions:
        if f not in defined:
            violations.append(f"required function '{f}' is not defined")
    return violations


def _dotted(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None
