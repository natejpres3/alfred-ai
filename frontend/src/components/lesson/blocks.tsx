"use client";

import { BookMarked, ExternalLink, FileText, Github, History, Info, KeyRound, Link2, Lightbulb, PlayCircle, TriangleAlert } from "lucide-react";

import { MathBlock, Markdown } from "@/components/markdown";
import { Badge } from "@/components/ui/primitives";
import { Widget } from "@/components/widgets";
import type { Answer, TBlock, TQuestion, TResource } from "@/lib/lesson-schema";
import { cn } from "@/lib/utils";

import { QuestionCard } from "./question-input";

const CALLOUT = {
  intuition: { icon: Lightbulb, label: "Intuition", cls: "border-l-warning bg-warning-soft/60" },
  key_idea: { icon: KeyRound, label: "Key idea", cls: "border-l-primary bg-accent" },
  warning: { icon: TriangleAlert, label: "Watch out", cls: "border-l-danger bg-danger-soft/60" },
  history: { icon: History, label: "History", cls: "border-l-muted-foreground bg-muted" },
  connection: { icon: Link2, label: "Connection", cls: "border-l-success bg-success-soft/60" },
  example: { icon: Info, label: "Example", cls: "border-l-primary bg-muted" },
} as const;

function youtubeId(url: string | null) {
  if (!url) return null;
  const m = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([\w-]{11})/);
  return m ? m[1] : null;
}

export function ResourceCard({ r, note }: { r: TResource; note?: string }) {
  const yt = r.kind === "video" ? youtubeId(r.url) : null;
  const Icon = r.kind === "video" ? PlayCircle : r.kind === "book" ? BookMarked : r.kind === "repo" ? Github : FileText;
  return (
    <div className="my-5 overflow-hidden rounded-lg border border-border bg-card font-sans">
      {yt && r.verification === "verified" && (
        <div className="aspect-video w-full bg-black">
          <iframe
            className="h-full w-full"
            src={`https://www.youtube-nocookie.com/embed/${yt}`}
            title={r.title}
            loading="lazy"
            allow="accelerometer; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
          />
        </div>
      )}
      <div className="flex gap-3 p-4">
        <Icon size={18} className="mt-0.5 shrink-0 text-muted-foreground" />
        <div className="min-w-0 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            {r.url ? (
              <a href={r.url} target="_blank" rel="noopener noreferrer" className="font-medium text-primary hover:underline">
                {r.title} <ExternalLink size={12} className="inline" />
              </a>
            ) : (
              <span className="font-medium">{r.title}</span>
            )}
            {r.verification !== "verified" && <Badge tone="warning">{r.verification === "failed" ? "link removed" : "unverified"}</Badge>}
            {r.required && <Badge tone="primary">required</Badge>}
          </div>
          <p className="text-muted-foreground">{[r.authors.join(", "), r.publisher, r.details].filter(Boolean).join(" · ")}</p>
          {(note || r.why) && <p className="mt-1">{note || r.why}</p>}
        </div>
      </div>
    </div>
  );
}

export function BlockView({ block, questions, resources, answers, setAnswer, numbering }: {
  block: TBlock;
  questions: Map<string, TQuestion>;
  resources: Map<string, TResource>;
  answers: Record<string, Answer>;
  setAnswer: (id: string, a: Answer) => void;
  numbering: Map<string, number>;
}) {
  switch (block.type) {
    case "markdown":
      return <Markdown>{block.text}</Markdown>;
    case "equation":
      return <MathBlock latex={block.latex} caption={block.caption} />;
    case "code":
      return (
        <figure className="my-5">
          <Markdown>{"```" + block.language + "\n" + block.code + "\n```"}</Markdown>
          {block.caption && <figcaption className="-mt-3 text-sm text-muted-foreground">{block.caption}</figcaption>}
        </figure>
      );
    case "callout": {
      const c = CALLOUT[block.variant];
      return (
        <aside className={cn("my-6 rounded-r-md border-l-4 px-5 py-4", c.cls)}>
          <p className="mb-1 flex items-center gap-1.5 font-sans text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <c.icon size={13} /> {c.label}: <span className="normal-case tracking-normal text-foreground">{block.title}</span>
          </p>
          <Markdown className="prose-p:my-1">{block.text}</Markdown>
        </aside>
      );
    }
    case "interactive":
      return (
        <figure className="my-6 rounded-lg border border-border bg-background p-4 font-sans">
          {block.caption && <figcaption className="mb-3 text-sm font-medium">{block.caption}</figcaption>}
          <Widget name={block.widget} params={block.params} />
          {block.instructions && (
            <div className="mt-4 rounded-md bg-muted px-4 py-3">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Try this</p>
              <Markdown compact>{block.instructions}</Markdown>
            </div>
          )}
        </figure>
      );
    case "resource": {
      const r = resources.get(block.resource_id);
      return r ? <ResourceCard r={r} note={block.note} /> : null;
    }
    case "question": {
      const q = questions.get(block.question_id);
      return q ? <QuestionCard q={q} answer={answers[q.id]} onChange={(a) => setAnswer(q.id, a)} index={numbering.get(q.id)} /> : null;
    }
  }
}
