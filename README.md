# AI Academy

A mastery-based, AI-driven education platform that teaches artificial intelligence from first principles
(linear algebra → … → LLM systems, GPUs and research), one ~60-minute lesson a day. You advance by
**demonstrating** understanding: explanations are graded against explicit rubrics, code runs against hidden
tests in a sandbox, critical objectives can't be compensated for by a high average, and failing produces a
targeted review with new questions instead of the same quiz again.

Design docs live in [`docs/`](docs/):
[requirements](docs/01-product-requirements.md) ·
[architecture](docs/02-architecture.md) ·
[data model](docs/03-data-model.md) ·
[curriculum, grading & mastery](docs/04-curriculum-grading-mastery.md) ·
[milestones](docs/05-milestones.md)

## What's here

| Path | What |
|---|---|
| `backend/` | FastAPI API + background worker (Python 3.12, SQLAlchemy, Alembic, Pydantic, Claude SDK) |
| `backend/app/seed/` | Curriculum graph (`curriculum.yaml`, all 18 blocks; Block 1 fully specified), 5 hand-authored lessons + checkpoint, the gradient-descent project |
| `backend/sandbox/` | Isolated code runner + Docker image for student code |
| `frontend/` | Next.js 15 app (TypeScript, Tailwind v4, KaTeX, Monaco, Recharts) |
| `docker-compose.yml` | Postgres 16 + Mailpit (captures outgoing email) |

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 22, Docker.

```bash
make setup            # install deps, create backend/.env from .env.example
# edit backend/.env: set ANTHROPIC_API_KEY
make db               # start Postgres + Mailpit, run migrations, seed the curriculum
make sandbox-image    # build the code-execution sandbox image
make dev              # API :8000, worker, web :3000
```

Open http://localhost:3000 and create an account (the **first account becomes admin**).
Emails appear in Mailpit at http://localhost:8025.

### Fully offline (no Docker, no API key)

```bash
make offline
```

This runs SQLite, the **offline AI provider** (keyword-heuristic grading, placeholder lessons for un-authored
topics — all clearly labelled in the UI), the **unsafe local sandbox** (no isolation; your own code only), and
console email (`.eml` files in `backend/var/outbox`). It's for exploring the product, not for real grading.

## Tests

```bash
make test         # backend pytest (69 tests) + frontend typecheck/lint
make check-seeds  # validates seed lessons and runs every reference solution against its own tests
```

The end-to-end tests (`backend/tests/test_lifecycle_e2e.py`) drive the HTTP API through the whole loop:
lesson delivered and emailed once → incomplete work rejected → failing on critical explanations → targeted
remediation with distinct questions → pass → next lesson unlocked and emailed exactly once (job replays don't
duplicate) → module gate requiring the checkpoint **and** the project (a closed-form shortcut is capped at 50%)
→ next module's lesson generated and validated → test-out after the diagnostic.

## How a lesson moves through the system

1. Passing an assessment → `progression.refresh` unlocks what the concept graph now allows → `prepare_lesson` job.
2. `prepare_lesson` reuses a published version or runs **author → deterministic validation (structure,
   objective coverage, LaTeX, workload, prerequisites, reference solutions executed against their tests, links
   verified) → repair → independent review → publish** (immutable, versioned) → email.
3. Submitting → `grade_submission` job: deterministic items, rubric LLM grading with evidence verification and
   a second pass when borderline/low-confidence (disagreement → manual review queue), code in the sandbox +
   static checks + AI review → mastery update → pass/remediate.

## Configuration

All settings are environment variables (see `.env.example`): thresholds (`THRESHOLD_*`), per-role models
(`AI_MODEL_<ROLE>`, default `claude-opus-5-5`), monthly AI budget, sandbox backend, email provider
(console / SMTP / Resend). Secrets are never stored in the database or committed.

## Status

Phases 1–6 of the plan are implemented (see [milestones](docs/05-milestones.md)). Not yet done: deployment
pipeline, GPU sandbox, specs for Blocks 2–18 (they show on the roadmap as outlines), a calibration eval set
for LLM grading.
