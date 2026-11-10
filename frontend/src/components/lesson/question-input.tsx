"use client";

import { ChevronDown, Lightbulb, Star } from "lucide-react";
import { useState } from "react";

import { Markdown } from "@/components/markdown";
import { Badge, Input, Textarea } from "@/components/ui/primitives";
import type { Answer, TQuestion } from "@/lib/lesson-schema";
import { cn } from "@/lib/utils";

import { CodeEditor } from "./code-editor";

const TYPE_LABEL: Record<string, string> = {
  mcq: "Multiple choice",
  multi_select: "Select all that apply",
  numeric: "Numeric",
  short_answer: "Short explanation",
  long_answer: "Explanation",
  derivation: "Derivation",
  code: "Code",
};

export function isAnswered(q: TQuestion, a: Answer | undefined) {
  if (!a) return false;
  if (q.type === "mcq" || q.type === "multi_select") return (a.selected?.length ?? 0) > 0;
  if (q.type === "numeric") return !!a.value?.trim();
  if (q.type === "code") return !!a.code?.trim() && a.code.trim() !== q.code?.starter_code.trim();
  return !!a.text?.trim();
}

export function QuestionCard({ q, answer, onChange, index }: { q: TQuestion; answer: Answer | undefined; onChange: (a: Answer) => void; index?: number }) {
  const [hints, setHints] = useState(0);
  const [showTests, setShowTests] = useState(false);
  const answered = isAnswered(q, answer);

  return (
    <div className={cn("my-6 rounded-lg border bg-card p-5 font-sans", answered ? "border-border" : "border-border")} id={`q-${q.id}`}>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        {index !== undefined && <span className="font-semibold text-muted-foreground">Q{index}</span>}
        <Badge>{TYPE_LABEL[q.type]}</Badge>
        {q.critical && (
          <Badge tone="warning" title="Must meet the mastery bar on its own">
            <Star size={11} /> critical
          </Badge>
        )}
        {!q.required && <Badge tone="primary">practice · not graded toward pass</Badge>}
        <span className="ml-auto text-muted-foreground">{q.points} pt{q.points === 1 ? "" : "s"}</span>
      </div>
      <Markdown className="mb-4">{q.prompt}</Markdown>

      {(q.type === "mcq" || q.type === "multi_select") && (
        <div className="space-y-2" role={q.type === "mcq" ? "radiogroup" : "group"}>
          {q.options?.map((o) => {
            const selected = answer?.selected?.includes(o.id) ?? false;
            return (
              <label key={o.id} className={cn("flex cursor-pointer items-start gap-3 rounded-md border px-3 py-2.5 text-sm transition-colors", selected ? "border-primary bg-accent" : "border-border hover:bg-muted")}>
                <input
                  type={q.type === "mcq" ? "radio" : "checkbox"}
                  name={q.id}
                  className="mt-1"
                  checked={selected}
                  onChange={() => {
                    const cur = new Set(answer?.selected ?? []);
                    if (q.type === "mcq") onChange({ selected: [o.id] });
                    else {
                      if (cur.has(o.id)) cur.delete(o.id);
                      else cur.add(o.id);
                      onChange({ selected: [...cur] });
                    }
                  }}
                />
                <Markdown compact className="prose-p:my-0">{o.text}</Markdown>
              </label>
            );
          })}
        </div>
      )}

      {q.type === "numeric" && (
        <div className="max-w-xs">
          <Input inputMode="decimal" placeholder="e.g. 0.75, 3/4, sqrt(2)/2" value={answer?.value ?? ""} onChange={(e) => onChange({ value: e.target.value })} />
          <p className="mt-1 text-xs text-muted-foreground">Fractions and simple expressions (pi, sqrt) are accepted.</p>
        </div>
      )}

      {(q.type === "short_answer" || q.type === "long_answer" || q.type === "derivation") && (
        <div>
          <Textarea
            rows={q.type === "short_answer" ? 5 : 9}
            placeholder={q.type === "derivation" ? "Show each step. LaTeX like $\\frac{dy}{dx}$ is fine." : "Explain in your own words. Concise and correct beats long."}
            value={answer?.text ?? ""}
            onChange={(e) => onChange({ text: e.target.value })}
            className="font-serif text-[0.98rem]"
          />
          {answer?.text && /\$/.test(answer.text) && (
            <div className="mt-2 rounded-md bg-muted px-3 py-2">
              <p className="mb-1 text-xs text-muted-foreground">Preview</p>
              <Markdown compact>{answer.text}</Markdown>
            </div>
          )}
        </div>
      )}

      {q.type === "code" && q.code && (
        <div className="space-y-2">
          <CodeEditor value={answer?.code ?? q.code.starter_code} onChange={(code) => onChange({ code })} />
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>Required: {q.code.required_functions.map((f) => <code key={f} className="mr-1 rounded bg-muted px-1">{f}</code>)}</span>
            <span>· Allowed imports: {q.code.allowed_imports?.length ? q.code.allowed_imports.join(", ") : "none"}</span>
            <span>· Hidden tests run on submission</span>
          </div>
          {q.code.public_tests.length > 0 && (
            <div>
              <button className="inline-flex items-center gap-1 text-xs text-primary" onClick={() => setShowTests(!showTests)}>
                <ChevronDown size={14} className={cn("transition-transform", showTests && "rotate-180")} /> Public tests ({q.code.public_tests.length})
              </button>
              {showTests && (
                <pre className="mt-2 overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs">{q.code.public_tests.map((t) => t.code).join("\n")}</pre>
              )}
            </div>
          )}
        </div>
      )}

      {q.hints.length > 0 && (
        <div className="mt-4 border-t border-border pt-3">
          {q.hints.slice(0, hints).map((h, i) => (
            <div key={i} className="mb-2 flex gap-2 text-sm">
              <Lightbulb size={15} className="mt-0.5 shrink-0 text-warning" />
              <Markdown compact className="prose-p:my-0">{h}</Markdown>
            </div>
          ))}
          {hints < q.hints.length && (
            <button className="text-xs text-primary hover:underline" onClick={() => setHints(hints + 1)}>
              {hints === 0 ? "Show a hint" : "Show a more explicit hint"} ({hints}/{q.hints.length})
            </button>
          )}
        </div>
      )}
    </div>
  );
}
