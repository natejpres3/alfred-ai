# AI Academy — Data Model

Source of truth: `backend/app/models/`. Migrations: `backend/migrations/`.
All tables have `id` (UUID string) and `created_at`. JSON columns are `JSONB` on Postgres.

## Identity & preferences
| Table | Key columns | Notes |
|---|---|---|
| `users` | email (unique), password_hash, display_name, email_verified_at, is_admin | |
| `user_sessions` | token_hash (unique), user_id, expires_at, revoked_at | Opaque token in cookie; only its SHA-256 stored |
| `user_preferences` | user_id (unique), timezone, daily_goal_minutes, delivery_mode (`immediate`/`scheduled`), delivery_hour, notify (JSON per trigger), unsubscribe_token | |
| `learning_profiles` | user_id (unique), background (JSON), self_ratings (JSON), diagnostic (JSON), onboarding_completed_at, streak_days, last_study_date | |
| `email_verification_tokens` | user_id, token_hash, expires_at, used_at | |

## Curriculum (versioned)
| Table | Key columns | Notes |
|---|---|---|
| `curricula` | key, title | |
| `curriculum_versions` | curriculum_id, version, spec (JSON snapshot of YAML), spec_hash, is_active | New YAML → new version; old progress keeps pointing at stable keys |
| `blocks` | curriculum_version_id, key, position, title, description, gate_threshold, status (`authored`/`outline`) | |
| `modules` | block_id, key, position, title, description, project_key, requires_modules (JSON) | |
| `lessons` | module_id, key, position, kind (`lesson`/`module_assessment`/`block_assessment`), title, spec (JSON: objectives, teaches, requires, est. minutes, notes), seed_path | |
| `concepts` | key (unique per version), name, description, block_key | |
| `concept_prerequisites` | concept_id, prerequisite_id, strength (`hard`/`soft`) | DAG, validated on load |
| `learning_objectives` | lesson_id, key, statement, concept_key, critical | |

## Content (immutable after publish)
| Table | Key columns | Notes |
|---|---|---|
| `lesson_versions` | lesson_id, version, user_id (null = shared seed), purpose (`primary`/`remediation`/`review`), status (`draft`/`validated`/`published`/`rejected`), content (JSON `LessonContent`), content_hash, validation_report, review_report, source (`seed`/`generated`) | |
| `educational_resources` | url (unique), kind, title, authors, publisher, verification_status, http_status, checked_at, metadata | |
| `grading_rubrics` | key, version, criteria (JSON), content_hash | Versioned; referenced by questions |
| `assessments` | lesson_version_id, user_id, kind (`lesson`/`remediation`/`module`/`block`/`review`/`diagnostic`), pass_threshold, title | |
| `assessment_questions` | assessment_id, question_key, position, qtype, category, critical, points, objective_keys, content (JSON incl. grading spec), rubric_id, content_hash | Never updated; variants are new rows |

## Learner activity
| Table | Key columns | Notes |
|---|---|---|
| `user_lesson_progress` | user_id, lesson_id (unique pair), state, current_version_id, attempts, unlocked_at, started_at, passed_at, test_out_eligible | Progression state machine |
| `user_module_progress` | user_id, module_id, state, assessment_passed_at, project_passed_at, completed_at | |
| `lesson_activities` | user_id, lesson_version_id, section_id, completed_at | Per-section completion |
| `learning_sessions` | user_id, lesson_id, started_at, last_seen_at, active_seconds | Time tracking |
| `notes` | user_id, lesson_id, body | |
| `tutor_conversations` / `tutor_messages` | user_id, lesson_id, mode / conversation_id, role, content | |

## Assessment results (append-only)
| Table | Key columns | Notes |
|---|---|---|
| `submissions` | user_id, assessment_id, attempt, status (`submitted`/`grading`/`graded`/`needs_review`/`error`), idempotency_key (unique) | |
| `submission_artifacts` | submission_id, question_key, kind (`choice`/`numeric`/`text`/`code`/`github`/`file`), payload (JSON), storage_key | |
| `grades` | submission_id, score, passed, category_scores, objective_scores, critical_failures, summary, feedback, grader_version, superseded_by_id, created_by (`system`/`admin`) | Overrides supersede, never mutate |
| `rubric_results` | grade_id, question_key, rubric_id, score, max_score, criteria (JSON), confidence, evidence, misconceptions, missing_concepts, incorrect_claims, next_steps, meets_mastery, review_status (`auto`/`second_pass`/`flagged`/`overridden`), ai_call_ids | |

## Mastery
| Table | Key columns | Notes |
|---|---|---|
| `mastery_records` | user_id, scope (`concept`/`objective`), key, estimate (0–1), evidence_count, state, stability_days, last_evidence_at, next_review_at, lapses, prior | Unique (user, scope, key) |
| `misconceptions` | user_id, concept_key, objective_key, description, status (`open`/`resolved`), source_rubric_result_id | |
| `remediation_plans` | user_id, lesson_id, submission_id, attempt, failed_objectives, diagnosis, include_prerequisites, lesson_version_id, assessment_id, status | |
| `review_schedules` | user_id, concept_key, due_at, status (`due`/`completed`/`skipped`), assessment_id | |

## Projects
| Table | Key columns | Notes |
|---|---|---|
| `coding_projects` | module_id, key, title, spec (JSON), pass_threshold | |
| `project_milestones` | project_id, key, position, title, spec (JSON incl. tests — hidden tests never serialized to client) | |
| `project_submissions` | user_id, milestone_id, version, source (`editor`/`github`/`upload`), code, repo_url, status, test_results, review, score, passed | |

## Operations
| Table | Key columns | Notes |
|---|---|---|
| `notifications` | user_id, kind, idempotency_key (unique), payload, scheduled_for, status (`pending`/`sent`/`suppressed`/`failed`) | |
| `email_deliveries` | notification_id, provider, provider_message_id, status, attempt, error, sent_at | |
| `background_jobs` | kind, payload, status (`queued`/`running`/`succeeded`/`failed`/`dead`), attempts, max_attempts, run_at, locked_at, locked_by, last_error, idempotency_key (unique), result | |
| `audit_events` | user_id, actor, action, entity_type, entity_id, data | Append-only |
| `ai_calls` | role, model, user_id, input_tokens, output_tokens, cache_read_tokens, cost_usd, latency_ms, status, error, request_id, prompt_hash | |

## Reproducibility guarantees
- A grade references the submission, which references immutable questions (content hash) and a
  versioned rubric; the rubric result records model, prompt hash and AI call ids. Re-deriving a
  decision needs nothing that can change.
- Progression transitions write `audit_events` with before/after state and the grade id that
  caused them.
