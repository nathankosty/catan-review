import React, { useEffect, useMemo, useRef, useState } from "react";
import Board from "./Board.jsx";
import EvalGraph from "./EvalGraph.jsx";
import { initEngine, engine } from "./engine.js";
import { LABEL_STYLE, playerColor, PLAYER_TEXT } from "./theme.js";
import { PlayerChip, LabelBadge } from "./ReviewApp.jsx";

const pct = (v) => `${Math.round((v ?? 0) * 100)}%`;
const RES_ICON = { WOOD: "🌲", BRICK: "🧱", SHEEP: "🐑", WHEAT: "🌾", ORE: "⛰️" };
const DEV_NAME = {
  KNIGHT: "Knight", YEAR_OF_PLENTY: "Year of Plenty", MONOPOLY: "Monopoly",
  ROAD_BUILDING: "Road Building", VICTORY_POINT: "Victory Point",
};

// Let the spinner paint before a synchronous WASM call blocks the thread.
const soon = () => new Promise((r) => setTimeout(r, 30));

export default function PlayApp({ options, onFinish, onHome }) {
  const [progress, setProgress] = useState("Starting…");
  const [state, setState] = useState(null);
  const [geometry, setGeometry] = useState(null);
  const [feedback, setFeedback] = useState(null);
  const [victimChoice, setVictimChoice] = useState(null);
  const [hint, setHint] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      try {
        await initEngine(setProgress);
        setProgress("Setting up the table…");
        await soon();
        const st = engine.startSession(options);
        setGeometry(engine.geometry());
        setState(st);
        setProgress(null);
      } catch (e) {
        setErr(String(e));
      }
    })();
  }, [options]);

  const run = async (fn) => {
    setBusy(true);
    setHint(null);
    await soon();
    try { fn(); } catch (e) { setErr(String(e)); }
    setBusy(false);
  };

  const submit = (id) =>
    run(() => {
      const res = engine.submit(id);
      if (res.error) throw new Error(res.error);
      setVictimChoice(null);
      setState(res.state);
      if (res.feedback) {
        setFeedback(res.feedback); // pause for the learning moment
      } else if (!res.state.is_human_turn && !res.state.over) {
        setState(engine.advance()); // forced move (e.g. roll): bots go on
      }
    });

  const onContinue = () =>
    run(() => {
      setFeedback(null);
      setState((s) => (!s.is_human_turn && !s.over ? engine.advance() : s));
    });

  const onTakeBack = () =>
    run(() => {
      setFeedback(null);
      setState(engine.takeBack());
    });

  const onHint = () =>
    run(() => setHint(engine.hint().hint));

  // ---- board click targets from the legal actions --------------------------
  const targets = useMemo(() => {
    if (!state?.is_human_turn) return null;
    const nodes = {}, edges = {}, hexes = {};
    for (const a of state.legal_actions) {
      if (a.node != null) nodes[a.node] = a.id;
      else if (a.edge) edges[[...a.edge].sort((x, y) => x - y).join("-")] = a.id;
      else if (a.coord) {
        const k = a.coord.join(",");
        (hexes[k] = hexes[k] || []).push(a);
      }
    }
    return { nodes, edges, hexes };
  }, [state]);

  const onTarget = (kind, key) => {
    if (busy || feedback) return;
    if (kind === "node") submit(targets.nodes[key]);
    else if (kind === "edge") submit(targets.edges[key]);
    else if (kind === "hex") {
      const opts = targets.hexes[key];
      if (opts.length === 1) submit(opts[0].id);
      else setVictimChoice(opts);
    }
  };

  // ---- panel actions (non-spatial) ------------------------------------------
  const grouped = useMemo(() => {
    const g = {};
    for (const a of state?.legal_actions || []) {
      if (a.node != null || a.edge || a.coord) continue; // on-board
      (g[a.type] = g[a.type] || []).push(a);
    }
    return g;
  }, [state]);

  if (err) return (
    <div className="fatal">
      <p>{err}</p>
      <button onClick={onHome}>⌂ Home</button>
    </div>
  );
  if (progress || !state) return (
    <div className="loading big">
      <div className="spinner" />
      <p>{progress || "Loading…"}</p>
      <p className="muted">First visit downloads the engine (~10 MB) — cached afterwards.</p>
    </div>
  );

  const me = state.human;
  const myWp = state.wp[me] ?? 0;
  const boardTargets = feedback || victimChoice ? null : targets;
  const spatialHints = [];
  if (state.is_human_turn && targets) {
    if (Object.keys(targets.nodes).length) spatialHints.push("spot");
    if (Object.keys(targets.edges).length) spatialHints.push("road edge");
    if (Object.keys(targets.hexes).length) spatialHints.push("robber hex");
  }

  return (
    <div className="app playmode">
      <header>
        <div className="titlerow">
          <div className="title">♟ Catan Review · Play</div>
          <button className="linkbtn" onClick={onHome}>⌂ Quit</button>
        </div>
        <div className="sub">
          You are <PlayerChip color={me} /> · turn {state.turn} · {state.phase} game ·
          your win chance <b>{pct(myWp)}</b>
        </div>
      </header>

      <div className="layout">
        <section className="left">
          <div className="boardwrap">
            <Board geometry={geometry} frame={state.board} targets={boardTargets} onTarget={onTarget} />
            {busy && <div className="thinking">…</div>}
          </div>

          {/* turn banner / actions */}
          {state.over ? (
            <div className="panel final">
              <h3>🏆 {state.winner} wins</h3>
              <p>
                {state.winner === me ? "Congratulations!" : "Good game."} Now walk
                through every move like a chess.com game review.
              </p>
              <button className="primary" disabled={busy}
                onClick={() => run(() => onFinish(engine.finalReview()))}>
                📊 Review my game
              </button>
            </div>
          ) : state.is_human_turn ? (
            <div className="panel actions">
              <div className="dhead">
                <b>Your move</b>
                {spatialHints.length > 0 && (
                  <span className="muted"> — click a highlighted {spatialHints.join(" / ")} on the board</span>
                )}
                <span className="spacer" />
                <button className="linkbtn" onClick={onHint} disabled={busy}>💡 hint</button>
                {state.can_take_back && !feedback && (
                  <button className="linkbtn" onClick={onTakeBack} disabled={busy}>↩ take back</button>
                )}
              </div>
              {hint && <div className="hintbox">💡 {hint.text} (→ {pct(hint.wp)} win chance)</div>}
              {victimChoice && (
                <div className="victimbox">
                  Steal from:{" "}
                  {victimChoice.map((a) => (
                    <button key={a.id} onClick={() => submit(a.id)} disabled={busy}>
                      {a.victim ? <PlayerChip color={a.victim} /> : "no one"}
                    </button>
                  ))}
                  <button className="linkbtn" onClick={() => setVictimChoice(null)}>cancel</button>
                </div>
              )}
              <div className="actionbtns">
                {state.must_roll && (
                  <button className="primary roll" disabled={busy} onClick={() => submit(0)}>
                    🎲 Roll dice
                  </button>
                )}
                {(grouped.BUY_DEVELOPMENT_CARD || []).map((a) => (
                  <button key={a.id} disabled={busy} onClick={() => submit(a.id)}>🃏 Buy dev card</button>
                ))}
                {(grouped.PLAY_KNIGHT_CARD || []).map((a) => (
                  <button key={a.id} disabled={busy} onClick={() => submit(a.id)}>⚔️ Play Knight</button>
                ))}
                {(grouped.PLAY_ROAD_BUILDING || []).map((a) => (
                  <button key={a.id} disabled={busy} onClick={() => submit(a.id)}>🛤️ Road Building</button>
                ))}
                {(grouped.PLAY_MONOPOLY || []).map((a) => (
                  <button key={a.id} disabled={busy} onClick={() => submit(a.id)}>
                    🎩 Monopoly: {RES_ICON[a.resource]} {a.resource}
                  </button>
                ))}
                {(grouped.PLAY_YEAR_OF_PLENTY || []).map((a) => (
                  <button key={a.id} disabled={busy} onClick={() => submit(a.id)}>
                    🎁 Take {(a.resources || []).map((r) => RES_ICON[r]).join(" ")}
                  </button>
                ))}
                {(grouped.MARITIME_TRADE || []).map((a) => (
                  <button key={a.id} disabled={busy} onClick={() => submit(a.id)}>
                    ⚓ {(a.gives || []).map((r) => RES_ICON[r]).join("")} → {RES_ICON[a.receives]}
                  </button>
                ))}
                {(grouped.END_TURN || []).map((a) => (
                  <button key={a.id} className="endturn" disabled={busy} onClick={() => submit(a.id)}>
                    ⏭ End turn
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="panel actions">
              <b>{state.current}</b> is thinking…
              <button className="primary" disabled={busy} onClick={() => run(() => setState(engine.advance()))}>
                ▶ Continue
              </button>
            </div>
          )}

          {state.eval_graph.length > 1 && (
            <EvalGraph
              evalGraph={state.eval_graph}
              players={state.colors.map((c) => ({ color: c }))}
              step={state.eval_graph.length - 1}
              onJump={() => {}}
            />
          )}
        </section>

        <section className="right">
          {/* players */}
          <div className="playersbox">
            {state.board.players.map((p) => (
              <div key={p.color} className={`prow ${p.color === state.current ? "cur" : ""}`}>
                <PlayerChip color={p.color} />
                {p.color === me && <span className="youtag">you</span>}
                <span className="pstat">{p.vp} VP</span>
                <span className="pstat">🂠 {p.resources}</span>
                <span className="pstat">🃏 {p.dev_cards}</span>
                {p.has_longest_road && <span className="pstat" title="Longest Road">🛣️</span>}
                {p.has_largest_army && <span className="pstat" title="Largest Army">⚔️</span>}
                <span className="pwp">{pct(state.wp[p.color])}</span>
              </div>
            ))}
          </div>

          {/* hand */}
          <div className="handbox">
            <h4>Your hand · {state.hand.actual_vp} VP</h4>
            <div className="handrow">
              {Object.entries(state.hand.resources).map(([r, n]) => (
                <span key={r} className={`rescard ${n === 0 ? "zero" : ""}`}>
                  {RES_ICON[r]} {n}
                </span>
              ))}
            </div>
            <div className="handrow">
              {Object.entries(state.hand.dev_cards).filter(([, n]) => n > 0).map(([d, n]) => (
                <span key={d} className="devcard">🃏 {DEV_NAME[d]} ×{n}</span>
              ))}
              {state.hand.played_knights > 0 && (
                <span className="devcard played">⚔️ {state.hand.played_knights} knight{state.hand.played_knights > 1 ? "s" : ""} played</span>
              )}
            </div>
          </div>

          {/* event feed */}
          <div className="feedbox">
            <h4>Game feed</h4>
            {state.feed.slice().reverse().map((f, i) => (
              <div key={i} className={`fitem ${f.kind}`}>
                <PlayerChip color={f.actor} />
                <span className="ftext">{f.text}</span>
                {f.label && (
                  <span className="flabel" style={{ color: (LABEL_STYLE[f.label] || {}).color }}>
                    {(LABEL_STYLE[f.label] || {}).glyph}
                  </span>
                )}
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* feedback modal — the learning moment */}
      {feedback && (
        <div className="overlay">
          <div className="fbmodal">
            <div className="dhead">
              <LabelBadge label={feedback.label} big />
              {feedback.low_confidence && <span className="lowconf">low confidence</span>}
            </div>
            <div className="action">{feedback.action_text}</div>
            <p className="annotation">{feedback.annotation}</p>
            {feedback.best_action_text && (
              <div className="best">Engine suggests: <b>{feedback.best_action_text}</b></div>
            )}
            <div className="fbbtns">
              <button onClick={onTakeBack} disabled={busy}>↩ Take it back</button>
              <button className="primary" onClick={onContinue} disabled={busy}>Continue ▸</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
