import React, { useMemo } from "react";
import { cubeToPixel, hexPolygon, nodePositions, bounds, SIZE } from "./hex.js";
import { RESOURCE_COLORS, RES_NAME, playerColor } from "./theme.js";

// Renders the board from static `geometry` + a per-frame `frame` snapshot.
// In play mode, `targets` marks legal build/robber spots and `onTarget`
// receives clicks: { nodes: {nodeId: actionId}, edges: {"a-b": actionId},
// hexes: {"x,y,z": true} }, absent in review mode (pure display).
export default function Board({ geometry, frame, targets, onTarget, suggest }) {
  const { tiles, nodes, edges, ports } = geometry;

  const nodePos = useMemo(() => nodePositions(nodes), [nodes]);
  const tileCenters = useMemo(
    () => tiles.map((t) => ({ t, c: cubeToPixel(t.coord) })),
    [tiles]
  );
  const view = useMemo(() => {
    const pts = [...Object.values(nodePos), ...tileCenters.map((x) => x.c)];
    return bounds(pts, SIZE * 1.5); // room for the port badges off the coast
  }, [nodePos, tileCenters]);

  const key = (a, b) => [a, b].sort((x, y) => x - y).join("-");
  const roadColor = {};
  (frame?.roads || []).forEach((r) => (roadColor[key(r.nodes[0], r.nodes[1])] = r.color));
  const robber = frame?.robber;

  const nodeTargets = targets?.nodes || {};
  const edgeTargets = targets?.edges || {};
  const hexTargets = targets?.hexes || {};

  return (
    <svg
      className="board"
      viewBox={`${view.minX} ${view.minY} ${view.w} ${view.h}`}
      preserveAspectRatio="xMidYMid meet"
    >
      {/* terrain hexes */}
      {tileCenters.map(({ t, c }) => {
        const red = t.number === 6 || t.number === 8;
        const hk = (t.coord || []).join(",");
        const clickable = hk in hexTargets;
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
            {clickable && (
              <polygon
                points={hexPolygon(c)}
                className="target hexTarget"
                data-hex={hk}
                onClick={() => onTarget("hex", hk)}
              />
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

      {/* ports: badge pushed off the coast (radially outward), with dots on
          the two intersections that actually grant the port */}
      {ports.map((p, i) => {
        const ps = p.nodes.map((n) => nodePos[n]).filter(Boolean);
        if (!ps.length) return null;
        const cx = ps.reduce((s, q) => s + q.x, 0) / ps.length;
        const cy = ps.reduce((s, q) => s + q.y, 0) / ps.length;
        const d = Math.hypot(cx, cy) || 1; // board is centered on (0,0)
        const bx = cx + (cx / d) * SIZE * 0.85;
        const by = cy + (cy / d) * SIZE * 0.85;
        const label = p.resource ? `2:1 ${RES_NAME[p.resource] || p.resource.toLowerCase()}` : "3:1";
        const w = p.resource ? 68 : 36;
        return (
          <g key={`port-${i}`} className="portg">
            {ps.map((q, j) => (
              <line key={`l${j}`} x1={bx} y1={by} x2={q.x} y2={q.y} className="portline" />
            ))}
            {ps.map((q, j) => (
              <circle key={`d${j}`} cx={q.x} cy={q.y} r="3.5" className="portdot" />
            ))}
            <rect x={bx - w / 2} y={by - 11} width={w} height="22" rx="11" className="portbadge" />
            <text x={bx} y={by + 1} className="port" textAnchor="middle" dominantBaseline="central">
              {label}
            </text>
          </g>
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

      {/* clickable edge targets (legal roads) */}
      {Object.keys(edgeTargets).map((k) => {
        const [a, b] = k.split("-");
        const pa = nodePos[a], pb = nodePos[b];
        if (!pa || !pb) return null;
        return (
          <g key={`et-${k}`}>
            <line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
              className="targetGhost" strokeWidth="6" strokeLinecap="round" />
            <line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
              className="target edgeTarget" strokeWidth="14" strokeLinecap="round"
              data-edge={k} onClick={() => onTarget("edge", k)} />
          </g>
        );
      })}

      {/* clickable node targets (legal settlements / city upgrades) */}
      {Object.keys(nodeTargets).map((nid) => {
        const p = nodePos[nid];
        if (!p) return null;
        return (
          <g key={`nt-${nid}`}>
            <circle cx={p.x} cy={p.y} r="10" className="targetGhost nodeGhost" />
            <circle cx={p.x} cy={p.y} r="13" className="target nodeTarget"
              data-node={nid} onClick={() => onTarget("node", nid)} />
          </g>
        );
      })}

      {/* suggestion marker (engine's better move / hint) */}
      {suggest?.node != null && nodePos[suggest.node] && (() => {
        const p = nodePos[suggest.node];
        return (
          <g className="suggest">
            <circle cx={p.x} cy={p.y} r="15" className="suggestRing" />
            <text x={p.x} y={p.y - 22} className="suggestStar" textAnchor="middle">★</text>
          </g>
        );
      })()}
      {suggest?.edge && (() => {
        const pa = nodePos[suggest.edge[0]], pb = nodePos[suggest.edge[1]];
        if (!pa || !pb) return null;
        return (
          <g className="suggest">
            <line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} className="suggestEdge" />
            <text x={(pa.x + pb.x) / 2} y={(pa.y + pb.y) / 2 - 14}
              className="suggestStar" textAnchor="middle">★</text>
          </g>
        );
      })()}
      {suggest?.coord && (() => {
        const c = cubeToPixel(suggest.coord);
        return (
          <g className="suggest">
            <circle cx={c.x} cy={c.y} r={SIZE * 0.5} className="suggestRing" />
            <text x={c.x} y={c.y - SIZE * 0.58} className="suggestStar" textAnchor="middle">★</text>
          </g>
        );
      })()}
    </svg>
  );
}
