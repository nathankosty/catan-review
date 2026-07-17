// Pyodide bridge — the real Python rules engine + value model, in the browser.
//
// Why: the deploy is a static site (no backend), but live play needs full rule
// fidelity. Rather than re-implementing Catan in JS (high bug risk), we run the
// exact same tested Python package under WASM. The value model gives instant
// move evaluation (~15 ms/step measured), so feedback feels immediate.
//
// The Python sources are bundled as raw strings at build time (single source
// of truth with the backend package); catanatron + networkx install from
// vendored wheels served by this site (no PyPI at runtime).

import initPy from "../../catan_review/__init__.py?raw";
import enginePy from "../../catan_review/engine.py?raw";
import policyPy from "../../catan_review/policy.py?raw";
import quickevalPy from "../../catan_review/quickeval.py?raw";
import classifierPy from "../../catan_review/classifier.py?raw";
import annotatePy from "../../catan_review/annotate.py?raw";
import gamelogPy from "../../catan_review/gamelog.py?raw";
import webplayPy from "../../catan_review/webplay.py?raw";

const PYODIDE_CDN = "https://cdn.jsdelivr.net/pyodide/v314.0.2/full/";
const WHEELS = [
  "networkx-3.6.1-py3-none-any.whl",
  "catanatron-3.2.1-py3-none-any.whl",
];
const MODULES = {
  "__init__.py": initPy,
  "engine.py": enginePy,
  "policy.py": policyPy,
  "quickeval.py": quickevalPy,
  "classifier.py": classifierPy,
  "annotate.py": annotatePy,
  "gamelog.py": gamelogPy,
  "webplay.py": webplayPy,
};

let _py = null;
let _initPromise = null;

async function _init(onProgress = () => {}) {
  onProgress("Loading Python runtime…");
  const { loadPyodide } = await import(/* @vite-ignore */ `${PYODIDE_CDN}pyodide.mjs`);
  const py = await loadPyodide({ indexURL: PYODIDE_CDN });

  onProgress("Installing the Catan rules engine…");
  await py.loadPackage("micropip");
  const micropip = py.pyimport("micropip");
  const base = new URL(import.meta.env.BASE_URL, window.location.href).href;
  for (const w of WHEELS) {
    await micropip.install(`${base}wheels/${w}`, { deps: false });
  }

  onProgress("Loading the review engine…");
  py.FS.mkdirTree("/app/catan_review");
  for (const [name, src] of Object.entries(MODULES)) {
    py.FS.writeFile(`/app/catan_review/${name}`, src);
  }
  py.runPython(`import sys; sys.path.insert(0, "/app")\nfrom catan_review import webplay`);

  onProgress("Loading the value model…");
  const model = await fetch(`${import.meta.env.BASE_URL}value_model.json`);
  if (!model.ok) throw new Error("could not load value_model.json");
  py.globals.set("MODEL_JSON", await model.text());

  _py = py;
  return py;
}

export function initEngine(onProgress) {
  if (!_initPromise) _initPromise = _init(onProgress);
  return _initPromise;
}

const call = (expr) => JSON.parse(_py.runPython(expr));

export const engine = {
  ready: () => _py !== null,
  startSession: ({ seed, color, players }) =>
    call(`webplay.start_session(MODEL_JSON, ${Number(seed)}, "${color}", ${Number(players)})`),
  geometry: () => call("webplay.get_geometry()"),
  state: () => call("webplay.get_state()"),
  submit: (id) => call(`webplay.submit_action(${Number(id)})`),
  advance: () => call("webplay.advance()"),
  takeBack: () => call("webplay.take_back()"),
  hint: () => call("webplay.hint()"),
  finalReview: () => call("webplay.final_review()"),
};
