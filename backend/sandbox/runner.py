"""Executes untrusted student code + tests. Runs INSIDE the sandbox container.

Protocol: the job arrives as JSON on stdin (never as a file the student code could read):
  {"code": str, "tests": [{"name", "code"}], "required_functions": [...], "time_limit": int, "nonce": str}
Result: a single line "@@RESULT:<nonce>@@<json>" on the real stdout. Student output is captured.
"""

import contextlib
import io
import json
import signal
import sys
import time
import traceback
import types


class _Timeout(BaseException):
    pass


@contextlib.contextmanager
def _time_limit(seconds):
    def handler(signum, frame):
        raise _Timeout()

    old = signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def _short_tb(exc):
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == "solution.py"]
    where = f" (solution.py line {frames[-1].lineno})" if frames else ""
    return f"{type(exc).__name__}: {exc}{where}"


def main():
    job = json.loads(sys.stdin.read())
    nonce = job.pop("nonce")
    real_stdout = sys.stdout
    marker = f"@@RESULT:{nonce}@@"
    del nonce

    def emit(payload, _out=real_stdout, _marker=marker):
        _out.write(_marker + json.dumps(payload) + "\n")
        _out.flush()

    del marker

    out = {"compile_error": None, "missing_functions": [], "tests": [], "stdout": ""}
    buf = io.StringIO()
    mod = types.ModuleType("solution")
    mod.__dict__["__name__"] = "solution"
    limit = float(job.get("time_limit", 10))
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf), _time_limit(limit):
            exec(compile(job["code"], "solution.py", "exec"), mod.__dict__)
    except _Timeout:
        out["compile_error"] = f"Module-level code exceeded {limit}s"
    except BaseException as e:  # noqa: BLE001 - student code may raise anything, incl. SystemExit
        out["compile_error"] = _short_tb(e)
    if out["compile_error"]:
        out["stdout"] = buf.getvalue()[-4000:]
        emit(out)
        return

    out["missing_functions"] = [f for f in job.get("required_functions", []) if not callable(mod.__dict__.get(f))]
    for test in job["tests"]:
        ns = dict(mod.__dict__)
        started = time.monotonic()
        status, message = "passed", ""
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf), _time_limit(limit):
                exec(compile(test["code"], f"{test['name']}.py", "exec"), ns)
                ns[test["name"]]()
        except _Timeout:
            status, message = "timeout", f"exceeded {limit}s"
        except AssertionError as e:
            status, message = "failed", str(e) or "assertion failed"
        except BaseException as e:  # noqa: BLE001
            status, message = "error", _short_tb(e)
        out["tests"].append(
            {"name": test["name"], "status": status, "message": message[:500], "seconds": round(time.monotonic() - started, 4)}
        )
    out["stdout"] = buf.getvalue()[-4000:]
    emit(out)


if __name__ == "__main__":
    main()
