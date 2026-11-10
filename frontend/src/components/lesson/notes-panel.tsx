"use client";

import { NotebookPen, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Textarea } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

export function NotesPanel({ lessonId, initial, open, onClose }: { lessonId: string; initial: string; open: boolean; onClose: () => void }) {
  const [body, setBody] = useState(initial);
  const [status, setStatus] = useState<"saved" | "saving" | "error">("saved");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => setBody(initial), [initial]);

  function change(v: string) {
    setBody(v);
    setStatus("saving");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api(`/api/lessons/${lessonId}/note`, { method: "PUT", json: { body: v } }).then(() => setStatus("saved"), () => setStatus("error"));
    }, 800);
  }

  return (
    <aside className={cn("fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-border bg-background shadow-xl transition-transform", open ? "translate-x-0" : "translate-x-full")} aria-hidden={!open}>
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <NotebookPen size={18} className="text-primary" />
        <h2 className="font-semibold">Notes</h2>
        <span className="text-xs text-muted-foreground">{status === "saving" ? "Saving…" : status === "error" ? "Not saved — retrying on next edit" : "Saved"}</span>
        <button className="ml-auto rounded-md p-1.5 hover:bg-muted" onClick={onClose} aria-label="Close notes">
          <X size={16} />
        </button>
      </div>
      <Textarea className="flex-1 resize-none rounded-none border-0 font-serif text-[0.98rem] focus:ring-0" value={body} onChange={(e) => change(e.target.value)} placeholder="Your notes for this lesson. Markdown and $LaTeX$ welcome." />
    </aside>
  );
}
