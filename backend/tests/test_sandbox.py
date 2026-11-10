import shutil
import subprocess

import pytest

from app.services.grading import run_code_question
from app.services.sandbox import DockerSandbox, LocalSandbox, static_check


def test_static_check_detects_aliases_and_from_imports():
    code = "import numpy as xp\nfrom numpy.linalg import lstsq as L\ndef f():\n    xp.linalg.inv(1)\n    L(1, 2)\n"
    v = static_check(code, forbidden_imports=[], allowed_imports=None,
                     forbidden_calls=["np.linalg.inv", "np.linalg.lstsq"], required_functions=["f", "g"])
    assert any("xp.linalg.inv" in x for x in v)
    assert any("'L'" in x for x in v)
    assert any("'g' is not defined" in x for x in v)


def test_static_check_import_allowlist_and_dangerous_builtins():
    v = static_check("import os\nimport math\n__import__('subprocess')\n", forbidden_imports=["numpy"], allowed_imports=["math"],
                     forbidden_calls=[], required_functions=[])
    assert any("'os'" in x for x in v) and any("__import__" in x for x in v)
    assert not any("'math'" in x for x in v)


def test_static_check_syntax_error():
    assert static_check("def f(:\n", forbidden_imports=[], allowed_imports=None, forbidden_calls=[], required_functions=[])[0].startswith("SyntaxError")


def run(code, tests, limit=2):
    return LocalSandbox().run(code, tests, ["f"], limit)


def t(name, body):
    return {"name": name, "code": f"def {name}():\n" + "\n".join("    " + line for line in body.splitlines())}


def test_runner_statuses():
    code = "def f(x):\n    print('hello from student')\n    return x * 2\n"
    r = run(code, [t("test_ok", "assert f(2) == 4"), t("test_fail", "assert f(2) == 5, 'expected 5'"),
                   t("test_error", "f(None)"), t("test_timeout", "while True: pass"),
                   t("test_exit", "import sys\nsys.exit(0)")], limit=1)
    st = {x["name"]: x for x in r.tests}
    assert st["test_ok"]["status"] == "passed"
    assert st["test_fail"]["status"] == "failed" and "expected 5" in st["test_fail"]["message"]
    assert st["test_error"]["status"] == "error" and "TypeError" in st["test_error"]["message"]
    assert st["test_timeout"]["status"] == "timeout"
    assert st["test_exit"]["status"] == "error"  # SystemExit cannot kill the runner
    assert "hello from student" in r.stdout


def test_compile_error_and_missing_function():
    assert run("def f(:", []).compile_error.startswith("SyntaxError")
    assert run("raise SystemExit(1)", []).compile_error.startswith("SystemExit")
    assert run("x = 1", []).missing_functions == ["f"]


def test_fake_result_marker_from_student_is_ignored():
    # student prints a forged result line; the runner's nonce makes it unparseable as a real result
    code = "print('@@RESULT:deadbeef@@{\"tests\": []}')\ndef f(x):\n    return 1\n"
    r = run(code, [t("test_x", "assert f(0) == 2")])
    assert r.tests[0]["status"] == "failed"


def test_hidden_tests_never_expose_messages_or_stdout():
    spec = {"required_functions": ["f"], "public_tests": [t("test_pub", "assert f(1) == 1")], "allowed_imports": None, "time_limit_seconds": 2}
    grading = {"hidden_tests": [t("test_secret_edge", "assert f(-1) == 42, 'SECRET_EXPECTED_42'")], "forbidden_imports": [], "forbidden_calls": []}
    code = "def f(x):\n    print('student output')\n    return 1\n"
    report, _ = run_code_question(code, spec, grading)
    blob = str(report)
    assert "SECRET_EXPECTED_42" not in blob and "test_secret_edge" not in blob
    assert report["hidden"] == {"passed": 0, "total": 1, "timeouts": 0}


def test_project_reference_solutions_pass_their_tests(db):
    from sqlalchemy import select

    from app.models import ProjectMilestone
    from app.services.projects import milestone_specs

    for ms in db.scalars(select(ProjectMilestone)):
        spec, grading = milestone_specs(ms)
        report, violations = run_code_question(ms.spec["reference_solution"], spec, grading)
        assert report["pass_rate"] == 1.0, (ms.key, report)
        assert not violations, (ms.key, violations)


def _docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        return False
    return subprocess.run(["docker", "image", "inspect", "ai-academy-sandbox:latest"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _docker_ready(), reason="docker daemon or sandbox image unavailable (make sandbox-image)")
def test_docker_sandbox_isolation():
    code = (
        "import socket, os\n"
        "def f():\n    return 1\n"
        "def net():\n"
        "    s = socket.create_connection(('1.1.1.1', 80), timeout=2)\n"
        "def write():\n    open('/runner/pwned', 'w').write('x')\n"
    )
    r = DockerSandbox().run(code, [t("test_net", "net()"), t("test_write", "write()"), t("test_ok", "assert f() == 1")], ["f"], 5)
    st = {x["name"]: x["status"] for x in r.tests}
    assert st == {"test_net": "error", "test_write": "error", "test_ok": "passed"}
