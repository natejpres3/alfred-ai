"use client";

import { AlertTriangle, Check, ChevronDown, Quote, X } from "lucide-react";
import { useState } from "react";

import { CodeEditor } from "@/components/lesson/code-editor";
import { Markdown } from "@/components/markdown";
import { Badge, Progress } from "@/components/ui/primitives";
import type { GradedQuestion } from "@/lib/types";
import { cn, pct } from "@/lib/utils";

function List({ title, items, tone }: { title: string; items?: string[]; tone: "success" | "danger" | "warning" | "neutral" }) {
  if (!items?.length) return null;
  const color = { success: "text-success", danger: "text-danger", warning: "text-warning", neutral: "text-muted-foreground" }[tone];
  return (
    <div>
      <p className={cn("text-xs font-semibold uppercase tracking-wider", color)}>{title}</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">{items.map((i, k) => <li key={k}>{i}</li>)}</ul>
    </div>
  );
}

export function QuestionFeedback({ q, index }: { q: GradedQuestion; index: number }) {
  const [showCode, setShowCode] = useState(false);
  const frac = q.max_score ? (q.score ?? 0) / q.max_score : 0;
  const tone = frac >= 0.85 ? "success" : frac >= 0.5 ? "warning" : "danger";
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <span className="font-semibold text-muted-foreground">Q{index}</span>
        <Badge>{q.type.replace("_", " ")}</Badge>
        {q.critical && <Badge tone="warning">critical</Badge>}
        {!q.required && <Badge tone="primary">practice</Badge>}
        {q.review_status === "second_pass" && <Badge tone="neutral" title="Graded twice independently; scores averaged">double-graded</Badge>}
        {q.review_status === "flagged" && <Badge tone="danger">flagged for manual review</Badge>}
        {q.review_status === "overridden" && <Badge tone="primary">manually reviewed</Badge>}
        {q.offline_grader && <Badge tone="warning" title="AI_PROVIDER=fake: keyword heuristic, not a real grade">offline grader</Badge>}
        <span className="ml-auto font-mono text-sm">
          {q.score?.toFixed(2)} / {q.max_score}
        </span>
      </div>
      <Progress value={frac} tone={tone === "success" ? "success" : tone === "danger" ? "danger" : "primary"} className="mb-4" />
      <Markdown compact className="mb-3">{q.prompt}</Markdown>

      {/* the student's answer */}
      <div className="mb-4 rounded-md bg-muted px-4 py-3 text-sm">
        <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Your answer</p>
        {q.type === "mcq" || q.type === "multi_select" ? (
          <ul className="space-y-1">
            {q.options?.map((o) => {
              const chosen = q.answer?.selected?.includes(o.id);
              const correct = q.correct_option_ids?.includes(o.id);
              return (
                <li key={o.id} className={cn("flex items-start gap-2", correct && "text-success", chosen && !correct && "text-danger")}>
                  {correct ? <Check size={14} className="mt-1 shrink-0" /> : chosen ? <X size={14} className="mt-1 shrink-0" /> : <span className="w-3.5 shrink-0" />}
                  <Markdown compact className="prose-p:my-0">{o.text}</Markdown>
                </li>
              );
            })}
          </ul>
        ) : q.type === "numeric" ? (
          <span className="font-mono">{q.answer?.value || "—"}</span>
        ) : q.type === "code" ? (
          <>
            <button className="inline-flex items-center gap-1 text-primary" onClick={() => setShowCode(!showCode)}>
              <ChevronDown size={14} className={cn(showCode && "rotate-180")} /> {showCode ? "Hide" : "Show"} submitted code
            </button>
            {showCode && <div className="mt-2"><CodeEditor value={q.answer?.code ?? ""} readOnly height={280} /></div>}
          </>
        ) : (
          <Markdown compact>{q.answer?.text || "_No answer_"}</Markdown>
        )}
      </div>

      {/* rubric breakdown */}
      {!!q.criteria?.length && (
        <div className="mb-4 overflow-hidden rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted text-left text-xs text-muted-foreground">
              <tr><th className="px-3 py-2 font-medium">Rubric criterion</th><th className="w-20 px-3 py-2 text-right font-medium">Points</th></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {q.criteria.map((c) => (
                <tr key={c.criterion_id} className="align-top">
                  <td className="px-3 py-2">
                    <p>{c.description} {c.required_for_mastery && <span className="text-xs text-warning">(essential)</span>}</p>
                    {c.evidence.map((e, i) => (
                      <p key={i} className="mt-1 flex gap-1.5 font-serif text-xs italic text-muted-foreground"><Quote size={11} className="mt-0.5 shrink-0" />{e}</p>
                    ))}
                    {c.rationale && <p className="mt-1 text-xs text-muted-foreground">{c.rationale}</p>}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums">
                    <span className={c.points_awarded >= c.max_points ? "text-success" : c.points_awarded === 0 ? "text-danger" : ""}>{c.points_awarded.toFixed(1)}</span>/{c.max_points}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* code test results */}
      {q.tests && (
        <div className="mb-4 space-y-2 text-sm">
          {q.tests.compile_error && <p className="rounded-md bg-danger-soft px-3 py-2 font-mono text-xs text-danger">{q.tests.compile_error}</p>}
          <ul className="space-y-1">
            {q.tests.public.map((t) => (
              <li key={t.name} className="flex items-start gap-2 font-mono text-xs">
                {t.status === "passed" ? <Check size={14} className="text-success" /> : <X size={14} className="text-danger" />}
                <span>{t.name}</span>
                {t.status !== "passed" && <span className="text-danger">{t.status}: {t.message}</span>}
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted-foreground">
            Hidden tests: {q.tests.hidden.passed}/{q.tests.hidden.total} passed{q.tests.hidden.timeouts ? ` (${q.tests.hidden.timeouts} timed out)` : ""}. Hidden test details are not shown, by design.
          </p>
          {q.tests.stdout && <pre className="max-h-40 overflow-auto rounded-md bg-muted p-2 font-mono text-xs">{q.tests.stdout}</pre>}
        </div>
      )}
      {!!q.static_violations?.length && (
        <div className="mb-4 flex gap-2 rounded-md bg-warning-soft px-3 py-2 text-sm text-warning">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          <ul>{q.static_violations.map((v, i) => <li key={i}>{v}</li>)}</ul>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <List title="Demonstrated" items={q.correct_concepts} tone="success" />
        <List title="Missing" items={q.missing_concepts} tone="warning" />
        <List title="Incorrect claims" items={q.incorrect_claims} tone="danger" />
        <List title="Likely misconceptions" items={q.misconceptions} tone="danger" />
      </div>
      {q.feedback && <Markdown compact className="mt-4">{q.feedback}</Markdown>}
      {q.explanation && (
        <div className="mt-4 rounded-md border-l-4 border-l-primary bg-accent px-4 py-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Explanation</p>
          <Markdown compact>{q.explanation}</Markdown>
        </div>
      )}
      <List title="Next steps" items={q.next_steps} tone="neutral" />
      {q.grader === "rubric_llm" && q.confidence !== undefined && <p className="mt-3 text-xs text-muted-foreground">Grader confidence {pct(q.confidence)}</p>}
    </div>
  );
}
