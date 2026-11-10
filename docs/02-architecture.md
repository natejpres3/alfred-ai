# AI Academy — Technical Architecture

## 1. Shape of the system

```
                 ┌──────────────────────────┐
  Browser ──────▶│ Next.js (frontend/)       │  App Router, TS, Tailwind, KaTeX, Monaco
                 │  /api/* rewritten to API  │  same-origin → session cookie just works
                 └────────────┬─────────────┘
                              │ HTTP (JSON)
                 ┌────────────▼─────────────┐
                 │ FastAPI (backend/app)     │  one deployable, logical services inside
                 │  api/  services/  ai/     │
                 └──┬──────────┬─────────┬───┘
                    │          │         │
           ┌────────▼──┐  ┌────▼─────┐  ┌▼─────────────────┐
           │ Postgres  │  │ Worker   │  │ Sandbox (Docker) │
           │ data+jobs │◀─│ app.worker│─▶│ no net, rlimits  │
           └───────────┘  └────┬─────┘  └──────────────────┘
                               │
                 ┌─────────────┴────────────┐
                 │ Claude API   Email (Resend│SMTP)  HTTP link checks
                 └──────────────────────────┘
```

Two processes run from one codebase: the **API** (`uvicorn app.main:app`) and the **worker**
(`python -m app.worker`). They share the database. Anything slow or fallible (LLM calls,
sandbox runs, email) happens in the worker; the API only enqueues.

## 2. Technology choices

| Concern | Choice | Why / tradeoff |
|---|---|---|
| Frontend | Next.js 15 + TS + Tailwind v4 + shadcn-style components | As requested. Components are written in-repo (shadcn's copy-in model) to avoid a CLI step. |
| Math | KaTeX via `remark-math`/`rehype-katex` | Fast, SSR-safe. |
| Code editor | Monaco (`@monaco-editor/react`) | VS Code editing in the browser. |
| Charts / widgets | Recharts + hand-written SVG widgets | Widgets are a fixed registry so the LLM can only reference known components. |
| Backend | FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic | As requested. |
| DB | PostgreSQL 16 (SQLite for unit tests) | Portable column types (`JSON` → `JSONB` on Postgres). |
| Queue | Postgres table + polling worker | See PRD assumption 2. |
| LLM | Anthropic Claude via official `anthropic` SDK, behind `LLMProvider` | Structured outputs (`output_config.format`) validated again by Pydantic. |
| Sandbox | Docker, `--network none`, read-only FS, CPU/mem/pids/time limits, nobody user | Strong enough for single-tenant; gVisor/Firecracker are drop-in upgrades via the `Sandbox` interface. |
| Email | `EmailProvider`: Console (dev), SMTP (Mailpit in docker-compose), Resend (prod) | Swappable. |
| Packaging | `uv` (Python), `npm` (Node), `docker compose` for Postgres + Mailpit | |

**Deliberately absent:** Redis, Celery, Kubernetes, microservices, vector DB. Each can be added
behind an existing interface when a real need appears.

## 3. Backend module map

```
backend/app/
  main.py            FastAPI app, routers, error handlers
  config.py          Settings (env), thresholds, model-per-role config
  db.py              engine/session, portable JSON type
  models/            SQLAlchemy entities (see 03-data-model.md)
  schemas/
    lesson.py        LessonContent — the typed lesson schema (+ student-view projection)
    grading.py       RubricGrade, CodeReview, Diagnosis … (LLM output schemas)
    api.py           request/response DTOs
  ai/
    provider.py      LLMProvider protocol, AnthropicProvider, FakeProvider
    schema_utils.py  Pydantic → structured-output JSON Schema
    costs.py         price table, budget guard
    prompts/         one template module per role
  services/
    curriculum.py    graph load/validate, eligibility           (Curriculum Service)
    lesson_gen.py    author → validate → review → publish        (Lesson Generation Service)
    lesson_validation.py  deterministic QC checks
    resources.py     verification of links                       (Resource Service)
    grading.py       objective, rubric, code graders             (Assessment Service)
    sandbox.py       Docker + unsafe-local backends
    mastery.py       evidence → estimates, spaced repetition     (Mastery Service)
    progression.py   state machine, gates, unlocks               (Progression Service)
    remediation.py   plans, variants, prerequisite fallback
    tutor.py         contextual tutoring                          (Tutor Service)
    notifications.py idempotent notifications + email            (Notification Service)
    jobs.py          enqueue/claim/complete/retry
    audit.py         append-only audit log
  api/               routers (auth, onboarding, dashboard, curriculum, lessons,
                     submissions, projects, tutor, reviews, notes, settings, admin, email)
  worker.py          job loop + periodic scheduler
  seed/              curriculum.yaml, lessons/*.yaml, projects/*.yaml
```

## 4. Key flows

### 4.1 Submit → grade → progress (the core loop)

```
POST /api/assessments/{id}/submissions  (Idempotency-Key)
  └─ tx: Submission(status=submitted) + Job(grade_submission, key=sub:{id})
worker: grade_submission
  ├─ objective items → deterministic grader
  ├─ free-response  → RubricGrader (LLM, pass 1) → second pass if borderline/low-confidence
  │                   → evidence quotes verified against the answer text
  ├─ code           → Sandbox(public+hidden) + static checks → CodeReviewer (LLM)
  ├─ Grade + RubricResults persisted (rubric/version/model/prompt hash recorded)
  ├─ Mastery.update(evidence)            (objective + concept level)
  └─ Progression.on_graded(submission)
        pass  → lesson PASSED → unlock eligible → Job(prepare_lesson) per unlocked lesson
        fail  → lesson REMEDIATION_REQUIRED → Job(create_remediation)
        flagged for review → lesson stays GRADING until an admin resolves it
worker: prepare_lesson → (published version exists? reuse : generate→validate→review→publish)
                       → Notification(lesson_available, key=…) → Job(send_notification)
worker: send_notification → preferences/quiet-hours → EmailProvider.send → EmailDelivery
```

Every job is idempotent: it is keyed (`background_jobs.idempotency_key` unique), and each
handler checks current state before acting (e.g. `prepare_lesson` exits if the user already has
a published version; `send_notification` exits if a delivery succeeded).

### 4.2 Lesson generation pipeline

1. **Plan** (deterministic): Curriculum Service picks the lesson; context = lesson spec,
   objectives, prerequisite concepts with the student's mastery, open misconceptions, recent
   grades, time budget, titles + summaries of completed lessons, verified resources for the
   concepts.
2. **Author** (LLM, `LessonContent` structured output, high effort).
3. **Validate** (deterministic, `lesson_validation.py`): schema; objectives ↔ questions
   coverage; every critical objective has ≥1 assessed question; prerequisites satisfied;
   LaTeX delimiter/brace balance; Python code blocks marked runnable execute in the sandbox;
   resource URLs verified (unverified → stripped or marked); workload ≤ budget × 1.15; every
   free-response item has a rubric; no grader-only data leaks into student-visible fields;
   near-duplicate check vs. completed lessons.
4. **Repair** (LLM, at most 2 rounds): validation errors fed back to the author.
5. **Review** (LLM, separate role): accuracy, pedagogy, alignment → approve / revise.
6. **Publish**: immutable `LessonVersion` (content hash), assessment rows materialized.

### 4.3 Tutor

`POST /api/tutor/conversations/{id}/messages` streams (SSE) a reply. Context: lesson
student-view (never the grader-only fields), the student's mastery for the lesson's concepts,
open misconceptions, notes, and mode. The system prompt forbids complete solutions to graded
items; hint mode escalates one level per request.

## 5. AI service design

| Role | Input | Output schema | Default model / effort |
|---|---|---|---|
| Curriculum Planner | deterministic code (graph + mastery); LLM only to *order* among several eligible lessons (future) | — | — |
| Lesson Author | lesson context | `LessonContent` | opus-5-5 / high |
| Resource Researcher | concept list | `ResourceCandidates` (then HTTP-verified) | opus-5-5 / medium |
| Lesson Reviewer | draft lesson | `LessonReview` | opus-5-5 / high |
| Tutor | lesson + history + mode | free text (streamed) | opus-5-5 / medium |
| Conceptual Grader | question, rubric, reference, answer | `RubricGrade` | opus-5-5 / high |
| Coding Reviewer | spec, code, test results | `CodeReview` | opus-5-5 / high |
| Mastery Evaluator | deterministic (`mastery.py`) | — | — |
| Remediation Planner | failed objectives, grades, misconceptions | `RemediationContent` | opus-5-5 / high |

Models and effort are configurable per role via env (`AI_MODEL_GRADER=…`), so cheaper models can
be assigned to simple roles once evals show quality holds. All calls go through
`LLMProvider.structured()` / `.stream_text()` which: enforce the budget, request structured JSON,
re-validate with Pydantic, handle `stop_reason` `refusal`/`max_tokens`, opt into server-side
refusal fallbacks, and log an `ai_calls` row (tokens, cost, latency, prompt hash, request id).

**Prompt-injection posture.** Student answers, code, and fetched web content are wrapped in
tagged blocks and declared to be data. Grading output can only *score*; it cannot trigger
actions. Rubric scores are clamped to criterion maxima in code, and every grader "evidence"
quote must literally occur in the student's answer or the criterion is re-graded / flagged.
No LLM role has tools that mutate state.

## 6. Security model

| Threat | Control |
|---|---|
| Account takeover | Argon2id hashes, HTTP-only `SameSite=Lax` session cookie, server-side sessions (revocable), login rate limit |
| Cross-user data access | Every query scoped by `user_id`; ownership checked in dependencies; tests for 404 on foreign IDs |
| Untrusted code | Docker sandbox: `--network none`, `--read-only`, tmpfs `/tmp`, `--memory`, `--cpus`, `--pids-limit`, `--cap-drop ALL`, `no-new-privileges`, uid 65534, wall-clock kill; never executed in the API process. `unsafe-local` backend refuses to run unless explicitly enabled |
| Hidden-test leakage | Hidden test names/messages never returned; only pass counts |
| Answer leakage | Student view is a *projection* that drops `grading` objects; tested |
| Prompt injection into grading | Data tagging, clamped scores, evidence verification, second pass, manual review |
| Secrets | Env vars only (`.env` git-ignored); no keys in DB or logs |
| Email abuse | Per-notification idempotency key; unsubscribe token; preference checks |
| Resource links | Only `http(s)`; verified; rendered with `rel="noopener noreferrer"`; YouTube embeds via `youtube-nocookie.com` |

## 7. Reliability

- Jobs: `attempts`/`max_attempts`, exponential backoff, `locked_at` lease (stale leases reclaimed),
  `dead` state surfaced on the admin page.
- Progression transitions are guarded (`expected_from` states) so replays are no-ops.
- Grades are append-only; overrides create a new grade that supersedes the old one.
- Lesson versions and assessment questions are immutable after publish; remediation creates new
  versions/assessments rather than editing.

## 8. Cost control

- Seeded lessons cost nothing; generated lessons are generated once per (user, lesson) and cached.
- Remediation and variants are generated only on failure.
- `AI_MONTHLY_BUDGET_USD` hard stop (jobs fail with a clear "budget exceeded" error and retry
  next month / after raising the budget).
- Admin page: cost by role, per lesson, per month.
- Prompt caching on stable system prompts.

## 9. Major tradeoffs

1. **Postgres queue vs. Redis/Celery** — simpler ops, transactional enqueue; lower throughput (irrelevant here).
2. **Hand-written lesson seeds** — upfront authoring cost; buys offline usability, tests, and exemplars.
3. **Docker sandbox vs. gVisor/Firecracker** — Docker is available everywhere; for a single trusted-ish
   student the residual container-escape risk is acceptable. Interface allows upgrading.
4. **Fixed widget registry** — the generator can't invent arbitrary interactive JS (safer, reviewable),
   at the cost of needing a developer to add new widget types.
5. **SQLite in unit tests** — fast tests without Docker; Postgres-specific behavior (SKIP LOCKED) is
   covered by an integration test that runs only when `TEST_DATABASE_URL` points at Postgres.
