"use client";

import { useMemo, useState } from "react";

import { Slider } from "./plot";

const TOKENS = ["the", "cat", "sat", "on", "the", "mat"];
// tiny fixed 3-d "embeddings" so the pattern is reproducible and interpretable
const EMB: Record<string, number[]> = { the: [0.1, 0.9, 0.0], cat: [1.0, 0.1, 0.4], sat: [0.3, 0.2, 1.0], on: [0.0, 0.8, 0.3], mat: [0.9, 0.2, 0.5] };

export function AttentionMatrix({ params }: { params: Record<string, number> }) {
  const [temp, setTemp] = useState(params.temperature ?? 1);
  const [causal, setCausal] = useState((params.causal ?? 0) > 0);
  const weights = useMemo(() => {
    const d = 3;
    return TOKENS.map((q, i) => {
      const scores = TOKENS.map((k, j) => (causal && j > i ? -Infinity : EMB[q].reduce((s, v, t) => s + v * EMB[k][t], 0) / Math.sqrt(d) / temp));
      const mx = Math.max(...scores.filter(Number.isFinite));
      const ex = scores.map((s) => (Number.isFinite(s) ? Math.exp(s - mx) : 0));
      const z = ex.reduce((a, b) => a + b, 0);
      return ex.map((e) => e / z);
    });
  }, [temp, causal]);
  const cell = 46;
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-0.5 font-mono text-xs">
          <thead>
            <tr>
              <th className="pr-2 text-right font-normal text-muted-foreground">query ↓ key →</th>
              {TOKENS.map((t, j) => (
                <th key={j} className="px-1 font-normal text-muted-foreground" style={{ width: cell }}>{t}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {weights.map((row, i) => (
              <tr key={i}>
                <td className="pr-2 text-right text-muted-foreground">{TOKENS[i]}</td>
                {row.map((w, j) => (
                  <td key={j} className="text-center tabular-nums" style={{ width: cell, height: 30, background: `color-mix(in oklab, var(--primary) ${Math.round(w * 100)}%, var(--card))`, color: w > 0.5 ? "var(--primary-foreground)" : "var(--foreground)" }}>
                    {w.toFixed(2)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Slider label="temperature" value={temp} min={0.1} max={3} step={0.05} onChange={setTemp} />
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={causal} onChange={(e) => setCausal(e.target.checked)} /> causal mask (a token can&apos;t attend to later tokens)
      </label>
    </div>
  );
}
