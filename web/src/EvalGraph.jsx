import React from "react";
import { playerColor } from "./theme.js";

// Multi-line win-probability graph (one line per player, summing to 1).
// The Catan analogue of chess.com's single eval bar (brief §6.1).
export default function EvalGraph({ evalGraph, players, step, onJump }) {
  const W = 1000, H = 200, padL = 34, padB = 18, padT = 8;
  const n = evalGraph.length;
  const x = (i) => padL + (i / Math.max(1, n - 1)) * (W - padL - 6);
  const y = (v) => padT + (1 - v) * (H - padT - padB);

  const lines = players.map((p) => {
    const c = p.color;
    const d = evalGraph
      .map((g, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(g.wp[c] ?? 0).toFixed(1)}`)
      .join(" ");
    return { c, d };
  });

  return (
    <div className="evalgraph">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
        onClick={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const px = ((e.clientX - rect.left) / rect.width) * W;
          const i = Math.round(((px - padL) / (W - padL - 6)) * (n - 1));
          onJump(Math.max(0, Math.min(n - 1, i)));
        }}>
        {[0, 0.25, 0.5, 0.75, 1].map((gy) => (
          <g key={gy}>
            <line x1={padL} y1={y(gy)} x2={W} y2={y(gy)} stroke="#0000000d" />
            <text x={4} y={y(gy) + 3} className="axis">{Math.round(gy * 100)}</text>
          </g>
        ))}
        <line className="cursor" x1={x(step)} y1={padT} x2={x(step)} y2={H - padB} />
        {lines.map((l) => (
          <path key={l.c} d={l.d} fill="none" stroke={playerColor(l.c)} strokeWidth="2.5"
            strokeLinejoin="round" opacity="0.95" />
        ))}
      </svg>
    </div>
  );
}
