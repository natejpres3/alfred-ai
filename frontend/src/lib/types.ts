import type { TLessonContent } from "./lesson-schema";

export type Me = { id: string; email: string; display_name: string; is_admin: boolean; email_verified: boolean; onboarded: boolean };

export type LessonState = "locked" | "available" | "in_progress" | "submitted" | "grading" | "passed" | "remediation_required";

export type LessonPayload = {
  id: string;
  key: string;
  title: string;
  kind: string;
  state: LessonState;
  block: { key: string; title: string; position: number };
  module: { id: string; key: string; title: string; position: number };
  test_out_eligible: boolean;
  attempts: number;
  best_score: number | null;
  locked_reason?: string;
  preparing?: boolean;
  version_id?: string;
  source?: string;
  content?: TLessonContent;
  completed_sections?: string[];
  note?: string;
  assessment?: { id: string; kind: string; threshold: number } | null;
  remediation?: { preparing?: boolean; version_id?: string; content?: TLessonContent; completed_sections?: string[]; failed_objectives?: string[]; prerequisites?: string[] } | null;
  submissions?: { submission_id: string; attempt: number; status: string; submitted_at: string; score: number | null; passed: boolean | null }[];
  tutor?: { available: boolean; reason: string };
};

export type Criterion = {
  criterion_id: string;
  description: string;
  points_awarded: number;
  max_points: number;
  evidence: string[];
  rationale: string;
  required_for_mastery?: boolean;
  second_pass_points?: number;
};

export type GradedQuestion = {
  key: string;
  type: string;
  category: string;
  critical: boolean;
  required: boolean;
  prompt: string;
  options?: { id: string; text: string }[] | null;
  answer?: { selected?: string[]; value?: string; text?: string; code?: string } | null;
  score?: number;
  max_score?: number;
  feedback?: string;
  criteria?: Criterion[];
  correct_concepts?: string[];
  missing_concepts?: string[];
  incorrect_claims?: string[];
  misconceptions?: string[];
  next_steps?: string[];
  meets_mastery?: boolean;
  confidence?: number;
  review_status?: string;
  grader?: string;
  explanation?: string;
  offline_grader?: boolean;
  tests?: { public: { name: string; status: string; message: string }[]; hidden: { passed: number; total: number; timeouts: number }; stdout: string; compile_error: string | null; pass_rate: number } | null;
  static_violations?: string[];
  correct_option_ids?: string[] | null;
};

export type SubmissionView = {
  id: string;
  status: string;
  attempt: number;
  submitted_at: string;
  assessment: { id: string; kind: string; title: string; threshold: number; lesson_id: string | null };
  grade: null | {
    id: string;
    score: number;
    passed: boolean;
    needs_review: boolean;
    summary: string;
    category_scores: Record<string, number>;
    objective_scores: Record<string, number>;
    objective_statements: Record<string, string>;
    critical_failures: string[];
    failure_reasons: string[];
    grader_version: string;
    created_by: string;
    questions: GradedQuestion[];
  };
};
