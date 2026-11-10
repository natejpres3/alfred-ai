"use client";

import { RotateCcw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";

import { AppShell, PageTitle } from "@/components/app-shell";
import { Badge, Button, Card, CardBody, CardHeader, CardTitle, Spinner } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";

type R = { pending_assessment_id: string | null; due: { key: string; name: string; state: string }[]; upcoming: { key: string; name: string; next_review_at: string; stability_days: number; state: string }[] };

export default function ReviewsPage() {
  const router = useRouter();
  const { data } = useSWR<R>("/api/reviews");
  const [msg, setMsg] = useState<string | null>(null);
  if (!data) return <AppShell><Spinner /></AppShell>;

  async function start() {
    try {
      const { assessment_id } = await api<{ assessment_id: string }>("/api/reviews/start", { method: "POST" });
      router.push(`/assessments/${assessment_id}`);
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : "Could not start a review");
    }
  }

  return (
    <AppShell>
      <PageTitle eyebrow="Spaced repetition" title="Reviews">
        Mastered concepts come back at growing intervals as short retrieval checks — a few minutes, never a full lesson. Doing well stretches the interval; struggling shortens it.
      </PageTitle>
      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Due now</CardTitle></CardHeader>
          <CardBody className="space-y-3">
            {data.due.length || data.pending_assessment_id ? (
              <>
                <div className="flex flex-wrap gap-1.5">{data.due.map((c) => <Badge key={c.key} tone={c.state === "at_risk" ? "danger" : "warning"}>{c.name}</Badge>)}</div>
                <Button onClick={data.pending_assessment_id ? () => router.push(`/assessments/${data.pending_assessment_id}`) : start}><RotateCcw size={15} /> Start review</Button>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Nothing due. Nice.</p>
            )}
            {msg && <p className="text-sm text-muted-foreground">{msg}</p>}
          </CardBody>
        </Card>
        <Card>
          <CardHeader><CardTitle>Schedule</CardTitle></CardHeader>
          <CardBody>
            {data.upcoming.length === 0 ? (
              <p className="text-sm text-muted-foreground">Concepts are scheduled after you master them.</p>
            ) : (
              <ul className="divide-y divide-border text-sm">
                {data.upcoming.map((c) => (
                  <li key={c.key} className="flex items-center gap-3 py-2">
                    <span className="flex-1">{c.name}</span>
                    <span className="text-muted-foreground">{new Date(c.next_review_at).toLocaleDateString()}</span>
                    <span className="w-24 text-right font-mono text-xs text-muted-foreground">stability {c.stability_days}d</span>
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
