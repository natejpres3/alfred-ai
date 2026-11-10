"use client";

import { Bot, Send, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";

import { Markdown } from "@/components/markdown";
import { Button, Spinner, Textarea } from "@/components/ui/primitives";
import { api, ApiError, streamSSE } from "@/lib/api";
import { cn } from "@/lib/utils";

const MODES = [
  { id: "socratic", label: "Socratic", hint: "Guiding questions" },
  { id: "explanation", label: "Explain", hint: "Detailed explanation" },
  { id: "hint", label: "Hint", hint: "One hint at a time" },
  { id: "review", label: "Review", hint: "Revisit earlier concepts" },
  { id: "deep_dive", label: "Deep dive", hint: "Beyond the lesson" },
] as const;

type Msg = { role: "user" | "assistant"; content: string };
type Conv = { id: string; messages: Msg[]; mode: string };

export function TutorPanel({ lessonId, open, onClose, disabledReason }: { lessonId: string; open: boolean; onClose: () => void; disabledReason?: string }) {
  const { data: convs, mutate } = useSWR<Conv[]>(open ? `/api/tutor/conversations?lesson_id=${lessonId}` : null);
  const [convId, setConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [mode, setMode] = useState<string>("socratic");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (convs && convs.length && !convId) {
      setConvId(convs[0].id);
      setMessages(convs[0].messages);
      setMode(convs[0].mode);
    }
  }, [convs, convId]);
  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [messages]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setInput("");
    try {
      let id = convId;
      if (!id) {
        id = (await api<{ id: string }>("/api/tutor/conversations", { method: "POST", json: { lesson_id: lessonId, mode } })).id;
        setConvId(id);
      }
      setMessages((m) => [...m, { role: "user", content: text }, { role: "assistant", content: "" }]);
      await streamSSE(`/tutor/conversations/${id}/messages`, { message: text, mode }, (delta) =>
        setMessages((m) => {
          const copy = m.slice();
          copy[copy.length - 1] = { role: "assistant", content: copy[copy.length - 1].content + delta };
          return copy;
        }),
      );
      mutate();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The tutor is unavailable right now.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside
      className={cn(
        "fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-border bg-background shadow-xl transition-transform",
        open ? "translate-x-0" : "translate-x-full",
      )}
      aria-hidden={!open}
    >
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Bot size={18} className="text-primary" />
        <h2 className="font-semibold">Tutor</h2>
        <button className="ml-auto rounded-md p-1.5 hover:bg-muted" onClick={onClose} aria-label="Close tutor">
          <X size={16} />
        </button>
      </div>
      <div className="flex flex-wrap gap-1 border-b border-border px-4 py-2">
        {MODES.map((m) => (
          <button key={m.id} title={m.hint} onClick={() => setMode(m.id)} className={cn("rounded-full px-2.5 py-1 text-xs", mode === m.id ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:text-foreground")}>
            {m.label}
          </button>
        ))}
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {disabledReason ? (
          <p className="text-sm text-muted-foreground">{disabledReason}</p>
        ) : messages.length === 0 ? (
          <div className="text-sm text-muted-foreground">
            <p className="mb-2">Ask about anything in this lesson. The tutor knows the material and your progress, and won&apos;t hand you graded answers — it will help you get there.</p>
            <p>Try: “Why does the gradient point uphill?” or “Check my reasoning: …”</p>
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={cn("rounded-lg px-3 py-2", m.role === "user" ? "ml-8 bg-accent" : "mr-2 bg-card border border-border")}>
              {m.content ? <Markdown compact>{m.content}</Markdown> : <Spinner className="text-muted-foreground" />}
            </div>
          ))
        )}
        <div ref={endRef} />
      </div>
      {error && <p className="px-4 pb-2 text-sm text-danger">{error}</p>}
      <form
        className="flex items-end gap-2 border-t border-border p-3"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <Textarea
          rows={2}
          value={input}
          disabled={!!disabledReason}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Ask the tutor… (Shift+Enter for a new line)"
        />
        <Button type="submit" size="icon" disabled={busy || !input.trim() || !!disabledReason} aria-label="Send">
          {busy ? <Spinner /> : <Send size={16} />}
        </Button>
      </form>
    </aside>
  );
}
