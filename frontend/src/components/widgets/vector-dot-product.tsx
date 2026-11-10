"use client";

import { useState } from "react";

import { Arrow, Grid, Readout, useDrag, usePlot } from "./plot";

export function VectorDotProduct({ params }: { params: Record<string, number> }) {
  const plot = usePlot(5);
  const { X, Y, inv, size } = plot;
  const [a, setA] = useState<[number, number]>([params.ax ?? 2, params.ay ?? 1]);
  const [b, setB] = useState<[number, number]>([params.bx ?? 1, params.by ?? 3]);
  const [target, setTarget] = useState<"a" | "b" | null>(null);
  const drag = useDrag((px, py) => {
    const [x, y] = inv(px, py);
    const snap = (v: number) => Math.max(-4.8, Math.min(4.8, Math.round(v * 4) / 4));
    if (target === "a") setA([snap(x), snap(y)]);
    if (target === "b") setB([snap(x), snap(y)]);
  });

  const dot = a[0] * b[0] + a[1] * b[1];
  const na = Math.hypot(...a);
  const nb = Math.hypot(...b);
  const cos = na && nb ? dot / (na * nb) : NaN;
  const angle = (Math.acos(Math.max(-1, Math.min(1, cos))) * 180) / Math.PI;
  const t = nb ? dot / (nb * nb) : 0; // projection of a onto b = t·b
  const proj: [number, number] = [t * b[0], t * b[1]];

  return (
    <div className="grid gap-4 md:grid-cols-[minmax(0,360px)_1fr]">
      <svg
        ref={drag.svgRef}
        viewBox={`0 0 ${size} ${size}`}
        className="w-full touch-none select-none rounded-md border border-border bg-card"
        onPointerMove={drag.move}
        onPointerUp={() => {
          drag.end();
          setTarget(null);
        }}
        onPointerLeave={() => setTarget(null)}
      >
        <Grid {...plot} />
        <line x1={X(a[0])} y1={Y(a[1])} x2={X(proj[0])} y2={Y(proj[1])} stroke="var(--muted-foreground)" strokeDasharray="4 4" />
        <line x1={X(0)} y1={Y(0)} x2={X(proj[0])} y2={Y(proj[1])} stroke="var(--vec-a)" strokeOpacity={0.35} strokeWidth={8} strokeLinecap="round" />
        <Arrow x1={X(0)} y1={Y(0)} x2={X(b[0])} y2={Y(b[1])} color="var(--vec-b)" label="b" />
        <Arrow x1={X(0)} y1={Y(0)} x2={X(a[0])} y2={Y(a[1])} color="var(--vec-a)" label="a" />
        {(["a", "b"] as const).map((k) => {
          const v = k === "a" ? a : b;
          return (
            <circle
              key={k}
              cx={X(v[0])}
              cy={Y(v[1])}
              r={11}
              fill="transparent"
              stroke={k === "a" ? "var(--vec-a)" : "var(--vec-b)"}
              strokeOpacity={0.4}
              className="cursor-grab"
              onPointerDown={(e) => {
                setTarget(k);
                drag.start(e);
              }}
            />
          );
        })}
      </svg>
      <div className="space-y-3 text-sm">
        <Readout
          items={[
            ["a", `(${a[0].toFixed(2)}, ${a[1].toFixed(2)})`],
            ["b", `(${b[0].toFixed(2)}, ${b[1].toFixed(2)})`],
            ["a·b", dot.toFixed(3)],
            ["|a|", na.toFixed(3)],
            ["|b|", nb.toFixed(3)],
            ["θ", Number.isNaN(angle) ? "—" : `${angle.toFixed(1)}°`],
            ["cos θ", Number.isNaN(cos) ? "—" : cos.toFixed(3)],
            ["|a| cos θ", nb ? (dot / nb).toFixed(3) : "—"],
          ]}
        />
        <p className="text-muted-foreground">
          {Math.abs(dot) < 1e-9 ? "Orthogonal: a casts no shadow on b." : dot > 0 ? "Positive: a points partly along b." : "Negative: a points partly against b."}
        </p>
      </div>
    </div>
  );
}
