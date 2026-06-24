import React, { useMemo } from "react";
import { cubeToPixel, hexPolygon, nodePositions, bounds, SIZE } from "./hex.js";
import { RESOURCE_COLORS, playerColor } from "./theme.js";

export default function Board({ geometry, frame }) {
  const { tiles, nodes, edges, ports } = geometry;

  const nodePos = useMemo(() => nodePositions(nodes), [nodes]);
  const tileCenters = useMemo(
    () => tiles.map((t) => ({ t, c: cubeToPixel(t.coord) })),
    [tiles]
  );
  const view = useMemo(() => {
    const pts = [...Object.values(nodePos), ...tileCenters.map((x) => x.c)];
    return bounds(pts, SIZE * 0.9);
  }, [nodePos, tileCenters]);

  const key = (a, b) => [a, b].sort((x, y) => x - y).join("-");
  const roadColor = {};
  (frame?.roads || []).forEach((r) => (roadColor[key(r.nodes[0], r.nodes[1])] = r.color));
  const robber = frame?.robber;

  return (
    <svg
      className="board"
      viewBox={`${view.minX} ${view.minY} ${view.w} ${view.h}`}
      preserveAspectRatio="xMidYMid meet"
    >
      {/* terrain hexes */}
      {tileCenters.map(({ t, c }) => {
        const red = t.number === 6 || t.number === 8;
        return (
          <g key={`tile-${t.id}-${c.x.toFixed(0)}-${c.y.toFixed(0)}`}>
            <polygon
              points={hexPolygon(c)}
              fill={RESOURCE_COLORS[t.resource] || RESOURCE_COLORS.DESERT}
              stroke="#00000033"
              strokeWidth="1.5"
            />
            {t.number != null && (
              <>
                <circle cx={c.x} cy={c.y} r={SIZE * 0.34} fill="#f8f1de" stroke="#0003" />
                <text
                  x={c.x}
                  y={c.y}
                  className={`tokenNum ${red ? "red" : ""}`}
                  textAnchor="middle"
                  dominantBaseline="central"
                >
                  {t.number}
                </text>
              </>
            )}
          </g>
        );
      })}

      {/* base road network (faint) */}
      {edges.map((e) => {
        const a = nodePos[e.nodes[0]], b = nodePos[e.nodes[1]];
        if (!a || !b) return null;
        return (
          <line key={`e-${e.nodes.join("-")}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
            stroke="#0000000f" strokeWidth="2" />
        );
      })}

      {/* ports */}
      {ports.map((p, i) => {
        const ps = p.nodes.map((n) => nodePos[n]).filter(Boolean);
        if (!ps.length) return null;
        const cx = ps.reduce((s, q) => s + q.x, 0) / ps.length;
        const cy = ps.reduce((s, q) => s + q.y, 0) / ps.length;
        return (
          <text key={`port-${i}`} x={cx} y={cy} className="port" textAnchor="middle">
            {p.resource ? `2:1 ${p.resource[0]}` : "3:1"}
          </text>
        );
      })}

      {/* built roads */}
      {Object.entries(roadColor).map(([k, color]) => {
        const [a, b] = k.split("-");
        const pa = nodePos[a], pb = nodePos[b];
        if (!pa || !pb) return null;
        return (
          <line key={`road-${k}`} x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
            stroke={playerColor(color)} strokeWidth="7" strokeLinecap="round" />
        );
      })}

      {/* robber */}
      {robber && (() => {
        const c = cubeToPixel(robber);
        return <circle cx={c.x} cy={c.y} r={SIZE * 0.2} fill="#212529" stroke="#fff" strokeWidth="2" />;
      })()}

      {/* settlements & cities */}
      {Object.entries(frame?.buildings || {}).map(([nid, b]) => {
        const p = nodePos[nid];
        if (!p) return null;
        const fill = playerColor(b.color);
        if (b.type === "CITY") {
          return (
            <rect key={`b-${nid}`} x={p.x - 9} y={p.y - 9} width="18" height="18" rx="3"
              fill={fill} stroke="#000" strokeWidth="2" />
          );
        }
        return <circle key={`b-${nid}`} cx={p.x} cy={p.y} r="8" fill={fill} stroke="#000" strokeWidth="2" />;
      })}
    </svg>
  );
}
