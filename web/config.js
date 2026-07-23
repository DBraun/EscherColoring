// Deployment flag. The FastAPI server ships this file as-is, so the demo talks
// to its `/api/color` and `/api/generate` backend. The GitHub Pages build
// overwrites it to set ESCHER_STATIC = true, which switches the app to the
// in-browser coloring engine (Pyodide) and hides the GPU-only generator.
window.ESCHER_STATIC = false;
