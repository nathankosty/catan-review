import React, { useEffect, useRef, useState } from "react";
import Board from "./Board.jsx";
import EvalGraph from "./EvalGraph.jsx";
import { LABEL_STYLE, LABEL_ORDER, playerColor, PLAYER_TEXT } from "./theme.js";

const pct = (v) => `${Math.round((v ?? 0) * 100)}%`;

export function PlayerChip({ color }) {
  return (
    <span className="chip" style={{ background: playerColor(color), color: PLAYER_TEXT[color] || "#fff" }}>
      {color}
    </span>
  );
}

export function LabelBadge({ label, big }) {
  const s = LABEL_STYLE[label] || LABEL_STYLE.Good;
  return (
    <span className={`label ${big ? "big" : ""}`} style={{ color: s.color, borderColor: s.color }}>
      <span className="glyph">{s.glyph}</span> {label}
    </span>
  );
}

// The chess.com-style walkthrough of a finished game (imported sample or the
// game you just played). Pure display over the review JSON schema.
export default function ReviewApp({ review, onHome, subtitle }) {
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [filter, setFilter] = useState(null);
  const timer = useRef(null);

  const timeline = review?.timeline || [];
  const evalGraph = review?.eval_graph || [];
  const players = review?.players || [];
  const lastStep = timeline.length; // final frame index
  const humanColor = review?.config?.human;

  useEffect(() => {
    if (!playing) return;
    timer.current = setInterval(() => {
      setStep((s) => {
        if (s >= lastStep) { setPlaying(false); return s; }
        return s + 1;
      });
    }, 700);
    return () => clearInterval(timer.current);
  }, [playing, lastStep]);

  const atFinal = step >= timeline.length;
  const entry = atFinal ? null : timeline[step];
  const frame = atFinal ? review.final_frame?.board : entry?.board;
  const presentLabels = LABEL_ORDER.filter((l) => timeline.some((t) => t.classification.label === l));

  return (
    <div className="app">
      <header>
        <div className="titlerow">
          <div className="title">Catan Review</div>
          {onHome && <button className="linkbtn" onClick={onHome}>Home</button>}
        </div>
        <div className="sub">
          {subtitle || "Game review"} · winner <PlayerChip color={review.winner} /> ·{" "}
          {review.num_turns} turns
          {humanColor && <> · you played <PlayerChip color={humanColor} /></>}
          {review.meta?.takebacks > 0 && <> · {review.meta.takebacks} take-back{review.meta.takebacks > 1 ? "s" : ""}</>}
        </div>
        {review.meta?.disclaimer && (
          <div className="disclaimer" title={review.meta.disclaimer}>
            {review.meta.disclaimer}
          </div>
        )}
      </header>

      <div className="layout">
        <section className="left">
          <Board geometry={review.geometry} frame={frame} />

          <div className="controls">
            <button onClick={() => setStep(0)} title="First move">«</button>
            <button onClick={() => setStep((s) => Math.max(0, s - 1))} title="Previous move">‹</button>
            <button className="play" onClick={() => setPlaying((p) => !p)}>
              {playing ? "Pause" : "Play"}
            </button>
            <button onClick={() => setStep((s) => Math.min(lastStep, s + 1))} title="Next move">›</button>
            <button onClick={() => setStep(lastStep)} title="Last move">»</button>
            <input
              type="range" min={0} max={lastStep} value={step}
              onChange={(e) => setStep(Number(e.target.value))}
            />
            <span className="stepno">
              {atFinal ? "end" : `move ${step + 1}/${timeline.length}`}
            </span>
          </div>

          <EvalGraph evalGraph={evalGraph} players={players} step={step} onJump={setStep} />

          {atFinal ? (
            <div className="panel final">
              <h3>Game over</h3>
              <p><PlayerChip color={review.winner} /> wins on turn {review.final_frame?.turn}.</p>
            </div>
          ) : (
            <div className="panel decision">
              <div className="dhead">
                <LabelBadge label={entry.classification.label} big />
                {entry.classification.low_confidence && <span className="lowconf">low confidence</span>}
                <span className="spacer" />
                <PlayerChip color={entry.actor} />
                <span className="turn">turn {entry.turn} · {entry.phase}</span>
              </div>
              <div className="action">{entry.action.text}</div>
              <div className="wprow">
                <span>WP for {entry.actor}: <b>{pct(entry.wp_after[entry.actor])}</b></span>
                <span className="muted">
                  top move ~{pct(entry.classification.best_wp)} · gave up{" "}
                  {pct(entry.classification.eff_loss)} (±{pct(entry.classification.ci_loss)})
                </span>
              </div>
              {entry.classification.best_action_text && (
                <div className="best">Engine suggests: <b>{entry.classification.best_action_text}</b></div>
              )}
              <p className="annotation">{entry.annotation}</p>
            </div>
          )}
        </section>

        <section className="right">
          <div className="filters">
            <button className={!filter ? "on" : ""} onClick={() => setFilter(null)}>All</button>
            {humanColor && (
              <button className={filter === "__me" ? "on" : ""} onClick={() => setFilter("__me")}>
                my moves
              </button>
            )}
            {presentLabels.map((l) => (
              <button key={l} className={filter === l ? "on" : ""} onClick={() => setFilter(l)}
                style={{ color: LABEL_STYLE[l].color }}>
                {LABEL_STYLE[l].glyph} {timeline.filter((t) => t.classification.label === l).length}
              </button>
            ))}
          </div>
          <div className="movelist">
            {timeline
              .filter((t) => !filter || (filter === "__me" ? t.actor === humanColor : t.classification.label === filter))
              .map((t) => {
                const s = LABEL_STYLE[t.classification.label] || LABEL_STYLE.Good;
                return (
                  <div key={t.step}
                    className={`move ${t.step === step ? "cur" : ""} ${t.actor === humanColor ? "mine" : ""}`}
                    onClick={() => setStep(t.step)}>
                    <span className="mvnum">{t.step + 1}</span>
                    <span className="mvglyph" style={{ color: s.color }}>{s.glyph}</span>
                    <PlayerChip color={t.actor} />
                    <span className="mvtext">{t.action.text}</span>
                  </div>
                );
              })}
          </div>
        </section>
      </div>

      <div className="bottom">
        <section className="cards">
          <h3>Player report cards</h3>
          <div className="cardrow">
            {Object.values(review.report_cards).map((rc) => (
              <div key={rc.color} className={`card ${rc.is_winner ? "winner" : ""} ${rc.color === humanColor ? "me" : ""}`}>
                <div className="cardhead">
                  <PlayerChip color={rc.color} />
                  {rc.color === humanColor && <span className="youtag">you</span>}
                  {rc.is_winner && <span className="youtag">winner</span>}
                  <span className="acc">{rc.accuracy}%</span>
                </div>
                <div className="acclabel">accuracy · {rc.decisions} decisions</div>
                <div className="labelcounts">
                  {LABEL_ORDER.filter((l) => rc.label_counts[l]).map((l) => (
                    <span key={l} className="lc" style={{ color: LABEL_STYLE[l].color }}>
                      {LABEL_STYLE[l].glyph} {rc.label_counts[l]}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="critical">
          <h3>Critical moments</h3>
          {review.critical_moments.map((m, i) => (
            <div key={i} className="crit" onClick={() => setStep(m.step)}>
              <LabelBadge label={m.label} />
              <span className="muted">T{m.turn} {m.actor} · −{pct(m.wp_loss)}</span>
              <div className="critnote">{m.annotation}</div>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
