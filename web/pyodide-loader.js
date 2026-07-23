// In-browser coloring engine for the static (GitHub Pages) build.
//
// GitHub Pages serves only static files, so there is no `/api/color` backend.
// When ESCHER_STATIC is set (see config.js) this loader boots Pyodide, loads
// shapely, mounts the `escher` package sources, and exposes window.escherColor
// — a drop-in replacement for the POST /api/color fetch. The GPU-only artwork
// generator has no static counterpart, so its controls are hidden.
//
// On the FastAPI server ESCHER_STATIC is false and this file is a no-op.

(() => {
  if (!window.ESCHER_STATIC) return;

  const PYODIDE_VERSION = "v0.26.4";
  const PYODIDE_URL =
    `https://cdn.jsdelivr.net/pyodide/${PYODIDE_VERSION}/full/`;

  // The coloring pipeline only. generate.py and raster.py need PIL/torch and
  // are deliberately excluded — they have no static counterpart.
  const MODULES = [
    "__init__.py",
    "lattice.py",
    "periods.py",
    "forbidden.py",
    "bigtile.py",
    "coloring.py",
    "tile.py",
    "api.py",
  ];

  function setStatus(text) {
    const el = document.getElementById("status");
    if (el) el.textContent = text;
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.onload = resolve;
      script.onerror = () => reject(new Error(`failed to load ${src}`));
      document.head.appendChild(script);
    });
  }

  async function boot() {
    setStatus("loading in-browser coloring engine…");
    await loadScript(PYODIDE_URL + "pyodide.js");
    const pyodide = await window.loadPyodide({ indexURL: PYODIDE_URL });

    setStatus("loading shapely…");
    await pyodide.loadPackage("shapely");

    setStatus("mounting the coloring algorithm…");
    pyodide.FS.mkdir("escher");
    const sources = await Promise.all(
      MODULES.map((name) =>
        fetch(`escher/${name}`).then((response) => {
          if (!response.ok) {
            throw new Error(`failed to fetch escher/${name}`);
          }
          return response.text();
        })
      )
    );
    MODULES.forEach((name, index) => {
      pyodide.FS.writeFile(`escher/${name}`, sources[index]);
    });

    // A single translation glue that mirrors server/main.py's error contract:
    // a bad tile becomes a user-facing detail rather than a crash.
    pyodide.runPython(`
import json
from escher.api import color_response


def _escher_color(payload_json):
    payload = json.loads(payload_json)
    try:
        result = color_response(
            payload["grid"], payload["pieces"], payload["diagonal"]
        )
        return json.dumps({"ok": True, "result": result})
    except ValueError as error:
        return json.dumps({"ok": False, "detail": str(error)})
`);

    setStatus("");
    return pyodide;
  }

  const ready = boot();

  window.escherColor = async (payload) => {
    const pyodide = await ready;
    pyodide.globals.set("_payload_json", JSON.stringify(payload));
    const out = pyodide.runPython("_escher_color(_payload_json)");
    return JSON.parse(out);
  };

  // The artwork generator is GPU-only; there is no static equivalent, so hide
  // its controls. This script tag sits after the markup, so the elements
  // already exist; a DOMContentLoaded fallback covers any load-order surprise.
  function hideGenerator() {
    const controls = document.getElementById("generate-controls");
    if (controls) controls.hidden = true;
    const result = document.getElementById("gen-result");
    if (result) result.hidden = true;
    const genStatus = document.getElementById("gen-status");
    if (genStatus) {
      genStatus.textContent =
        "Artwork generation needs a GPU backend and is unavailable in this " +
        "static build; run the FastAPI server locally to enable it.";
    }
  }

  hideGenerator();
  document.addEventListener("DOMContentLoaded", hideGenerator);
})();
