"use client";

import { ArrowRight, BookOpen, Clock, Flame, FolderGit2, RotateCcw } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";

import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, CardBody, CardHeader, CardTitle, EmptyState, Progress, Spinner } from "@/components/ui/primitives";
import { pct } from "@/lib/utils";

type Dashboard = {
  user: { display_name: string; email_verified: boolean };
  onboarded: boolean;
  current: null | { lesson_id: string; title: string; state: string; kind: string; prepared: boolean; estimated_minutes: number; block: { title: string }; module: { title: string } };
  progress: { lessons_passed: number; lessons_total: number; blocks_total: number; outline_topics_remaining: number; percent_known: number };
  workload: { remaining_specified_hours: number; remaining_outline_hours_estimate: number; daily_goal_minutes: number; studied_last_24h_minutes: number };
  streak_days: number;
  recent_grades: { submission_id: string; title: string; kind: string; score: number; passed: boolean; needs_review: boolean; at: string }[];
  mastered: { key: string; name: string; estimate: number }[];
  needs_review: { key: string; name: string; state: string; estimate: number }[];
  reviews_due: number;
  available: { lesson_id: string; title: string; state: string }[];
  projects: { key: string; title: string; passed: boolean; score: number; milestones_passed: number; milestones_total: number }[];
  history: { at: string; action: string; data: Record<string, unknown> }[];
};

const STATE_COPY: Record<string, string> = {
  available: "Ready to start",
  in_progress: "In progress",
  remediation_required: "Targeted review ready",
  submitted: "Submitted",
  grading: "Being graded",
};

function describe(h: Dashboard["history"][number]) {
  const d = h.data as Record<string, string>;
  if (h.action === "lesson_progress.transition") return `Lesson ${d.before?.replace("_", " ")} → ${d.after?.replace("_", " ")}`;
  if (h.action === "submission.graded") return `Graded: ${pct(Number(d.score))}${d.passed ? " · passed" : ""}`;
  if (h.action === "remediation.created") return "Targeted review generated";
  if (h.action === "project.submitted") return "Project milestone submitted";
  return h.action;
}

export default function DashboardPage() {
  const { data } = useSWR<Dashboard>("/api/dashboard", { refreshInterval: (d) => (d?.current && !d.current.prepared ? 4000 : 0) });
  if (!data) return <AppShell><Spinner /></AppShell>;
  const goal = data.workload.daily_goal_minutes;

  return (
    <AppShell>
      <div className="mb-8 flex flex-wrap items-end gap-4">
        <div>
          <p className="text-sm text-muted-foreground">{new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</p>
          <h1 className="font-serif text-3xl font-semibold tracking-tight">{data.user.display_name ? `Welcome back, ${data.user.display_name}` : "Welcome back"}</h1>
        </div>
        <div className="ml-auto flex items-center gap-4 text-sm text-muted-foreground">
          <span className="inline-flex items-center gap-1.5"><Flame size={15} className={data.streak_days ? "text-warning" : ""} /> {data.streak_days}-day streak</span>
          <span className="inline-flex items-center gap-1.5"><Clock size={15} /> {data.workload.studied_last_24h_minutes}/{goal} min today</span>
        </div>
      </div>
      {!data.user.email_verified && (
        <Card className="mb-6 border-warning/40 bg-warning-soft/40 px-5 py-3 text-sm">Confirm your email address (check your inbox) so lesson notifications can reach you.</Card>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardBody className="p-6">
            {data.current ? (
              <>
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{data.current.block.title} · {data.current.module.title}</p>
                <h2 className="mt-2 font-serif text-2xl font-semibold">{data.current.title}</h2>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                  <Badge tone={data.current.state === "remediation_required" ? "warning" : "primary"}>{STATE_COPY[data.current.state] ?? data.current.state}</Badge>
                  <span>~{data.current.estimated_minutes} min</span>
                </div>
                <div className="mt-6">
                  {data.current.prepared ? (
                    <Link href={`/lessons/${data.current.lesson_id}`}>
                      <Button size="lg">{data.current.state === "available" ? "Start lesson" : "Continue"} <ArrowRight size={16} /></Button>
                    </Link>
                  ) : (
                    <span className="inline-flex items-center gap-2 text-sm text-muted-foreground"><Spinner /> Preparing your lesson…</span>
                  )}
                </div>
              </>
            ) : (
              <EmptyState title="Nothing to do right now">You&apos;re waiting on a project gate or a review. Check the roadmap.</EmptyState>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader><CardTitle>Program progress</CardTitle></CardHeader>
          <CardBody className="space-y-4 text-sm">
            <div>
              <div className="mb-1 flex justify-between"><span>Specified lessons passed</span><span className="font-mono">{data.progress.lessons_passed}/{data.progress.lessons_total}</span></div>
              <Progress value={data.progress.lessons_passed / Math.max(1, data.progress.lessons_total)} />
            </div>
            <p className="text-muted-foreground">
              ~{data.workload.remaining_specified_hours} h left in specified lessons, plus ~{data.workload.remaining_outline_hours_estimate} h across {data.progress.blocks_total - 1} outlined blocks.
            </p>
            <Link href="/roadmap" className="inline-flex items-center gap-1 text-primary hover:underline">Open the roadmap <ArrowRight size={14} /></Link>
          </CardBody>
        </Card>

        <Card>
          <CardHeader><CardTitle>Recent grades</CardTitle></CardHeader>
          <CardBody>
            {data.recent_grades.length === 0 ? (
              <p className="text-sm text-muted-foreground">No graded work yet.</p>
            ) : (
              <ul className="divide-y divide-border text-sm">
                {data.recent_grades.map((g) => (
                  <li key={g.submission_id}>
                    <Link href={`/submissions/${g.submission_id}`} className="flex items-center gap-2 py-2 hover:text-primary">
                      <span className="flex-1 truncate">{g.title}</span>
                      <span className="font-mono">{pct(g.score)}</span>
                      <Badge tone={g.needs_review ? "warning" : g.passed ? "success" : "danger"}>{g.needs_review ? "review" : g.passed ? "pass" : "retry"}</Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader><CardTitle>Mastery</CardTitle></CardHeader>
          <CardBody className="space-y-3 text-sm">
            {data.needs_review.length > 0 && (
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-warning">Needs attention</p>
                <div className="flex flex-wrap gap-1.5">{data.needs_review.map((c) => <Badge key={c.key} tone={c.state === "needs_remediation" ? "danger" : "warning"}>{c.name}</Badge>)}</div>
              </div>
            )}
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-success">Mastered ({data.mastered.length})</p>
              {data.mastered.length ? (
                <div className="flex flex-wrap gap-1.5">{data.mastered.map((c) => <Badge key={c.key} tone="success">{c.name}</Badge>)}</div>
              ) : (
                <p className="text-muted-foreground">Concepts appear here once you pass an assessment on them.</p>
              )}
            </div>
            {data.reviews_due > 0 && (
              <Link href="/reviews" className="inline-flex items-center gap-1 text-primary hover:underline"><RotateCcw size={14} /> {data.reviews_due} concept review{data.reviews_due > 1 ? "s" : ""} due</Link>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader><CardTitle>Projects</CardTitle></CardHeader>
          <CardBody className="space-y-3 text-sm">
            {data.projects.length === 0 ? (
              <p className="text-muted-foreground">Module projects unlock with their modules.</p>
            ) : (
              data.projects.map((p) => (
                <Link key={p.key} href={`/projects/${p.key}`} className="block rounded-md border border-border p-3 hover:bg-muted">
                  <div className="flex items-center gap-2"><FolderGit2 size={15} /> <span className="flex-1 font-medium">{p.title}</span>{p.passed && <Badge tone="success">passed</Badge>}</div>
                  <Progress className="mt-2" value={p.milestones_passed / p.milestones_total} tone={p.passed ? "success" : "primary"} />
                  <p className="mt-1 text-xs text-muted-foreground">{p.milestones_passed}/{p.milestones_total} milestones at ≥90%</p>
                </Link>
              ))
            )}
          </CardBody>
        </Card>

        <Card className="lg:col-span-3">
          <CardHeader><CardTitle>Recent activity</CardTitle></CardHeader>
          <CardBody>
            {data.history.length === 0 ? (
              <p className="text-sm text-muted-foreground"><BookOpen size={14} className="mr-1 inline" /> Your learning history will appear here.</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {data.history.map((h, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="w-36 shrink-0 text-muted-foreground">{new Date(h.at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</span>
                    <span>{describe(h)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>
    </AppShell>
  );
}
