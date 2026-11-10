"use client";

import dynamic from "next/dynamic";
import { useTheme } from "next-themes";

import { Spinner } from "@/components/ui/primitives";

const Monaco = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-muted-foreground">
      <Spinner />
    </div>
  ),
});

export function CodeEditor({ value, onChange, height = 360, readOnly = false, language = "python" }: { value: string; onChange?: (v: string) => void; height?: number; readOnly?: boolean; language?: string }) {
  const { resolvedTheme } = useTheme();
  return (
    <div className="overflow-hidden rounded-md border border-border" style={{ height }}>
      <Monaco
        language={language}
        value={value}
        theme={resolvedTheme === "dark" ? "vs-dark" : "light"}
        onChange={(v) => onChange?.(v ?? "")}
        options={{
          readOnly,
          minimap: { enabled: false },
          fontSize: 13,
          fontFamily: "var(--font-jetbrains), Menlo, monospace",
          scrollBeyondLastLine: false,
          tabSize: 4,
          insertSpaces: true,
          automaticLayout: true,
          wordWrap: "on",
        }}
      />
    </div>
  );
}
