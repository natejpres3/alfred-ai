"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import useSWR from "swr";

import { AppShell, PageTitle } from "@/components/app-shell";
import { isAnswered, QuestionCard } from "@/components/lesson/question-input";
import { Button, Card, Spinner } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Answer, TQuestion } from "@/lib/lesson-schema";
import { newKey, safeStorage } from "@/lib/utils";

type A = { id: string; kind: string; title: string; threshold: number; questions: TQuestion[]; submissions: { id: string }[] };

function AssessmentInner() {
  const { id } = useParams<{ id: string }>();
  const back = useSearchParams().get("return");
  const router = useRouter();
  const { data } = useSWR<A>(`/api/assessments/${id}`);
  const [answers, setAnswers] = useState<Record<string, Answer>>(() => safeStorage.get(`draft:${id}`, {}));
  const [key] = useState(newKey);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!data) return <Spinner />;
  if (data.submissions.length)
    return <Card className="p-6">Already submitted. <a className="text-primary" href={`/submissions/${data.submissions[0].id}`}>See the results</a>.</Card>;

  async function submit() {
    setBusy(true);
    try {
      const r = await api<{ submission_id: string }>(`/api/assessments/${id}/submissions`, { method: "POST", json: { answers, idempotency_key: key } });
      safeStorage.remove(`draft:${id}`);
      if (data!.kind === "diagnostic") {
        await new Promise((res) => setTimeout(res, 1500));
        router.push(back || "/onboarding");
      } else router.push(`/submissions/${r.submission_id}`);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Submission failed");
      setBusy(false);
    }
  }

  const answered = data.questions.filter((q) => isAnswered(q, answers[q.id])).length;
  return (
    <>
      <PageTitle eyebrow={data.kind === "diagnostic" ? "Diagnostic" : data.kind === "review" ? "Spaced review" : "Assessment"} title={data.title}>
        {data.kind === "diagnostic" ? "Answer what you can; skip what you don't know. This only sets starting estimates." : "A short retrieval check. No notes — the point is to practice recalling."}
      </PageTitle>
      <div className="max-w-3xl">
        {data.questions.map((q, i) => (
          <QuestionCard key={q.id} q={q} index={i + 1} answer={answers[q.id]} onChange={(a) => {
            const next = { ...answers, [q.id]: a };
            setAnswers(next);
            safeStorage.set(`draft:${id}`, next);
          }} />
        ))}
        <Card className="sticky bottom-4 flex items-center gap-4 p-4 shadow-lg">
          <span className="text-sm text-muted-foreground">{answered}/{data.questions.length} answered</span>
          {err && <span className="text-sm text-danger">{err}</span>}
          <Button className="ml-auto" disabled={busy || (data.kind !== "diagnostic" && answered < data.questions.length)} onClick={submit}>
            {busy && <Spinner />} Submit
          </Button>
        </Card>
      </div>
    </>
  );
}

export default function AssessmentPage() {
  return (
    <AppShell requireOnboarded={false}>
      <Suspense>
        <AssessmentInner />
      </Suspense>
    </AppShell>
  );
}
