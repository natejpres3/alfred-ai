"use client";

import { useState } from "react";

import { Readout, Slider } from "./plot";

const f = (x: number) => x ** 3 - 2 * x;
const df = (x: number) => 3 * x ** 2 - 2;

export function DerivativeTangent({ params }: { params: Record<string, number> }) {
  const [x0, setX0] = useState(params.x0 ?? 1);
  const [h, setH] = useState(params.h ?? 0.5);
  const W = 420, H = 300, xr = 2.5, yr = 6;
  const X = (x: number) => ((x + xr) / (2 * xr)) * W;
  const Y = (y: number) => H / 2 - (y / yr) * (H / 2);
  const pts = Array.from({ length: 201 }, (_, i) => -xr + (2 * xr * i) / 200).map((x) => `${X(x)},${Y(f(x))}`).join(" ");
  const secant = (f(x0 + h) - f(x0)) / h;
  const line = (slope: number) => [[-xr, f(x0) + slope * (-xr - x0)], [xr, f(x0) + slope * (xr - x0)]];
  const [t1, t2] = line(df(x0));
  const [s1, s2] = line(secant);
  const predicted = f(x0) + df(x0) * h;

  return (
    <div className="grid gap-4 md:grid-cols-[minmax(0,420px)_1fr]">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded-md border border-border bg-card">
        <defs>
          <clipPath id="clip-deriv">
            <rect width={W} height={H} />
          </clipPath>
        </defs>
        <g clipPath="url(#clip-deriv)">
          <line x1={0} x2={W} y1={Y(0)} y2={Y(0)} stroke="var(--plot-grid)" strokeWidth={1.5} />
          <line y1={0} y2={H} x1={X(0)} x2={X(0)} stroke="var(--plot-grid)" strokeWidth={1.5} />
          <polyline points={pts} fill="none" stroke="var(--foreground)" strokeWidth={2} />
          <line x1={X(s1[0])} y1={Y(s1[1])} x2={X(s2[0])} y2={Y(s2[1])} stroke="var(--vec-b)" strokeWidth={1.5} strokeDasharray="5 4" />
          <line x1={X(t1[0])} y1={Y(t1[1])} x2={X(t2[0])} y2={Y(t2[1])} stroke="var(--vec-a)" strokeWidth={2} />
          <circle cx={X(x0)} cy={Y(f(x0))} r={4.5} fill="var(--vec-a)" />
          <circle cx={X(x0 + h)} cy={Y(f(x0 + h))} r={4} fill="var(--vec-b)" />
        </g>
      </svg>
      <div className="space-y-3">
        <Slider label="x₀" value={x0} min={-2} max={2} step={0.01} onChange={setX0} />
        <Slider label="h" value={h} min={0.001} max={1.5} step={0.001} onChange={setH} format={(v) => v.toFixed(3)} />
        <Readout
          items={[
            ["f(x₀)", f(x0).toFixed(4)],
            ["f′(x₀)", df(x0).toFixed(4)],
            ["secant slope", secant.toFixed(4)],
            ["f(x₀+h)", f(x0 + h).toFixed(4)],
            ["tangent predicts", predicted.toFixed(4)],
            ["error", Math.abs(f(x0 + h) - predicted).toExponential(2)],
          ]}
        />
        <p className="text-sm text-muted-foreground">
          <span style={{ color: "var(--vec-a)" }}>Tangent</span> vs <span style={{ color: "var(--vec-b)" }}>secant</span>. Halve h and watch the prediction error shrink about 4×: it is second order in h.
        </p>
      </div>
    </div>
  );
}
