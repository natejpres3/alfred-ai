"use client";

import { CheckCircle2, ChevronDown, Circle, CircleDashed, FolderGit2, Lock, PlayCircle, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";

import { AppShell, PageTitle } from "@/components/app-shell";
import { Badge, Card, Spinner } from "@/components/ui/primitives";
import { cn, pct } from "@/lib/utils";

type Lesson = { id: string; key: string; title: string; kind: string; state: string; estimated_minutes: number; authored: boolean; best_score: number | null };
type Module = { id: string; key: string; title: string; description: string; state: string; project: { key: string; title: string } | null; lessons: Lesson[] };
type Block = { key: string; title: string; description: string; status: string; topics: string[]; modules: Module[] };

const ICON: Record<string, React.ReactNode> = {
  passed: <CheckCircle2 size={16} className="text-success" />,
  available: <PlayCircle size={16} className="text-primary" />,
  in_progress: <PlayCircle size={16} className="text-primary" />,
  remediation_required: <RotateCcw size={16} className="text-warning" />,
  submitted: <CircleDashed size={16} className="text-primary" />,
  grading: <CircleDashed size={16} className="text-primary" />,
  locked: <Lock size={14} className="text-muted-foreground" />,
};

const MODULE_TONE: Record<string, "success" | "primary" | "warning" | "neutral"> = {
  completed: "success",
  in_progress: "primary",
  available: "primary",
  project_pending: "warning",
  assessment_pending: "warning",
  locked: "neutral",
};

export default function RoadmapPage() {
  const { data } = useSWR<{ blocks: Block[] }>("/api/curriculum");
  const [open, setOpen] = useState<Record<string, boolean>>({ b01: true });
  if (!data) return <AppShell><Spinner /></AppShell>;
  return (
    <AppShell>
      <PageTitle eyebrow="Curriculum" title="Roadmap">
        Eighteen blocks from mathematical foundations to a full capstone. Each module unlocks only when the previous one&apos;s lessons, assessment and project gate are passed.
      </PageTitle>
      <ol className="space-y-3">
        {data.blocks.map((b, bi) => {
          const lessons = b.modules.flatMap((m) => m.lessons);
          const passed = lessons.filter((l) => l.state === "passed").length;
          const isOpen = open[b.key] ?? false;
          return (
            <li key={b.key}>
              <Card className={cn(b.status === "outline" && "bg-transparent")}>
                <button className="flex w-full items-center gap-4 px-5 py-4 text-left" onClick={() => setOpen({ ...open, [b.key]: !isOpen })}>
                  <span className="font-mono text-sm text-muted-foreground">{String(bi + 1).padStart(2, "0")}</span>
                  <span className="flex-1">
                    <span className="font-serif text-lg font-semibold">{b.title}</span>
                    {b.status === "outline" && <span className="ml-2 text-xs text-muted-foreground">outline · lessons specified when you get here</span>}
                  </span>
                  {lessons.length > 0 && <span className="text-sm text-muted-foreground">{passed}/{lessons.length}</span>}
                  <ChevronDown size={16} className={cn("transition-transform", isOpen && "rotate-180")} />
                </button>
                {isOpen && (
                  <div className="border-t border-border px-5 py-4">
                    {b.status === "outline" ? (
                      <div className="flex flex-wrap gap-1.5">{b.topics.map((t) => <Badge key={t}>{t}</Badge>)}</div>
                    ) : (
                      <div className="space-y-5">
                        {b.modules.map((m) => (
                          <div key={m.id}>
                            <div className="mb-2 flex flex-wrap items-center gap-2">
                              <h3 className="font-semibold">{m.title}</h3>
                              <Badge tone={MODULE_TONE[m.state] ?? "neutral"}>{m.state.replace("_", " ")}</Badge>
                              {m.project && (
                                <Link href={`/projects/${m.project.key}`} className={cn("inline-flex items-center gap-1 text-xs text-primary hover:underline", m.state === "locked" && "pointer-events-none opacity-50")}>
                                  <FolderGit2 size={13} /> {m.project.title}
                                </Link>
                              )}
                            </div>
                            <ul className="divide-y divide-border rounded-md border border-border">
                              {m.lessons.map((l) => {
                                const inner = (
                                  <>
                                    <span className="w-5">{ICON[l.state] ?? <Circle size={16} />}</span>
                                    <span className={cn("flex-1", l.state === "locked" && "text-muted-foreground")}>{l.title}</span>
                                    {l.kind !== "lesson" && <Badge tone="primary">{l.kind === "module_assessment" ? "checkpoint" : "block exam"}</Badge>}
                                    {!l.authored && l.kind === "lesson" && <span className="hidden text-xs text-muted-foreground sm:inline">generated on unlock</span>}
                                    {l.best_score !== null && <span className="font-mono text-xs">{pct(l.best_score)}</span>}
                                    <span className="w-12 text-right text-xs text-muted-foreground">{l.estimated_minutes}m</span>
                                  </>
                                );
                                return (
                                  <li key={l.id}>
                                    {l.state === "locked" ? (
                                      <div className="flex items-center gap-3 px-3 py-2 text-sm">{inner}</div>
                                    ) : (
                                      <Link href={`/lessons/${l.id}`} className="flex items-center gap-3 px-3 py-2 text-sm hover:bg-muted">{inner}</Link>
                                    )}
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </Card>
            </li>
          );
        })}
      </ol>
    </AppShell>
  );
}
