"use client";

import { useCallback, useRef } from "react";

/** A square SVG plot over [-R, R]² with world↔screen helpers and an optional pointer-drag handler. */
export function usePlot(range: number, size = 360) {
  const s = size / (2 * range);
  const X = (x: number) => size / 2 + x * s;
  const Y = (y: number) => size / 2 - y * s;
  const inv = (px: number, py: number) => [(px - size / 2) / s, (size / 2 - py) / s] as const;
  return { size, range, X, Y, inv, s };
}

export function Grid({ range, X, Y, step = 1 }: { range: number; X: (x: number) => number; Y: (y: number) => number; step?: number }) {
  const lines = [];
  for (let v = -Math.floor(range); v <= range; v += step) {
    lines.push(<line key={`v${v}`} x1={X(v)} x2={X(v)} y1={Y(-range)} y2={Y(range)} stroke="var(--plot-grid)" strokeWidth={v === 0 ? 1.5 : 1} />);
    lines.push(<line key={`h${v}`} y1={Y(v)} y2={Y(v)} x1={X(-range)} x2={X(range)} stroke="var(--plot-grid)" strokeWidth={v === 0 ? 1.5 : 1} />);
  }
  return <g>{lines}</g>;
}

export function Arrow({ x1, y1, x2, y2, color, width = 2.5, label }: { x1: number; y1: number; x2: number; y2: number; color: string; width?: number; label?: string }) {
  const ang = Math.atan2(y2 - y1, x2 - x1);
  const h = 10;
  const p1 = [x2 - h * Math.cos(ang - 0.4), y2 - h * Math.sin(ang - 0.4)];
  const p2 = [x2 - h * Math.cos(ang + 0.4), y2 - h * Math.sin(ang + 0.4)];
  return (
    <g>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={width} strokeLinecap="round" />
      <polygon points={`${x2},${y2} ${p1[0]},${p1[1]} ${p2[0]},${p2[1]}`} fill={color} />
      {label && (
        <text x={x2 + 8} y={y2 - 8} fill={color} fontSize={14} fontWeight={600} fontFamily="var(--font-serif)" fontStyle="italic">
          {label}
        </text>
      )}
    </g>
  );
}

export function useDrag(onMove: (px: number, py: number) => void) {
  const svgRef = useRef<SVGSVGElement>(null);
  const dragging = useRef<boolean>(false);
  const toLocal = useCallback((e: React.PointerEvent) => {
    const svg = svgRef.current!;
    const r = svg.getBoundingClientRect();
    const vb = svg.viewBox.baseVal;
    return [((e.clientX - r.left) / r.width) * vb.width, ((e.clientY - r.top) / r.height) * vb.height] as const;
  }, []);
  return {
    svgRef,
    start: (e: React.PointerEvent) => {
      dragging.current = true;
      (e.target as Element).setPointerCapture?.(e.pointerId);
    },
    move: (e: React.PointerEvent) => {
      if (!dragging.current) return;
      const [x, y] = toLocal(e);
      onMove(x, y);
    },
    end: () => {
      dragging.current = false;
    },
  };
}

export function Slider({ label, value, min, max, step, onChange, format }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; format?: (v: number) => string }) {
  return (
    <label className="flex items-center gap-3 text-sm">
      <span className="w-28 shrink-0 font-mono text-xs text-muted-foreground">{label}</span>
      <input type="range" className="w-full" min={min} max={max} step={step} value={value} onChange={(e) => onChange(parseFloat(e.target.value))} />
      <span className="w-16 shrink-0 text-right font-mono text-xs tabular-nums">{format ? format(value) : value.toFixed(2)}</span>
    </label>
  );
}

export function Readout({ items }: { items: [string, string][] }) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-xs sm:grid-cols-3">
      {items.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-2 border-b border-border/60 py-1">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className="tabular-nums">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
