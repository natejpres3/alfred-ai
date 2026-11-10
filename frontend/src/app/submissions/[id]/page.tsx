"use client";

import { ArrowRight, CheckCircle2, Clock, RotateCcw, ShieldAlert, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";

import { AppShell, PageTitle } from "@/components/app-shell";
import { QuestionFeedback } from "@/components/feedback/question-feedback";
import { Badge, Card, CardBody, CardHeader, CardTitle, Progress, Spinner } from "@/components/ui/primitives";
import type { SubmissionView } from "@/lib/types";
import { pct } from "@/lib/utils";

export default function SubmissionPage() {
  const { id } = useParams<{ id: string }>();
  const { data } = useSWR<SubmissionView>(`/api/submissions/${id}`, { refreshInterval: (d) => (d && !d.grade && d.status !== "error" ? 2000 : 0) });
  if (!data) return <AppShell><Spinner /></AppShell>;
  const g = data.grade;
  const lessonHref = data.assessment.lesson_id ? `/lessons/${data.assessment.lesson_id}` : "/";

  if (!g)
    return (
      <AppShell>
        <Card className="mx-auto max-w-xl p-8 text-center">
          {data.status === "error" ? (
            <>
              <ShieldAlert className="mx-auto mb-3 text-danger" />
              <h1 className="font-serif text-2xl font-semibold">Grading failed</h1>
              <p className="mt-2 text-muted-foreground">Your work is saved. Grading will be retried; an admin can also re-run it from the Admin page.</p>
            </>
          ) : (
            <>
              <Spinner className="mx-auto mb-3 text-primary" />
              <h1 className="font-serif text-2xl font-semibold">Grading your work…</h1>
              <p className="mt-2 text-muted-foreground">Objective items are checked instantly; explanations are graded against rubrics (twice when borderline); code runs in an isolated sandbox. This page updates automatically.</p>
            </>
          )}
        </Card>
      </AppShell>
    );

  const graded = g.questions.filter((q) => q.score !== undefined);
  return (
    <AppShell>
      <PageTitle eyebrow={`${data.assessment.title} · attempt ${data.attempt}`} title={g.needs_review ? "Awaiting manual review" : g.passed ? "Passed" : "Not yet — here's exactly what to work on"} />
      <div className="mb-8 grid gap-4 md:grid-cols-3">
        <Card className="p-5">
          <div className="flex items-center gap-3">
            {g.needs_review ? <Clock className="text-warning" /> : g.passed ? <CheckCircle2 className="text-success" /> : <XCircle className="text-danger" />}
            <span className="font-serif text-4xl font-semibold">{pct(g.score)}</span>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">Pass mark {pct(data.assessment.threshold)} overall, plus every category and critical objective.</p>
          {g.created_by === "admin" && <Badge tone="primary" className="mt-2">manually reviewed</Badge>}
        </Card>
        <Card className="md:col-span-2">
          <CardHeader><CardTitle>Summary</CardTitle></CardHeader>
          <CardBody className="space-y-2 text-sm">
            <p>{g.summary}</p>
            {!g.passed && !g.needs_review && (
              <Link href={lessonHref} className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
                <RotateCcw size={14} /> Go to your targeted review
              </Link>
            )}
            {g.passed && (
              <Link href="/" className="inline-flex items-center gap-1 font-medium text-primary hover:underline">
                Continue to the next lesson <ArrowRight size={14} />
              </Link>
            )}
          </CardBody>
        </Card>
      </div>

      <div className="mb-10 grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>By category</CardTitle></CardHeader>
          <CardBody className="space-y-3">
            {Object.entries(g.category_scores).map(([k, v]) => (
              <div key={k}>
                <div className="mb-1 flex justify-between text-sm"><span className="capitalize">{k}</span><span className="font-mono">{pct(v)}</span></div>
                <Progress value={v} tone={v >= 0.85 ? "success" : "danger"} />
              </div>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader><CardTitle>By learning objective</CardTitle></CardHeader>
          <CardBody className="space-y-3">
            {Object.entries(g.objective_scores).map(([k, v]) => (
              <div key={k}>
                <div className="mb-1 flex justify-between gap-3 text-sm">
                  <span>{g.objective_statements[k] ?? k} {g.critical_failures.includes(k) && <Badge tone="danger">below mastery</Badge>}</span>
                  <span className="font-mono">{pct(v)}</span>
                </div>
                <Progress value={v} tone={v >= 0.85 ? "success" : "danger"} />
              </div>
            ))}
          </CardBody>
        </Card>
      </div>

      <h2 className="mb-4 font-serif text-2xl font-semibold">Question-by-question feedback</h2>
      <div className="space-y-5">
        {graded.map((q, i) => <QuestionFeedback key={q.key} q={q} index={i + 1} />)}
      </div>
      <p className="mt-8 text-xs text-muted-foreground">Grader version {g.grader_version}. Every grading decision is stored with its rubric version and an audit trail.</p>
    </AppShell>
  );
}
