"use client";

import { Check, CheckCircle2, Github, Upload, X } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import useSWR from "swr";

import { AppShell, PageTitle } from "@/components/app-shell";
import { CodeEditor } from "@/components/lesson/code-editor";
import { Markdown } from "@/components/markdown";
import { Badge, Button, Card, Input, Progress, Spinner } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { cn, pct, safeStorage } from "@/lib/utils";

type Sub = { id: string; version: number; status: string; score: number | null; passed: boolean | null; feedback: string; source: string; created_at: string; public_tests: { name: string; status: string; message: string }[]; hidden: { passed: number; total: number } | null; stdout: string; code: string };
type Milestone = { id: string; key: string; title: string; description: string; starter_code: string; required_functions: string[]; public_tests: { name: string; code: string }[]; hidden_test_count: number; best_score: number | null; passed: boolean; submissions: Sub[] };
type Project = { key: string; title: string; summary: string; pass_threshold: number; passed: boolean; score: number; milestones: Milestone[] };

function MilestonePanel({ m, project, onSubmitted }: { m: Milestone; project: Project; onSubmitted: () => void }) {
  const draftKey = `project:${project.key}:code`;
  const [code, setCode] = useState<string>("");
  const [source, setSource] = useState<"editor" | "github" | "upload">("editor");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    // one file accumulates across milestones: start from the latest submission or the draft, then append new starter code
    const prev = m.submissions[0]?.code || safeStorage.get<string>(draftKey, "");
    setCode(prev && prev.includes(m.required_functions.at(-1) ?? "") ? prev : (prev ? prev + "\n\n" : "") + m.starter_code);
  }, [m.key]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      await api(`/api/projects/milestones/${m.id}/submissions`, { method: "POST", json: source === "github" ? { source, repo_url: url } : { source, code } });
      onSubmitted();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Submission failed");
    } finally {
      setBusy(false);
    }
  }

  const latest = m.submissions[0];
  const pending = latest && latest.status !== "graded";
  return (
    <div className="space-y-4">
      <Markdown>{m.description}</Markdown>
      <div className="flex flex-wrap gap-2 text-sm">
        {(["editor", "upload", "github"] as const).map((s) => (
          <button key={s} onClick={() => setSource(s)} className={cn("inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5", source === s ? "border-primary bg-accent text-primary" : "border-border")}>
            {s === "github" ? <Github size={14} /> : s === "upload" ? <Upload size={14} /> : null} {s === "editor" ? "Editor" : s === "upload" ? "Upload .py" : "GitHub file"}
          </button>
        ))}
      </div>
      {source === "github" ? (
        <Input placeholder="https://github.com/you/repo/blob/main/linreg.py" value={url} onChange={(e) => setUrl(e.target.value)} />
      ) : (
        <>
          {source === "upload" && (
            <input type="file" accept=".py,text/x-python" onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f) setCode(await f.text());
            }} className="text-sm" />
          )}
          <CodeEditor value={code} onChange={(v) => { setCode(v); safeStorage.set(draftKey, v); }} height={460} />
        </>
      )}
      <div className="flex items-center gap-3">
        <Button onClick={submit} disabled={busy || !!pending}>{(busy || pending) && <Spinner />} {pending ? "Grading…" : "Submit milestone"}</Button>
        <span className="text-xs text-muted-foreground">{m.public_tests.length} public + {m.hidden_test_count} hidden tests · sandboxed · no network</span>
        {err && <span className="text-sm text-danger">{err}</span>}
      </div>
      {m.submissions.filter((s) => s.status === "graded").slice(0, 3).map((s) => (
        <Card key={s.id} className="p-4 text-sm">
          <div className="mb-2 flex items-center gap-2">
            <span className="font-medium">Version {s.version}</span>
            <span className="text-muted-foreground">{new Date(s.created_at).toLocaleString()}</span>
            <span className="ml-auto font-mono">{pct(s.score)}</span>
            <Badge tone={s.passed ? "success" : "danger"}>{s.passed ? "meets bar" : "below bar"}</Badge>
          </div>
          <ul className="mb-2 space-y-0.5">
            {s.public_tests.map((t) => (
              <li key={t.name} className="flex gap-2 font-mono text-xs">{t.status === "passed" ? <Check size={13} className="text-success" /> : <X size={13} className="text-danger" />}{t.name} {t.status !== "passed" && <span className="text-danger">{t.message}</span>}</li>
            ))}
          </ul>
          <Markdown compact>{s.feedback}</Markdown>
        </Card>
      ))}
    </div>
  );
}

export default function ProjectPage() {
  const { key } = useParams<{ key: string }>();
  const { data, mutate } = useSWR<Project>(`/api/projects/${key}`, {
    refreshInterval: (d) => (d?.milestones.some((m) => m.submissions[0] && m.submissions[0].status !== "graded") ? 2500 : 0),
  });
  const [active, setActive] = useState(0);
  if (!data) return <AppShell><Spinner /></AppShell>;
  const m = data.milestones[active];
  return (
    <AppShell wide>
      <PageTitle eyebrow={`Module project · pass bar ${pct(data.pass_threshold)} on every milestone`} title={data.title}>
        <Markdown compact>{data.summary}</Markdown>
      </PageTitle>
      <div className="grid gap-8 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="space-y-2">
          {data.milestones.map((ms, i) => (
            <button key={ms.id} onClick={() => setActive(i)} className={cn("w-full rounded-md border px-3 py-2 text-left text-sm", i === active ? "border-primary bg-accent" : "border-border hover:bg-muted")}>
              <div className="flex items-center gap-2">
                {ms.passed ? <CheckCircle2 size={15} className="text-success" /> : <span className="font-mono text-xs text-muted-foreground">{i + 1}</span>}
                <span className="flex-1">{ms.title}</span>
              </div>
              <Progress className="mt-2" value={ms.best_score ?? 0} tone={ms.passed ? "success" : "primary"} />
            </button>
          ))}
          <Card className="p-3 text-sm">
            Project score <span className="font-mono">{pct(data.score)}</span>{" "}
            {data.passed ? <Badge tone="success">gate passed</Badge> : <Badge tone="warning">gate closed</Badge>}
          </Card>
        </aside>
        <MilestonePanel key={m.id} m={m} project={data} onSubmitted={() => mutate()} />
      </div>
    </AppShell>
  );
}
