import React, { useState } from "react";
import ReviewApp from "./ReviewApp.jsx";
import PlayApp from "./PlayApp.jsx";
import { PLAYER_COLORS, playerColor, PLAYER_TEXT } from "./theme.js";

async function loadSampleReview() {
  const r = await fetch(`${import.meta.env.BASE_URL}sample.review.json`);
  if (!r.ok) throw new Error("Could not load the sample review.");
  return await r.json();
}

export default function App() {
  const [mode, setMode] = useState("home"); // home | play | review
  const [review, setReview] = useState(null);
  const [subtitle, setSubtitle] = useState(null);
  const [playOpts, setPlayOpts] = useState(null);
  const [err, setErr] = useState(null);

  // home-screen options
  const [color, setColor] = useState("RED");
  const [players, setPlayers] = useState(4);

  const goHome = () => { setMode("home"); setReview(null); setErr(null); };

  if (mode === "play") {
    return (
      <PlayApp
        options={playOpts}
        onHome={goHome}
        onFinish={(rev) => {
          setReview(rev);
          setSubtitle("Your game");
          setMode("review");
        }}
      />
    );
  }

  if (mode === "review" && review) {
    return <ReviewApp review={review} onHome={goHome} subtitle={subtitle} />;
  }

  const colorChoices = Object.keys(PLAYER_COLORS).slice(0, players);

  return (
    <div className="app home">
      <header className="homehead">
        <div className="title">♟ Catan Review</div>
        <p className="tagline">
          Play Settlers of Catan against the engine and learn from every move —
          instant <b>Best / Book / Mistake / Blunder</b> feedback, take-backs,
          a live win-probability chart, and a full chess.com-style game review
          at the end.
        </p>
      </header>

      <div className="homegrid">
        <div className="homecard">
          <h3>▶ Play a game</h3>
          <div className="optrow">
            <span>You play</span>
            {colorChoices.map((c) => (
              <button
                key={c}
                className={`colorpick ${color === c ? "on" : ""}`}
                style={{ background: playerColor(c), color: PLAYER_TEXT[c] || "#fff" }}
                onClick={() => setColor(c)}
              >
                {c}
              </button>
            ))}
          </div>
          <div className="optrow">
            <span>Players</span>
            {[3, 4].map((n) => (
              <button key={n} className={`pick ${players === n ? "on" : ""}`}
                onClick={() => { setPlayers(n); if (n === 3 && color === "WHITE") setColor("RED"); }}>
                {n}
              </button>
            ))}
          </div>
          <button
            className="primary big"
            onClick={() => {
              setPlayOpts({
                seed: 1 + Math.floor(Math.random() * 1_000_000),
                color,
                players,
              });
              setMode("play");
            }}
          >
            Play vs bots
          </button>
          <p className="muted">
            Every decision is graded as you play. You can take a move back after
            seeing its label — this app is for learning.
          </p>
        </div>

        <div className="homecard">
          <h3>📊 Watch a reviewed game</h3>
          <p className="muted">
            A complete bot-vs-bot game analyzed with the deep engine (Monte-Carlo
            rollouts with confidence intervals).
          </p>
          <button
            className="primary big"
            onClick={async () => {
              try {
                setSubtitle("Sample game (deep analysis)");
                setReview(await loadSampleReview());
                setMode("review");
              } catch (e) {
                setErr(String(e));
              }
            }}
          >
            Open sample review
          </button>
          {err && <p className="fatal">{err}</p>}
        </div>
      </div>

      <footer className="homefoot">
        Win probabilities are honest estimates (value model in play, Monte-Carlo
        rollouts in the sample review) — labels within the engine's error margin
        are marked low-confidence. The engine sees the full state (perfect
        information); hidden hands are not yet modeled.
      </footer>
    </div>
  );
}
