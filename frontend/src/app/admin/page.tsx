"use client";

import { useState } from "react";
import useSWR from "swr";

import { AppShell, PageTitle } from "@/components/app-shell";
import { Badge, Button, Card, CardBody, CardHeader, CardTitle, Spinner, Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { pct } from "@/lib/utils";

type Queue = { flagged: { grade_id: string; submission_id: string; assessment: string; score: number; flagged: { question_key: string; score: number; max: number }[] }[]; errored_submissions: { id: string }[] };
type Costs = { budget_usd: number; spent_usd: number; errors: number; by_role: { role: string; model: string; calls: number; input_tokens: number; output_tokens: number; cost_usd: number }[] };
type Job = { id: string; kind: string; status: string; attempts: number; last_error: string | null; run_at: string };

function Override({ gradeId, done }: { gradeId: string; done: () => void }) {
  const [note, setNote] = useState("");
  async function decide(passed: boolean) {
    await api(`/api/admin/grades/${gradeId}/override`, { method: "POST", json: { passed, note } });
    done();
  }
  return (
    <div className="mt-2 space-y-2">
      <Textarea rows={2} placeholder="Reason (required, kept in the audit log)" value={note} onChange={(e) => setNote(e.target.value)} />
      <div className="flex gap-2">
        <Button size="sm" disabled={note.length < 3} onClick={() => decide(true)}>Pass</Button>
        <Button size="sm" variant="outline" disabled={note.length < 3} onClick={() => decide(false)}>Fail → remediation</Button>
      </div>
    </div>
  );
}

export default function AdminPage() {
  const { data: q, mutate: mq } = useSWR<Queue>("/api/admin/review-queue");
  const { data: c } = useSWR<Costs>("/api/admin/costs");
  const { data: jobs, mutate: mj } = useSWR<Job[]>("/api/admin/jobs");
  if (!q || !c || !jobs) return <AppShell><Spinner /></AppShell>;
  return (
    <AppShell>
      <PageTitle eyebrow="Admin" title="Grading review, jobs and AI cost" />
      <div className="grid gap-6">
        <Card>
          <CardHeader><CardTitle>Manual review queue ({q.flagged.length})</CardTitle></CardHeader>
          <CardBody className="space-y-4 text-sm">
            {q.flagged.length === 0 && <p className="text-muted-foreground">No grades waiting for review.</p>}
            {q.flagged.map((f) => (
              <div key={f.grade_id} className="rounded-md border border-border p-3">
                <div className="flex items-center gap-2"><span className="font-medium">{f.assessment}</span><span className="font-mono">{pct(f.score)}</span>
                  <a className="ml-auto text-primary" href={`/submissions/${f.submission_id}`} target="_blank">Open submission</a></div>
                <p className="text-muted-foreground">Graders disagreed on: {f.flagged.map((x) => x.question_key).join(", ")}</p>
                <Override gradeId={f.grade_id} done={() => mq()} />
              </div>
            ))}
          </CardBody>
        </Card>
        <Card>
          <CardHeader><CardTitle>AI spend this month</CardTitle></CardHeader>
          <CardBody className="text-sm">
            <p className="mb-3"><span className="font-mono text-lg">${c.spent_usd.toFixed(2)}</span> of ${c.budget_usd.toFixed(2)} budget · {c.errors} failed calls</p>
            <table className="w-full text-left">
              <thead className="text-xs text-muted-foreground"><tr><th className="py-1">Role</th><th>Model</th><th className="text-right">Calls</th><th className="text-right">In tok</th><th className="text-right">Out tok</th><th className="text-right">Cost</th></tr></thead>
              <tbody className="divide-y divide-border font-mono text-xs">
                {c.by_role.map((r) => (
                  <tr key={r.role + r.model}><td className="py-1.5">{r.role}</td><td>{r.model}</td><td className="text-right">{r.calls}</td><td className="text-right">{r.input_tokens.toLocaleString()}</td><td className="text-right">{r.output_tokens.toLocaleString()}</td><td className="text-right">${r.cost_usd.toFixed(3)}</td></tr>
                ))}
              </tbody>
            </table>
          </CardBody>
        </Card>
        <Card>
          <CardHeader><CardTitle>Background jobs</CardTitle></CardHeader>
          <CardBody>
            <ul className="divide-y divide-border text-sm">
              {jobs.slice(0, 40).map((j) => (
                <li key={j.id} className="flex items-center gap-3 py-1.5">
                  <span className="w-40 font-mono text-xs">{j.kind}</span>
                  <Badge tone={j.status === "succeeded" ? "success" : j.status === "dead" ? "danger" : j.status === "queued" ? "primary" : "warning"}>{j.status}</Badge>
                  <span className="text-xs text-muted-foreground">attempts {j.attempts}</span>
                  <span className="flex-1 truncate text-xs text-danger" title={j.last_error ?? ""}>{j.last_error}</span>
                  {(j.status === "dead" || j.status === "failed") && <Button size="sm" variant="outline" onClick={async () => { await api(`/api/admin/jobs/${j.id}/retry`, { method: "POST" }); mj(); }}>Retry</Button>}
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      </div>
    </AppShell>
  );
}
