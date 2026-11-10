"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";

import { AppShell, PageTitle } from "@/components/app-shell";
import { Button, Card, CardBody, CardHeader, CardTitle, Input, Label, Spinner } from "@/components/ui/primitives";
import { api } from "@/lib/api";

type S = { timezone: string; daily_goal_minutes: number; delivery_mode: string; delivery_hour: number; email_enabled: boolean; notify: Record<string, boolean>; display_name: string; email: string };
const LABELS: Record<string, string> = {
  lesson_available: "A new lesson is ready",
  submission_graded: "A submission is graded",
  lesson_passed: "A lesson is passed",
  remediation_required: "A targeted review is ready",
  module_completed: "A module is completed",
  section_unlocked: "A new module unlocks",
  project_graded: "A project milestone is graded",
  review_due: "A spaced review is due",
};

export default function SettingsPage() {
  const { data, mutate } = useSWR<S>("/api/settings");
  const [s, setS] = useState<S | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => setS(data ?? null), [data]);
  if (!s) return <AppShell><Spinner /></AppShell>;
  async function save() {
    await api("/api/settings", { method: "PUT", json: s });
    setSaved(true);
    mutate();
    setTimeout(() => setSaved(false), 2000);
  }
  return (
    <AppShell>
      <PageTitle title="Settings" />
      <div className="grid max-w-3xl gap-6">
        <Card>
          <CardHeader><CardTitle>Profile & schedule</CardTitle></CardHeader>
          <CardBody className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5"><Label>Name</Label><Input value={s.display_name} onChange={(e) => setS({ ...s, display_name: e.target.value })} /></div>
            <div className="space-y-1.5"><Label>Email</Label><Input value={s.email} disabled /></div>
            <div className="space-y-1.5"><Label>Timezone</Label><Input value={s.timezone} onChange={(e) => setS({ ...s, timezone: e.target.value })} /></div>
            <div className="space-y-1.5"><Label>Daily goal (minutes)</Label><Input type="number" min={15} max={240} value={s.daily_goal_minutes} onChange={(e) => setS({ ...s, daily_goal_minutes: parseInt(e.target.value || "60") })} /></div>
          </CardBody>
        </Card>
        <Card>
          <CardHeader><CardTitle>Email</CardTitle></CardHeader>
          <CardBody className="space-y-3 text-sm">
            <label className="flex items-center gap-2"><input type="checkbox" checked={s.email_enabled} onChange={(e) => setS({ ...s, email_enabled: e.target.checked })} /> Send me emails</label>
            <div className="flex flex-wrap items-center gap-2">
              <span>New-lesson and review emails:</span>
              <select className="rounded-md border border-border bg-card px-2 py-1" value={s.delivery_mode} onChange={(e) => setS({ ...s, delivery_mode: e.target.value })}>
                <option value="immediate">immediately</option>
                <option value="scheduled">daily at</option>
              </select>
              {s.delivery_mode === "scheduled" && (
                <select className="rounded-md border border-border bg-card px-2 py-1" value={s.delivery_hour} onChange={(e) => setS({ ...s, delivery_hour: parseInt(e.target.value) })}>
                  {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
                </select>
              )}
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {Object.entries(LABELS).map(([k, label]) => (
                <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={s.notify[k] ?? true} disabled={!s.email_enabled} onChange={(e) => setS({ ...s, notify: { ...s.notify, [k]: e.target.checked } })} /> {label}</label>
              ))}
            </div>
          </CardBody>
        </Card>
        <div className="flex items-center gap-3"><Button onClick={save}>Save settings</Button>{saved && <span className="text-sm text-success">Saved</span>}</div>
      </div>
    </AppShell>
  );
}
