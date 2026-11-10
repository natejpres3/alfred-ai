"use client";

import { ArrowRight, Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import useSWR from "swr";

import { AppShell } from "@/components/app-shell";
import { Badge, Button, Card, Input, Label, Spinner, Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type Overview = {
  program: { title: string; blocks: { key: string; title: string; status: string; topics: string[] }[] };
  profile: { completed: boolean; diagnostic: { priors?: Record<string, number>; test_out?: string[]; score?: number } };
  diagnostic_assessment_id: string | null;
};

const AREAS = [
  { key: "math", label: "Mathematics", hint: "Linear algebra, calculus, probability" },
  { key: "programming", label: "Programming", hint: "Python, data structures, tooling" },
  { key: "ml", label: "Machine learning", hint: "Regression, classifiers, evaluation" },
  { key: "ai", label: "AI / deep learning", hint: "Neural nets, transformers, LLMs" },
] as const;
const LEVELS = ["None", "Some exposure", "Comfortable", "Strong", "Expert"];

export default function OnboardingPage() {
  const router = useRouter();
  const { data } = useSWR<Overview>("/api/onboarding");
  const [step, setStep] = useState(0);
  const [bg, setBg] = useState({ math: 1, programming: 2, ml: 0, ai: 0, notes: "" });
  const [goals, setGoals] = useState("");
  const [minutes, setMinutes] = useState(60);
  const [tz, setTz] = useState("UTC");
  const [delivery, setDelivery] = useState<"immediate" | "scheduled">("immediate");
  const [hour, setHour] = useState(7);
  const [busy, setBusy] = useState(false);
  useEffect(() => setTz(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"), []);
  useEffect(() => {
    if (data?.profile.diagnostic?.score !== undefined) setStep(3);
  }, [data]);

  async function saveProfile() {
    await api("/api/onboarding/profile", { method: "POST", json: { background: bg, goals, daily_goal_minutes: minutes, timezone: tz, delivery_mode: delivery, delivery_hour: hour, email_enabled: true } });
  }
  async function startDiagnostic() {
    setBusy(true);
    await saveProfile();
    const { assessment_id } = await api<{ assessment_id: string }>("/api/onboarding/diagnostic", { method: "POST" });
    router.push(`/assessments/${assessment_id}?return=/onboarding`);
  }
  async function finish() {
    setBusy(true);
    await saveProfile();
    await api("/api/onboarding/complete", { method: "POST" });
    router.push("/");
  }

  if (!data) return <AppShell requireOnboarded={false}><Spinner /></AppShell>;
  const steps = ["The program", "Your background", "Schedule", "Diagnostic"];

  return (
    <AppShell requireOnboarded={false}>
      <div className="mx-auto max-w-3xl">
        <ol className="mb-8 flex flex-wrap gap-2 text-sm">
          {steps.map((s, i) => (
            <li key={s} className={cn("flex items-center gap-2 rounded-full px-3 py-1", i === step ? "bg-primary text-primary-foreground" : i < step ? "bg-success-soft text-success" : "bg-muted text-muted-foreground")}>
              {i < step ? <Check size={13} /> : <span className="font-mono text-xs">{i + 1}</span>} {s}
            </li>
          ))}
        </ol>

        {step === 0 && (
          <section>
            <h1 className="font-serif text-3xl font-semibold">{data.program.title}</h1>
            <div className="mt-4 space-y-3 text-muted-foreground">
              <p>This program teaches AI the way a rigorous university sequence would — but you advance when you <em>demonstrate</em> understanding, not when time passes.</p>
              <p>Each day (~1 hour) you get a lesson: retrieval warm-up, concept, mathematics, an interactive demo, active recall, a coding exercise, and a summary. Explanations you write are graded against explicit rubrics; code runs against hidden tests in a sandbox. Miss the bar on a critical idea and you get a targeted review with new questions — not the same quiz again.</p>
            </div>
            <div className="mt-6 grid gap-2 sm:grid-cols-2">
              {data.program.blocks.map((b, i) => (
                <Card key={b.key} className="p-3 text-sm">
                  <span className="mr-2 font-mono text-muted-foreground">{String(i + 1).padStart(2, "0")}</span>
                  {b.title}
                  {b.status === "authored" && <Badge tone="primary" className="ml-2">start here</Badge>}
                </Card>
              ))}
            </div>
            <Button className="mt-8" size="lg" onClick={() => setStep(1)}>Continue <ArrowRight size={16} /></Button>
          </section>
        )}

        {step === 1 && (
          <section className="space-y-6">
            <h1 className="font-serif text-3xl font-semibold">Where are you starting from?</h1>
            {AREAS.map((a) => (
              <div key={a.key}>
                <p className="font-medium">{a.label} <span className="text-sm font-normal text-muted-foreground">— {a.hint}</span></p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {LEVELS.map((l, i) => (
                    <button key={l} onClick={() => setBg({ ...bg, [a.key]: i })} className={cn("rounded-md border px-3 py-1.5 text-sm", bg[a.key] === i ? "border-primary bg-accent text-primary" : "border-border hover:bg-muted")}>
                      {l}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            <div className="space-y-1.5">
              <Label htmlFor="notes">Anything else? (courses taken, languages, what you build)</Label>
              <Textarea id="notes" rows={3} value={bg.notes} onChange={(e) => setBg({ ...bg, notes: e.target.value })} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="goals">What do you want to be able to do in 12–24 months?</Label>
              <Textarea id="goals" rows={3} value={goals} onChange={(e) => setGoals(e.target.value)} placeholder="e.g. read and reproduce LLM papers; optimize inference on GPUs; design production AI systems" />
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setStep(0)}>Back</Button>
              <Button onClick={() => setStep(2)}>Continue <ArrowRight size={16} /></Button>
            </div>
          </section>
        )}

        {step === 2 && (
          <section className="space-y-6">
            <h1 className="font-serif text-3xl font-semibold">Your schedule</h1>
            <div className="space-y-1.5">
              <Label htmlFor="minutes">Daily goal: {minutes} minutes</Label>
              <input id="minutes" type="range" min={15} max={180} step={15} value={minutes} onChange={(e) => setMinutes(parseInt(e.target.value))} className="w-full" />
              <p className="text-sm text-muted-foreground">Lessons are sized to this budget. It&apos;s a recommendation, not a limit: when you pass, the next lesson unlocks immediately.</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tz">Timezone</Label>
              <Input id="tz" value={tz} onChange={(e) => setTz(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>New-lesson emails</Label>
              <label className="flex items-center gap-2 text-sm"><input type="radio" checked={delivery === "immediate"} onChange={() => setDelivery("immediate")} /> As soon as the next lesson is ready</label>
              <label className="flex items-center gap-2 text-sm">
                <input type="radio" checked={delivery === "scheduled"} onChange={() => setDelivery("scheduled")} /> Batched daily at
                <select className="rounded-md border border-border bg-card px-2 py-1" value={hour} onChange={(e) => setHour(parseInt(e.target.value))} disabled={delivery !== "scheduled"}>
                  {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
                </select>
              </label>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setStep(1)}>Back</Button>
              <Button onClick={() => setStep(3)}>Continue <ArrowRight size={16} /></Button>
            </div>
          </section>
        )}

        {step === 3 && (
          <section className="space-y-6">
            <h1 className="font-serif text-3xl font-semibold">Optional diagnostic</h1>
            {data.profile.diagnostic?.score !== undefined ? (
              <Card className="p-5 text-sm">
                <p className="font-medium">Diagnostic complete.</p>
                <p className="mt-1 text-muted-foreground">
                  {data.profile.diagnostic.test_out?.length
                    ? `You can test out of ${data.profile.diagnostic.test_out.length} lesson(s): skip the instruction, but you still have to pass the real assessment.`
                    : "Your results set starting estimates for your mastery profile. You'll start from the first lesson."}
                </p>
              </Card>
            ) : (
              <p className="text-muted-foreground">
                Fifteen short questions across Block 1 (about 15 minutes). Results set starting estimates and may let you <em>test out</em> of lessons you already know — you&apos;d still pass each lesson&apos;s real assessment. Skip it if you&apos;d rather start from the beginning.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => setStep(2)}>Back</Button>
              {data.profile.diagnostic?.score === undefined && (
                <Button variant="outline" onClick={startDiagnostic} disabled={busy}>Take the diagnostic</Button>
              )}
              <Button onClick={finish} disabled={busy}>{busy && <Spinner />} Start learning <ArrowRight size={16} /></Button>
            </div>
          </section>
        )}
      </div>
    </AppShell>
  );
}
