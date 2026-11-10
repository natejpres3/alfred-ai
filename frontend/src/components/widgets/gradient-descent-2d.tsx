"use client";

import { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Readout, Slider } from "./plot";

const STEPS = 60;

export function GradientDescent2D({ params }: { params: Record<string, number> }) {
  const [a, setA] = useState(params.a ?? 1);
  const [b, setB] = useState(params.b ?? 10);
  const [lr, setLr] = useState(params.lr ?? 0.05);
  const [start, setStart] = useState<[number, number]>([params.x0 ?? -4, params.y0 ?? 2]);
  const W = 420, H = 300, xr = 5, yr = (5 * H) / W;
  const X = (x: number) => ((x + xr) / (2 * xr)) * W;
  const Y = (y: number) => H / 2 - (y / yr) * (H / 2);
  const loss = (x: number, y: number) => 0.5 * (a * x * x + b * y * y);

  const { path, losses, diverged } = useMemo(() => {
    const path: [number, number][] = [start];
    let [x, y] = start;
    let diverged = false;
    for (let i = 0; i < STEPS; i++) {
      x -= lr * a * x;
      y -= lr * b * y;
      if (!Number.isFinite(x) || !Number.isFinite(y) || Math.abs(x) > 1e6 || Math.abs(y) > 1e6) {
        diverged = true;
        break;
      }
      path.push([x, y]);
    }
    return { path, losses: path.map(([px, py], i) => ({ step: i, loss: Math.max(1e-12, loss(px, py)) })), diverged };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a, b, lr, start]);

  const levels = [0.25, 1, 2.5, 5, 10, 20, 40];
  const final = path[path.length - 1];

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-[minmax(0,420px)_1fr]">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full cursor-crosshair rounded-md border border-border bg-card"
          onClick={(e) => {
            const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            const px = ((e.clientX - r.left) / r.width) * W;
            const py = ((e.clientY - r.top) / r.height) * H;
            setStart([(px / W) * 2 * xr - xr, ((H / 2 - py) / (H / 2)) * yr]);
          }}
        >
          <defs>
            <clipPath id="clip-gd">
              <rect width={W} height={H} />
            </clipPath>
          </defs>
          <g clipPath="url(#clip-gd)">
            {levels.map((L) => (
              <ellipse key={L} cx={X(0)} cy={Y(0)} rx={(Math.sqrt((2 * L) / a) / (2 * xr)) * W} ry={(Math.sqrt((2 * L) / b) / (2 * yr)) * H} fill="none" stroke="var(--plot-grid)" strokeWidth={1.3} />
            ))}
            <line x1={0} x2={W} y1={Y(0)} y2={Y(0)} stroke="var(--plot-grid)" />
            <line y1={0} y2={H} x1={X(0)} x2={X(0)} stroke="var(--plot-grid)" />
            <polyline points={path.map(([x, y]) => `${X(x)},${Y(y)}`).join(" ")} fill="none" stroke="var(--vec-a)" strokeWidth={1.8} />
            {path.map(([x, y], i) => (
              <circle key={i} cx={X(x)} cy={Y(y)} r={i === 0 ? 4.5 : 2.4} fill={i === 0 ? "var(--vec-b)" : "var(--vec-a)"} />
            ))}
          </g>
        </svg>
        <div className="space-y-3">
          <Slider label="learning rate" value={lr} min={0.001} max={Math.max(0.3, 2.4 / Math.max(a, b))} step={0.001} onChange={setLr} format={(v) => v.toFixed(3)} />
          <Slider label="curvature a (x)" value={a} min={0.2} max={30} step={0.1} onChange={setA} />
          <Slider label="curvature b (y)" value={b} min={0.2} max={30} step={0.1} onChange={setB} />
          <Readout
            items={[
              ["1/max(a,b)", (1 / Math.max(a, b)).toFixed(3)],
              ["2/max(a,b)", (2 / Math.max(a, b)).toFixed(3)],
              ["factor x", (1 - lr * a).toFixed(3)],
              ["factor y", (1 - lr * b).toFixed(3)],
              ["final loss", diverged ? "diverged" : loss(final[0], final[1]).toExponential(2)],
              ["steps", String(path.length - 1)],
            ]}
          />
          <p className="text-sm text-muted-foreground">Click the plot to choose a new starting point.</p>
        </div>
      </div>
      <div className="h-40 rounded-md border border-border bg-card p-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={losses} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--plot-grid)" strokeDasharray="3 3" />
            <XAxis dataKey="step" tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} stroke="var(--border)" />
            <YAxis scale="log" domain={["auto", "auto"]} allowDataOverflow tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} stroke="var(--border)" tickFormatter={(v: number) => v.toExponential(0)} width={48} />
            <Tooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", fontSize: 12 }} formatter={(v: number) => v.toExponential(3)} />
            <Line type="monotone" dataKey="loss" stroke="var(--primary)" dot={false} strokeWidth={2} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
