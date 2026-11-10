/**
 * Student-view lesson schema. Mirrors backend/app/schemas/lesson.py (LessonContent.student_view()):
 * grading data and the variant bank are never sent to the browser.
 */
import { z } from "zod";

export const Objective = z.object({
  id: z.string(),
  statement: z.string(),
  concept_key: z.string(),
  critical: z.boolean(),
  bloom: z.string().optional(),
});

export const Resource = z.object({
  id: z.string(),
  kind: z.enum(["video", "article", "book", "paper", "docs", "course", "repo"]),
  title: z.string(),
  url: z.string().nullable(),
  authors: z.array(z.string()).default([]),
  publisher: z.string().default(""),
  details: z.string().default(""),
  why: z.string().default(""),
  required: z.boolean().default(false),
  verification: z.enum(["verified", "unverified", "failed"]),
});

export const CodeTest = z.object({ name: z.string(), code: z.string(), weight: z.number().default(1) });

export const Question = z.object({
  id: z.string(),
  type: z.enum(["mcq", "multi_select", "numeric", "short_answer", "long_answer", "derivation", "code"]),
  category: z.enum(["conceptual", "math", "coding", "recall"]),
  prompt: z.string(),
  objective_ids: z.array(z.string()),
  critical: z.boolean().default(false),
  required: z.boolean().default(true),
  points: z.number().default(1),
  options: z.array(z.object({ id: z.string(), text: z.string() })).nullable().optional(),
  code: z
    .object({
      language: z.string(),
      starter_code: z.string(),
      required_functions: z.array(z.string()),
      public_tests: z.array(CodeTest),
      allowed_imports: z.array(z.string()).nullable().optional(),
      time_limit_seconds: z.number(),
    })
    .nullable()
    .optional(),
  hints: z.array(z.string()).default([]),
});

const Param = z.object({ name: z.string(), value: z.number() });

export const Block = z.discriminatedUnion("type", [
  z.object({ type: z.literal("markdown"), text: z.string() }),
  z.object({ type: z.literal("equation"), latex: z.string(), caption: z.string().default("") }),
  z.object({ type: z.literal("code"), language: z.string(), code: z.string(), caption: z.string().default(""), runnable: z.boolean().default(false) }),
  z.object({
    type: z.literal("callout"),
    variant: z.enum(["intuition", "key_idea", "warning", "history", "connection", "example"]),
    title: z.string(),
    text: z.string(),
  }),
  z.object({
    type: z.literal("interactive"),
    widget: z.string(),
    params: z.array(Param).default([]),
    caption: z.string().default(""),
    instructions: z.string().default(""),
  }),
  z.object({ type: z.literal("resource"), resource_id: z.string(), note: z.string().default("") }),
  z.object({ type: z.literal("question"), question_id: z.string() }),
]);

export const Section = z.object({
  id: z.string(),
  kind: z.string(),
  title: z.string(),
  estimated_minutes: z.number(),
  required: z.boolean().default(true),
  blocks: z.array(Block),
});

export const LessonContent = z.object({
  lesson_key: z.string(),
  title: z.string(),
  subtitle: z.string().default(""),
  summary: z.string(),
  why_it_matters: z.string(),
  objectives: z.array(Objective),
  prerequisites: z.array(z.string()),
  connections: z.array(z.object({ concept_key: z.string(), direction: z.string(), note: z.string() })).default([]),
  estimated_minutes: z.number(),
  sections: z.array(Section),
  questions: z.array(Question),
  resources: z.array(Resource).default([]),
  homework: z.array(z.string()).default([]),
  completion: z.object({
    required_section_ids: z.array(z.string()),
    required_question_ids: z.array(z.string()),
    pass_threshold: z.number(),
  }),
});

export type TLessonContent = z.infer<typeof LessonContent>;
export type TQuestion = z.infer<typeof Question>;
export type TBlock = z.infer<typeof Block>;
export type TSection = z.infer<typeof Section>;
export type TResource = z.infer<typeof Resource>;
export type Answer = { selected?: string[]; value?: string; text?: string; code?: string };
