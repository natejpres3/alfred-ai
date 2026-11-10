"""Management commands.

    uv run python -m app.cli init-db      # create tables (dev; production uses alembic upgrade)
    uv run python -m app.cli seed         # sync curriculum + seed lessons
    uv run python -m app.cli check-seeds  # validate seed lessons incl. running reference solutions
"""

from __future__ import annotations

import sys

from app.db import Base, engine, session_scope


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "help"
    if cmd == "init-db":
        import app.models  # noqa: F401

        Base.metadata.create_all(engine())
        print("tables created")
    elif cmd == "seed":
        from app.services.curriculum import sync_curriculum

        with session_scope() as db:
            v = sync_curriculum(db)
            print(f"curriculum version {v.version} active")
    elif cmd == "check-seeds":
        from app.services.curriculum import iter_lessons, load_seed_lesson, load_spec
        from app.services.lesson_validation import validate_lesson

        bad = 0
        for *_, lesson in iter_lessons(load_spec()):
            if lesson.get("seed"):
                spec = {"key": lesson["key"], "objectives": lesson.get("objectives", [])}
                r = validate_lesson(load_seed_lesson(lesson["seed"]), spec, execute_code=True, check_links="--links" in argv)
                print(f"{lesson['key']}: {'OK' if r.ok else 'FAIL'} {r.errors} warnings={r.warnings}")
                bad += not r.ok
        return 1 if bad else 0
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
