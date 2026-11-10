"use client";

import { ArrowRight, Bot, Check, CheckCircle2, Circle, Clock, Lock, NotebookPen, RotateCcw, Target } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";

import { AppShell } from "@/components/app-shell";
import { BlockView, ResourceCard } from "@/components/lesson/blocks";
import { NotesPanel } from "@/components/lesson/notes-panel";
import { isAnswered } from "@/components/lesson/question-input";
import { TutorPanel } from "@/components/lesson/tutor-panel";
import { Markdown } from "@/components/markdown";
import { Badge, Button, Card, Progress, Spinner } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { type Answer, LessonContent, type TLessonContent } from "@/lib/lesson-schema";
import type { LessonPayload } from "@/lib/types";
import { cn, newKey, pct, safeStorage } from "@/lib/utils";

const SECTION_LABEL: Record<string, string> = {
  retrieval: "Warm-up",
  concept: "Concept",
  math: "Math",
  demo: "Demo",
  recall: "Recall",
  coding: "Coding",
  summary: "Summary",
  remediation: "Review",
};

export default function LessonPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data, mutate, error } = useSWR<LessonPayload>(`/api/lessons/${id}`, {
    refreshInterval: (d) => (d?.preparing || d?.remediation?.preparing || d?.state === "grading" || d?.state === "submitted" ? 3000 : 0),
  });
  const [tutorOpen, setTutorOpen] = useState(false);
  const [notesOpen, setNotesOpen] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);

  // ---- session tracking (start + heartbeat while visible)
  const sessionRef = useRef<string | null>(null);
  const startedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!data?.content || data.state === "locked" || startedFor.current === id) return;
    startedFor.current = id;
    api<{ session_id: string }>(`/api/lessons/${id}/start`, { method: "POST" }).then((r) => {
      sessionRef.current = r.session_id;
      mutate();
    });
  }, [data?.content, data?.state, id, mutate]);
  useEffect(() => {
    const t = setInterval(() => {
      if (sessionRef.current && document.visibilityState === "visible")
        api(`/api/lessons/${id}/heartbeat`, { method: "POST", json: { session_id: sessionRef.current, seconds: 60 } }).catch(() => {});
    }, 60_000);
    return () => clearInterval(t);
  }, [id]);

  const remediationActive = !!data?.remediation?.content && !showOriginal;
  const content: TLessonContent | null = useMemo(() => {
    const raw = remediationActive ? data?.remediation?.content : data?.content;
    if (!raw) return null;
    const parsed = LessonContent.safeParse(raw);
    return parsed.success ? parsed.data : (raw as TLessonContent);
  }, [data, remediationActive]);
  const versionId = remediationActive ? data?.remediation?.version_id : data?.version_id;
  const completed = new Set(remediationActive ? data?.remediation?.completed_sections : data?.completed_sections);
  const assessmentId = data?.assessment?.id;
  const canAnswer = !!data && ["available", "in_progress", "remediation_required"].includes(data.state) && (!data.remediation || remediationActive || !data.remediation.content);

  // ---- answers (drafts persisted per assessment in this browser)
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  useEffect(() => {
    if (assessmentId) setAnswers(safeStorage.get(`draft:${assessmentId}`, {}));
  }, [assessmentId]);
  const setAnswer = useCallback(
    (qid: string, a: Answer) => {
      setAnswers((prev) => {
        const next = { ...prev, [qid]: a };
        if (assessmentId) safeStorage.set(`draft:${assessmentId}`, next);
        return next;
      });
    },
    [assessmentId],
  );

  const questions = useMemo(() => new Map(content?.questions.map((q) => [q.id, q]) ?? []), [content]);
  const resources = useMemo(() => new Map(content?.resources.map((r) => [r.id, r]) ?? []), [content]);
  const numbering = useMemo(() => {
    const m = new Map<string, number>();
    let n = 1;
    content?.sections.forEach((s) => s.blocks.forEach((b) => b.type === "question" && !m.has(b.question_id) && m.set(b.question_id, n++)));
    return m;
  }, [content]);

  async function markComplete(sectionId: string) {
    if (!versionId) return;
    await api(`/api/lessons/${id}/sections/${sectionId}/complete`, { method: "POST", json: { version_id: versionId } });
    mutate();
  }

  const [submitKey, setSubmitKey] = useState(newKey);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  async function submit(testOut = false) {
    if (!assessmentId) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const payload = Object.fromEntries(Object.entries(answers).filter(([k]) => questions.has(k)));
      const r = await api<{ submission_id: string }>(`/api/assessments/${assessmentId}/submissions`, {
        method: "POST",
        json: { answers: payload, idempotency_key: submitKey, test_out: testOut },
      });
      safeStorage.remove(`draft:${assessmentId}`);
      setSubmitKey(newKey());
      router.push(`/submissions/${r.submission_id}`);
    } catch (e) {
      const d = e instanceof ApiError ? (e.detail as { message?: string; missing_sections?: string[] } | string) : null;
      setSubmitError(typeof d === "string" ? d : d?.message ? `${d.message}${d.missing_sections ? ` Missing: ${d.missing_sections.join(", ")}` : ""}` : "Submission failed.");
    } finally {
      setSubmitting(false);
    }
  }

  if (error) return <AppShell><p className="text-danger">{error.message}</p></AppShell>;
  if (!data) return <AppShell><Spinner /></AppShell>;

  if (data.state === "locked")
    return (
      <AppShell>
        <Card className="mx-auto max-w-xl p-8 text-center">
          <Lock className="mx-auto mb-3 text-muted-foreground" />
          <h1 className="font-serif text-2xl font-semibold">{data.title}</h1>
          <p className="mt-2 text-muted-foreground">{data.locked_reason}</p>
          <Link href="/roadmap" className="mt-4 inline-block text-primary hover:underline">View the roadmap</Link>
        </Card>
      </AppShell>
    );

  if (data.preparing || !content)
    return (
      <AppShell>
        <Card className="mx-auto max-w-xl p-8 text-center">
          <Spinner className="mx-auto mb-3 text-primary" />
          <h1 className="font-serif text-2xl font-semibold">{data.title}</h1>
          <p className="mt-2 text-muted-foreground">This lesson is being prepared for you — generated from the curriculum, your mastery profile, then validated and reviewed. You&apos;ll also get an email when it&apos;s ready.</p>
        </Card>
      </AppShell>
    );

  const required = content.completion.required_section_ids;
  const requiredQs = content.completion.required_question_ids.map((q) => questions.get(q)!).filter(Boolean);
  const sectionsDone = required.filter((s) => completed.has(s)).length;
  const answeredCount = requiredQs.filter((q) => isAnswered(q, answers[q.id])).length;
  const totalMinutes = content.sections.reduce((s, x) => s + x.estimated_minutes, 0);
  const ready = sectionsDone === required.length && answeredCount === requiredQs.length;
  const lastSub = data.submissions?.[0];

  return (
    <AppShell wide>
      <div className="grid gap-10 lg:grid-cols-[240px_minmax(0,1fr)]">
        {/* ---- sidebar: outline */}
        <aside className="hidden lg:block">
          <div className="sticky top-24 space-y-5 text-sm">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{data.block.title}</p>
              <p className="text-muted-foreground">{data.module.title}</p>
            </div>
            <ol className="space-y-1">
              {content.sections.map((s) => (
                <li key={s.id}>
                  <a href={`#sec-${s.id}`} className="flex items-center gap-2 rounded-md px-2 py-1 hover:bg-muted">
                    {completed.has(s.id) ? <CheckCircle2 size={15} className="text-success" /> : <Circle size={15} className="text-muted-foreground" />}
                    <span className="flex-1 truncate">{s.title}</span>
                    <span className="text-xs text-muted-foreground">{s.estimated_minutes}m</span>
                  </a>
                </li>
              ))}
            </ol>
            <div className="space-y-2 border-t border-border pt-4">
              <div className="flex justify-between text-xs text-muted-foreground"><span>Sections</span><span>{sectionsDone}/{required.length}</span></div>
              <Progress value={sectionsDone / Math.max(1, required.length)} />
              <div className="flex justify-between text-xs text-muted-foreground"><span>Required answers</span><span>{answeredCount}/{requiredQs.length}</span></div>
              <Progress value={answeredCount / Math.max(1, requiredQs.length)} />
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => setTutorOpen(true)}><Bot size={14} /> Tutor</Button>
              <Button variant="outline" size="sm" onClick={() => setNotesOpen(true)}><NotebookPen size={14} /> Notes</Button>
            </div>
          </div>
        </aside>

        {/* ---- main column */}
        <article className="min-w-0 max-w-3xl">
          <header className="mb-8">
            <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
              <Badge>{data.kind === "lesson" ? "Lesson" : data.kind === "module_assessment" ? "Module assessment" : "Block exam"}</Badge>
              <Badge tone={data.state === "passed" ? "success" : data.state === "remediation_required" ? "warning" : "primary"}>{data.state.replace("_", " ")}</Badge>
              <span className="inline-flex items-center gap-1 text-muted-foreground"><Clock size={12} /> ~{totalMinutes} min</span>
              {data.source === "generated" && <Badge tone="neutral">AI-generated · validated</Badge>}
            </div>
            <h1 className="font-serif text-4xl font-semibold leading-tight tracking-tight">{content.title}</h1>
            {content.subtitle && <p className="mt-2 font-serif text-xl text-muted-foreground">{content.subtitle}</p>}
          </header>

          {remediationActive && (
            <Card className="mb-8 border-warning/40 bg-warning-soft/40 p-5">
              <p className="flex items-center gap-2 font-semibold"><RotateCcw size={16} /> Targeted review</p>
              <Markdown compact className="mt-2">{content.summary}</Markdown>
              {!!data.remediation?.prerequisites?.length && <p className="mt-2 text-sm text-muted-foreground">Includes a refresher on prerequisites: {data.remediation.prerequisites.join(", ")}.</p>}
              <button className="mt-2 text-sm text-primary hover:underline" onClick={() => setShowOriginal(true)}>Re-read the original lesson</button>
            </Card>
          )}
          {data.remediation?.content && showOriginal && (
            <Card className="mb-8 p-4 text-sm">
              Reading the original lesson. <button className="text-primary hover:underline" onClick={() => setShowOriginal(false)}>Back to the targeted review</button> to submit.
            </Card>
          )}
          {data.remediation?.preparing && (
            <Card className="mb-8 flex items-center gap-3 p-5 text-sm"><Spinner /> Preparing a targeted review based on your answers…</Card>
          )}
          {(data.state === "submitted" || data.state === "grading") && lastSub && (
            <Card className="mb-8 flex items-center gap-3 p-5 text-sm">
              <Spinner /> Your work is being graded. <Link className="text-primary hover:underline" href={`/submissions/${lastSub.submission_id}`}>Open the submission</Link>
            </Card>
          )}
          {data.state === "passed" && (
            <Card className="mb-8 flex flex-wrap items-center gap-3 border-success/40 bg-success-soft/50 p-5">
              <Check className="text-success" />
              <span className="font-medium">Passed{data.best_score !== null ? ` · best score ${pct(data.best_score)}` : ""}.</span>
              <Link href="/" className="ml-auto inline-flex items-center gap-1 text-sm text-primary hover:underline">Next lesson <ArrowRight size={14} /></Link>
            </Card>
          )}

          {!remediationActive && (
            <section className="mb-10 space-y-4">
              <Markdown>{content.why_it_matters}</Markdown>
              <Card className="p-5">
                <p className="mb-2 flex items-center gap-2 text-sm font-semibold"><Target size={15} /> By the end you should be able to</p>
                <ul className="space-y-1.5 text-sm">
                  {content.objectives.map((o) => (
                    <li key={o.id} className="flex gap-2">
                      <span className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", o.critical ? "bg-warning" : "bg-muted-foreground")} />
                      <span>{o.statement} {o.critical && <span className="text-xs text-warning">(critical)</span>}</span>
                    </li>
                  ))}
                </ul>
                {content.connections.length > 0 && (
                  <div className="mt-3 border-t border-border pt-3 text-sm text-muted-foreground">
                    {content.connections.map((c, i) => (
                      <p key={i}><span className="font-medium text-foreground">{c.direction === "builds_on" ? "Builds on" : "Leads to"}:</span> {c.note}</p>
                    ))}
                  </div>
                )}
              </Card>
            </section>
          )}

          {content.sections.map((s) => (
            <section key={s.id} id={`sec-${s.id}`} className="mb-14 scroll-mt-24">
              <div className="mb-4 flex items-baseline gap-3 border-b border-border pb-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-primary">{SECTION_LABEL[s.kind] ?? s.kind}</span>
                <h2 className="font-serif text-2xl font-semibold">{s.title}</h2>
                <span className="ml-auto text-xs text-muted-foreground">{s.estimated_minutes} min</span>
              </div>
              {s.blocks.map((b, i) => (
                <BlockView key={i} block={b} questions={questions} resources={resources} answers={answers} setAnswer={setAnswer} numbering={numbering} />
              ))}
              {canAnswer && s.required && (
                <div className="mt-6 flex justify-end">
                  {completed.has(s.id) ? (
                    <span className="inline-flex items-center gap-1.5 text-sm text-success"><CheckCircle2 size={16} /> Section complete</span>
                  ) : (
                    <Button variant="outline" size="sm" onClick={() => markComplete(s.id)}>Mark section complete</Button>
                  )}
                </div>
              )}
            </section>
          ))}

          {!remediationActive && (content.resources.length > 0 || content.homework.length > 0) && (
            <section className="mb-14">
              <h2 className="mb-3 font-serif text-2xl font-semibold">Further study</h2>
              {content.resources.map((r) => <ResourceCard key={r.id} r={r} />)}
              {content.homework.length > 0 && (
                <Card className="p-5">
                  <p className="mb-2 text-sm font-semibold">Optional practice (ungraded)</p>
                  <ol className="list-decimal space-y-2 pl-5">{content.homework.map((h, i) => <li key={i}><Markdown compact className="prose-p:my-0">{h}</Markdown></li>)}</ol>
                </Card>
              )}
            </section>
          )}

          {canAnswer && (
            <Card className="sticky bottom-4 z-20 flex flex-wrap items-center gap-4 p-4 shadow-lg">
              <div className="text-sm">
                <p className="font-medium">{ready ? "Ready to submit" : "Finish the lesson to submit"}</p>
                <p className="text-muted-foreground">Sections {sectionsDone}/{required.length} · answers {answeredCount}/{requiredQs.length} · pass mark {pct(data.assessment?.threshold)} and every critical objective</p>
                {submitError && <p className="text-danger">{submitError}</p>}
              </div>
              <div className="ml-auto flex gap-2">
                {data.test_out_eligible && !remediationActive && (
                  <Button variant="outline" disabled={submitting || answeredCount < requiredQs.length} onClick={() => submit(true)} title="Your diagnostic showed prior knowledge: you may skip the instruction, but you still have to pass the assessment.">
                    Test out
                  </Button>
                )}
                <Button disabled={!ready || submitting} onClick={() => submit(false)}>
                  {submitting && <Spinner />} Submit for grading
                </Button>
              </div>
            </Card>
          )}

          {!!data.submissions?.length && (
            <section className="mt-10 text-sm">
              <h3 className="mb-2 font-semibold">Attempts</h3>
              <ul className="divide-y divide-border rounded-lg border border-border">
                {data.submissions.map((s) => (
                  <li key={s.submission_id}>
                    <Link href={`/submissions/${s.submission_id}`} className="flex items-center gap-3 px-4 py-2 hover:bg-muted">
                      <span>Attempt {s.attempt}</span>
                      <span className="text-muted-foreground">{new Date(s.submitted_at).toLocaleString()}</span>
                      <span className="ml-auto">{s.score !== null ? pct(s.score) : s.status}</span>
                      {s.passed !== null && <Badge tone={s.passed ? "success" : "danger"}>{s.passed ? "passed" : "not passed"}</Badge>}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </article>
      </div>

      <div className="fixed bottom-4 right-4 z-30 flex gap-2 lg:hidden">
        <Button size="icon" variant="outline" onClick={() => setNotesOpen(true)} aria-label="Notes"><NotebookPen size={16} /></Button>
        <Button size="icon" onClick={() => setTutorOpen(true)} aria-label="Tutor"><Bot size={16} /></Button>
      </div>
      <TutorPanel lessonId={id} open={tutorOpen} onClose={() => setTutorOpen(false)} disabledReason={data.tutor?.available === false ? data.tutor.reason : undefined} />
      <NotesPanel lessonId={id} initial={data.note ?? ""} open={notesOpen} onClose={() => setNotesOpen(false)} />
    </AppShell>
  );
}
