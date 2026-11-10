# AI Academy — Implementation Milestones

| Phase | Scope | Exit criteria | Status |
|---|---|---|---|
| 1 | Requirements & architecture (these docs) | Docs reviewed | ✅ |
| 2 | Project setup: uv backend, Next.js frontend, docker-compose (Postgres, Mailpit), Alembic, pytest, Makefile | `make dev` runs API + worker + web; `make test` green | ✅ |
| 3 | Core learning loop: curriculum load, lesson rendering, assessments, submissions, deterministic grading, mastery, progression, dashboard | Student can pass L1 with objective items only | ✅ |
| 4 | AI: provider abstraction, lesson generation + validation + review, rubric grading w/ second pass, tutor (SSE), remediation | Fail → remediation → pass in E2E test with FakeProvider | ✅ |
| 5 | Coding: Monaco, sandbox (Docker), public/hidden tests, static checks, AI code review, project milestones | GD project milestone graded in sandbox | ✅ |
| 6 | Automation: notifications, email providers, delivery hours/timezones, review scheduler, periodic jobs | Pass → next lesson email exactly once | ✅ |
| 7 | Hardening: admin review queue, cost dashboard, resource verification job, rate limits, CI | | partial |
| 8 | Deployment: Dockerfiles, managed Postgres, Resend domain, GitHub Actions deploy | | not started |
| 9 | Content expansion: author/generate remaining Block 1 modules; Blocks 2+ specs | | not started |

## Verification status (2026-11-08)
- Verified locally: 68 backend tests on SQLite (1 skipped: Docker isolation test), ruff clean; frontend
  typecheck, lint and production build; all seed reference solutions pass their public + hidden tests;
  Alembic migration applies with no model drift; a live smoke run (API + worker + Next.js as separate
  processes, offline AI provider) through register → onboarding → lesson delivery → grading → next lesson →
  tutor SSE via the proxy.
- **Not yet run anywhere:** the Postgres test pass, the Docker sandbox, and real Claude calls (lesson
  generation, rubric grading, tutor). CI is configured to run the first two; the Claude path is unit-tested
  against a mocked SDK only.
- The UI has not yet been reviewed visually in a browser.

## Known gaps / next steps
- GPU sandbox backend (needed for Block 7 CUDA/Triton work).
- GitHub-repo submissions are stored and linked but only single-file editor submissions are executed.
- LLM-graded items need a calibration eval set (`backend/evals/`) before trusting new models/prompts.
- The diagnostic is a short objective quiz; an adaptive (IRT-style) diagnostic would be better.
