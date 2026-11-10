# AI Academy — Curriculum, Grading and Mastery Specification

## 1. Curriculum dependency model

Hierarchy: **Program → Block → Module → Lesson → Learning Objective → Activity (section) → Assessment (questions)**.

The authoritative spec is `backend/app/seed/curriculum.yaml`:

```yaml
concepts:
  - key: la.dot_product
    name: Dot product
    requires: [la.vectors]            # hard prerequisites
    soft_requires: [geo.angles]       # helpful, not gating
blocks:
  - key: b01
    title: Mathematical Foundations
    status: authored                  # 'outline' blocks show on the roadmap but have no lesson specs yet
    modules:
      - key: b01.m01
        title: Vectors and Matrices
        lessons:
          - key: b01.m01.l01
            title: Vectors, dot products, and geometric intuition
            teaches: [la.vectors, la.dot_product, la.norms]
            objectives:
              - key: b01.m01.l01.o1
                statement: Compute and geometrically interpret the dot product
                concept: la.dot_product
                critical: true
            seed: lessons/b01_m01_l01.yaml
```

Load-time validation (tests enforce): concept graph is a DAG; every `requires` key exists; every
objective's concept is in its lesson's `teaches`; a lesson's *external* prerequisites
(`requires` of taught concepts minus taught concepts) are all taught by **earlier** lessons
(curriculum order is a topological order).

### Eligibility (`curriculum.eligible_lessons`)
A lesson is **available** when all hold:
1. Its block is unlocked (previous block's block assessment passed, or it is the first block).
2. Its module is unlocked (all `requires_modules` completed — default: the previous module).
3. Every hard-prerequisite concept has concept-mastery state in {`mastered`, `review_due`, `at_risk`}
   (i.e. it was demonstrated at least once; decay schedules review but does not re-lock content).
4. Within a module, lessons are sequential (the previous lesson is passed). Module/block
   assessments additionally require every lesson in the module/block passed.

## 2. Progression state machines

Lesson (`user_lesson_progress.state`):
```
locked ─unlock→ available ─open→ in_progress ─submit→ submitted ─claim→ grading
grading ─pass→ passed
grading ─fail→ remediation_required ─remediation submitted→ grading
grading ─needs human→ grading (stays; flagged)  ─admin resolves→ passed | remediation_required
```
Module (`user_module_progress.state`):
```
locked → available → in_progress → (all lessons passed) → project_pending | assessment_pending
→ completed   (module assessment passed ∧ project passed)
```
`not_started` is represented by `available` with `started_at = NULL`. Transitions go through
`progression.transition(progress, to, expected_from={…})`; an unexpected current state is a no-op
(returns False) which makes job replays safe. Each transition writes an audit event.

## 3. Thresholds (defaults, configurable)

| Requirement | Default | Setting |
|---|---|---|
| Required activity completion | 100% | `THRESHOLD_ACTIVITY_COMPLETION` |
| Daily lesson assessment | 85% | `THRESHOLD_LESSON` |
| Conceptual recall | 85% | `THRESHOLD_CONCEPTUAL` |
| Mathematical | 85% | `THRESHOLD_MATH` |
| Coding correctness | 90% | `THRESHOLD_CODING` |
| Major coding project | 90% | `THRESHOLD_PROJECT` |
| End-of-module | 85% | `THRESHOLD_MODULE` |
| End-of-block | 90% | `THRESHOLD_BLOCK` |
| Per-critical-objective | 85% | `THRESHOLD_CRITICAL_OBJECTIVE` |

### Pass rule (non-compensatory)
A submission passes iff **all** of:
1. Every required question answered (and, for lessons, every required section completed unless test-out).
2. Overall weighted score ≥ the assessment threshold.
3. Each category present (conceptual, math, coding) ≥ its category threshold.
4. Each **critical objective** score ≥ the critical-objective threshold.
5. No question is `flagged` for human review (flag → decision waits).

Example: 92% overall but 60% on the critical "apply the chain rule" objective → **fail**, with
`critical_failures = ["b01.m02.l03.o2"]`.

## 4. Grading

### Deterministic
- `mcq`: full credit iff the selected option is correct.
- `multi_select`: `max(0, (TP − FP) / |correct|)`.
- `numeric`: correct iff `|x − v| ≤ max(abs_tol, rel_tol·|v|)`. Accepts fractions and simple
  expressions (`3/4`, `2*pi`) parsed safely (no `eval`).

### Rubric (LLM) — `short_answer`, `long_answer`, `derivation`
Rubric = list of criteria `{id, description, points, required_for_mastery}` + reference answer +
known misconceptions. The grader returns per criterion: `points_awarded`, `evidence` (verbatim
quotes from the answer), `rationale`; plus `correct_concepts`, `missing_concepts`,
`incorrect_claims`, `misconceptions`, `feedback`, `next_steps`, `confidence` (0–1).

Safeguards:
1. Scores are clamped to `[0, points]` in code; totals recomputed in code (the LLM's arithmetic is ignored).
2. Evidence verification: any criterion awarded >0 points whose evidence quotes do not appear in
   the answer (normalized whitespace/case) is set to 0 and the result is marked for second pass.
3. **Second pass** when: confidence < 0.7, or score within ±10 points of the mastery threshold,
   or evidence verification failed. The second pass is an independent call with the criteria in
   a shuffled order. Final per-criterion score = mean of passes; if any criterion differs by more
   than 50% of its points → `flagged` (manual review queue).
4. Style/length are explicitly excluded from the rubric instructions; concise correct answers score fully.
5. `required_for_mastery` criteria scoring < 50% → `meets_mastery = false` regardless of total.

### Code
1. Submission stored (versioned).
2. Static checks (AST): required function names exist; forbidden imports/calls absent
   (e.g. `sklearn`, `torch`, `np.linalg.lstsq` in "from scratch" tasks).
3. Sandbox runs public then hidden tests (per-test timeout, total wall-clock limit).
4. Correctness score = weighted pass rate (hidden tests weight 2×). Performance tests count as tests.
5. AI Coding Reviewer receives spec, code, *test names + pass/fail* (hidden test bodies withheld
   from the student-facing output but given to the reviewer), returns quality notes,
   `implements_required_algorithm`, and actionable feedback. If the reviewer says the required
   algorithm was not implemented (e.g. closed-form solution instead of gradient descent) **and**
   static checks agree or confidence ≥ 0.8, the question is capped at 50%.
6. Resubmission allowed; history kept.

## 5. Mastery model

Evidence: each graded question contributes `(objective_key, score ∈ [0,1], weight)` where weight
reflects question type (code/derivation 1.5, free-response 1.2, mcq/numeric 1.0) and context
(review 0.7, diagnostic 0.5).

Objective estimate update (exponentially-weighted, recency-biased):
```
α = weight / (evidence_count_weighted + weight) , floored at 0.35
estimate ← estimate + α · (score − estimate)
```
Concept estimate = weighted mean of its objectives' estimates (objectives without evidence ignored).

Concept states:
| State | Rule |
|---|---|
| `not_started` | no evidence |
| `introduced` | lesson opened, no graded evidence |
| `practiced` | evidence exists, estimate < 0.85 |
| `mastered` | estimate ≥ 0.85 from a passed assessment |
| `review_due` | mastered and `now ≥ next_review_at` |
| `at_risk` | mastered and retrievability R < 0.6, where `R = exp(−Δt / stability_days)` |
| `needs_remediation` | latest graded evidence < 0.6, or open misconception on a critical objective |

Spaced repetition (simplified SM-2 / FSRS-like):
- On first mastery: `stability_days = 2`, `next_review_at = now + stability`.
- Review success (score ≥ 0.85): `stability ← stability × (1.8 + 0.6·(score−0.85)/0.15)` (cap 180 days).
- Review partial (0.6–0.85): `stability ← stability × 1.2`.
- Review fail (< 0.6): `lapses += 1`, `stability ← max(1, stability × 0.3)`, state `needs_remediation`.
- Reviews are 3–5 short items drawn from the concept's questions or generated variants; never a full lesson.

## 6. Remediation

On fail (attempt *n* for lesson L):
1. Failed objectives = critical failures ∪ objectives < threshold.
2. Diagnosis (LLM, `Diagnosis` schema): likely misconception per objective, from rubric results and answers.
3. If *n* ≥ 2 for the same objective, or the diagnosis names a prerequisite gap, include the
   prerequisite concepts (from the graph) in the plan.
4. Remediation Planner generates `RemediationContent`: a mini-lesson (≤ 25 min, different
   explanation strategy than previously used — strategies recorded so they aren't repeated),
   focused practice, and **new** questions for each failed objective.
5. Distinctness: new question prompts are compared to all previous prompts for that objective
   (normalized token Jaccard < 0.6); near-duplicates are rejected and regenerated.
6. Remediation assessment covers the failed objectives **plus** one retained item per passed
   critical objective (so passing remediation can't silently lose earlier mastery). Passing it
   passes the lesson.
7. Offline/fake mode: variant questions come from the seed's `variant_bank` when present.
