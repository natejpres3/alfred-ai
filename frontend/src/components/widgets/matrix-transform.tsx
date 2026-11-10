"use client";

import { useState } from "react";

import { Arrow, Grid, Readout, Slider, usePlot } from "./plot";

export function MatrixTransform2D({ params }: { params: Record<string, number> }) {
  const plot = usePlot(4);
  const { X, Y, size } = plot;
  const [m, setM] = useState({ a: params.a ?? 1, b: params.b ?? 0, c: params.c ?? 0, d: params.d ?? 1 });
  const T = (x: number, y: number): [number, number] => [m.a * x + m.b * y, m.c * x + m.d * y];
  const det = m.a * m.d - m.b * m.c;

  const lines = [];
  for (let k = -4; k <= 4; k++) {
    const [x1, y1] = T(k, -4);
    const [x2, y2] = T(k, 4);
    const [x3, y3] = T(-4, k);
    const [x4, y4] = T(4, k);
    lines.push(<line key={`v${k}`} x1={X(x1)} y1={Y(y1)} x2={X(x2)} y2={Y(y2)} stroke="var(--primary)" strokeOpacity={0.25} />);
    lines.push(<line key={`h${k}`} x1={X(x3)} y1={Y(y3)} x2={X(x4)} y2={Y(y4)} stroke="var(--primary)" strokeOpacity={0.25} />);
  }
  const sq = [T(0, 0), T(1, 0), T(1, 1), T(0, 1)].map(([x, y]) => `${X(x)},${Y(y)}`).join(" ");

  return (
    <div className="grid gap-4 md:grid-cols-[minmax(0,360px)_1fr]">
      <svg viewBox={`0 0 ${size} ${size}`} className="w-full rounded-md border border-border bg-card">
        <Grid {...plot} />
        <g>{lines}</g>
        <polygon points={sq} fill="var(--primary)" fillOpacity={0.12} stroke="var(--primary)" strokeOpacity={0.5} />
        <Arrow x1={X(0)} y1={Y(0)} x2={X(m.a)} y2={Y(m.c)} color="var(--vec-a)" label="Ae₁" />
        <Arrow x1={X(0)} y1={Y(0)} x2={X(m.b)} y2={Y(m.d)} color="var(--vec-b)" label="Ae₂" />
      </svg>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-x-6 gap-y-2">
          {(["a", "b", "c", "d"] as const).map((k) => (
            <Slider key={k} label={k} value={m[k]} min={-3} max={3} step={0.1} onChange={(v) => setM({ ...m, [k]: v })} />
          ))}
        </div>
        <div className="font-mono text-sm">
          A = [[{m.a.toFixed(1)}, {m.b.toFixed(1)}], [{m.c.toFixed(1)}, {m.d.toFixed(1)}]]
        </div>
        <Readout items={[["Ae₁ (col 1)", `(${m.a.toFixed(1)}, ${m.c.toFixed(1)})`], ["Ae₂ (col 2)", `(${m.b.toFixed(1)}, ${m.d.toFixed(1)})`], ["area scale (det)", det.toFixed(2)]]} />
        <p className="text-sm text-muted-foreground">
          {Math.abs(det) < 1e-9 ? "The columns are parallel: the plane collapses onto a line (det = 0)." : det < 0 ? "Negative determinant: orientation is flipped." : "The shaded square shows how unit area is transformed."}
        </p>
      </div>
    </div>
  );
}
