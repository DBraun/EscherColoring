"use strict";

/* ---------------------------------------------------------------- state */

const state = {
  grid: 6,
  pieces: [],        // closed pieces: arrays of [x, y] grid vertices
  drawing: [],       // vertices of the piece being drawn
  hover: null,       // snapped grid point under the cursor
  hoverVertex: null, // {piece, vertex} of a draggable vertex under the cursor
  dragging: null,    // {piece, vertex, moved} while dragging a vertex
  suppressClick: false, // swallow the click that ends a real vertex drag
  result: null,      // last successful /api/color response
  stale: false,      // tile edited since `result` was computed
  error: "",
  diagonal: true,    // corner contact between diagonal tiles connects
  highlight: null,   // piece index located from the piece list, or null
  weave: {},         // "i,j" -> piece index drawn on top at that crossing
  regionPrompts: {}, // color index -> per-class prompt fragment
  background: "#ffffff",
  backgroundPrompt: "",
  rails: true,       // draw ribbon outlines in the wallpaper view
  palette: {},       // color index -> user-picked hex, overriding the default
};

const editor = document.getElementById("editor");
const wallpaper = document.getElementById("wallpaper");
const ectx = editor.getContext("2d");
const wctx = wallpaper.getContext("2d");

const EDGE = 560;          // logical canvas size
const MARGIN = 80;         // ghost band around the unit tile in the editor
const TILE = EDGE - 2 * MARGIN;

// Render at the device pixel ratio so lines stay crisp on scaled displays.
const DPR = window.devicePixelRatio || 1;
for (const canvas of [editor, wallpaper]) {
  canvas.width = EDGE * DPR;
  canvas.height = EDGE * DPR;
}

const INK = "#1b2430";
const GRID_LINE = "#c3cedb";
const REGISTRATION = "#c22e1f";

/* ------------------------------------------------------------- palette */

// Red, green, blue for the first three color classes; golden-angle hues for
// any beyond.  Users can override any class with the readout color pickers.
const DEFAULT_PALETTE = ["#ff0000", "#008000", "#0000ff"];

function defaultPaletteHex(index) {
  if (index < DEFAULT_PALETTE.length) return DEFAULT_PALETTE[index];
  const hue = (150 + index * 137.508) % 360;
  const f = (n) => {
    const k = (n + hue / 30) % 12;
    const c = 0.52 - 0.62 * Math.min(0.52, 0.48) * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(255 * c).toString(16).padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

function paletteColor(index) {
  return state.palette[index] || defaultPaletteHex(index);
}

function pieceFillAt(piece, tileX, tileY) {
  const result = state.result;
  if (result && result.colors[piece] !== undefined) {
    const bh = result.bigHeight;
    const bw = result.bigWidth;
    const row = ((tileY % bh) + bh) % bh;
    const col = ((tileX % bw) + bw) % bw;
    return paletteColor(result.colors[piece][row][col]);
  }
  return "#9aa5b1";
}

function pieceFill(piece) {
  return pieceFillAt(piece, 0, 0);
}

// Coalesce rapid updates (color-picker drags) to one render per frame.
let renderQueued = false;
function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    renderEditor();
    renderWallpaper();
    renderPieceList();
  });
}

/* --------------------------------------------------------------- weave */

// A crossing is one overlap region between pieces i and j; a pair may cross
// more than once, so k indexes the region and each is woven independently.
function weaveKey(i, j, k) {
  const [a, b] = i < j ? [i, j] : [j, i];
  return `${a},${b},${k}`;
}

function weaveWinner(i, j, k) {
  const key = weaveKey(i, j, k);
  if (key in state.weave) return state.weave[key];
  const [a, b] = i < j ? [i, j] : [j, i];
  return (a + b) % 2 === 0 ? b : a;
}

function polygonCentroid(poly) {
  let x = 0;
  let y = 0;
  for (const [px, py] of poly) {
    x += px;
    y += py;
  }
  return [x / poly.length, y / poly.length];
}

// Carry per-crossing over/under choices across a recompute.  The region
// index k within a pair follows the geometry library's enumeration order,
// which can shuffle when a vertex moves even though the weave topology is
// unchanged; match each overridden old region to the nearest new region of
// the same pair (one-to-one) instead of trusting k.  Overrides whose old
// region is unknown (e.g. a tile just loaded from a link, file, or preset,
// where the keys already describe the new tile) pass through untouched.
function remapWeave(oldCrossings, newCrossings) {
  const remapped = {};
  const pairs = new Map();
  for (const [key, winner] of Object.entries(state.weave)) {
    const [a, b, k] = key.split(",").map(Number);
    const old = oldCrossings.find((c) => c.i === a && c.j === b && c.k === k);
    if (!old) {
      remapped[key] = winner;
      continue;
    }
    const pairKey = `${a},${b}`;
    if (!pairs.has(pairKey)) pairs.set(pairKey, []);
    pairs.get(pairKey).push({ old, winner });
  }
  for (const [pairKey, overrides] of pairs) {
    const [a, b] = pairKey.split(",").map(Number);
    const fresh = newCrossings.filter((c) => c.i === a && c.j === b);
    // All (override, new region) centroid distances, closest first; each
    // side is claimed at most once, so two overrides cannot land on the
    // same region.
    const options = [];
    overrides.forEach((override, index) => {
      const [ox, oy] = polygonCentroid(override.old.poly);
      for (const cross of fresh) {
        const [nx, ny] = polygonCentroid(cross.poly);
        const d = (nx - ox) ** 2 + (ny - oy) ** 2;
        options.push([d, index, cross.k]);
      }
    });
    options.sort((p, q) => p[0] - q[0]);
    const takenOverride = new Set();
    const takenRegion = new Set();
    for (const [, index, k] of options) {
      if (takenOverride.has(index) || takenRegion.has(k)) continue;
      takenOverride.add(index);
      takenRegion.add(k);
      remapped[weaveKey(a, b, k)] = overrides[index].winner;
    }
  }
  return remapped;
}

// Trace only the edges that are real ribbon rails: segments lying along the
// tile border are internal seams of a ribbon continuing into the neighbor
// tile and must not be outlined.
function traceInteriorEdges(ctx, piece, map) {
  const g = state.grid;
  const onBorder = (a, b) =>
    (a[0] === 0 && b[0] === 0) || (a[0] === g && b[0] === g) ||
    (a[1] === 0 && b[1] === 0) || (a[1] === g && b[1] === g);
  ctx.beginPath();
  for (let k = 0; k < piece.length; k++) {
    const a = piece[k];
    const b = piece[(k + 1) % piece.length];
    if (onBorder(a, b)) continue;
    const [xa, ya] = map(a);
    const [xb, yb] = map(b);
    ctx.moveTo(xa, ya);
    ctx.lineTo(xb, yb);
  }
}

// Paint a piece with an inner outline: the stroke is drawn at double width
// clipped to the polygon, so it never straddles the boundary.  Opaque fills
// therefore cover neighboring rails completely, which keeps the weave
// repaint free of half-stroke seams.
function paintPiece(ctx, piece, map, fill, strokeStyle, strokeWidth) {
  tracePolygon(ctx, piece, map);
  ctx.fillStyle = fill;
  ctx.fill();
  if (!strokeStyle) return;
  ctx.save();
  tracePolygon(ctx, piece, map);
  ctx.clip();
  traceInteriorEdges(ctx, piece, map);
  ctx.strokeStyle = strokeStyle;
  ctx.lineWidth = strokeWidth * 2;
  ctx.lineCap = "round";
  ctx.stroke();
  ctx.restore();
}

// Redraw each crossing region so the winning ribbon passes over: clip to the
// region, fill it with the winner's color, and redraw the winner's rails on
// top.  The same choice repeats in every unit tile, so the weave tiles
// seamlessly.
function renderWeave(ctx, map, colorOf, strokeStyle, strokeWidth) {
  if (!state.result || !state.result.crossings) return;
  const crossings = state.result.crossings.filter(
    (c) => state.pieces[c.i] && state.pieces[c.j]
  );
  const winners = crossings.map((c) => weaveWinner(c.i, c.j, c.k));

  // The region clip below is antialiased, so border pixels never reach full
  // coverage and the loser's rails would show through as a hairline.  First
  // overpaint every region's loser-contributed border edges, clipped to the
  // winner's polygon so the stroke cannot cross the winner's own outline at
  // region corners.  Strokes may land inside a neighboring region (where a
  // third piece passes over this winner); the repaint loop that follows
  // covers those, and same-color overpaints are idempotent.
  crossings.forEach((cross, n) => {
    const winner = winners[n];
    ctx.save();
    tracePolygon(ctx, state.pieces[winner], map);
    ctx.clip();
    traceCrossingSeams(ctx, cross.poly, state.pieces[winner], map);
    ctx.strokeStyle = colorOf(winner);
    ctx.lineWidth = strokeWidth * 2;
    ctx.lineCap = "butt";
    ctx.stroke();
    ctx.restore();
  });

  crossings.forEach((cross, n) => {
    const winner = winners[n];
    const color = colorOf(winner);
    ctx.save();
    tracePolygon(ctx, cross.poly, map);
    ctx.clip();
    // Fill the overlap so the winner covers the loser here.
    tracePolygon(ctx, cross.poly, map);
    ctx.fillStyle = color;
    ctx.fill();
    // Cover the antialiased seam along the region's border.
    tracePolygon(ctx, cross.poly, map);
    ctx.strokeStyle = color;
    ctx.lineWidth = strokeWidth * 2;
    ctx.lineJoin = "round";
    ctx.stroke();
    ctx.restore();
    // Redraw the winner's rails so they pass over; the loser's rails inside
    // the region stay buried under the fill.  A second pass clips to small
    // discs at the region corners (intersected with the winner's polygon):
    // a seam stroke above may have nicked the winner's base rail around a
    // corner, and the discs let the redraw repair it without letting ink
    // cross the winner's outline.  The discs are a separate clip because
    // combining them with the region in one path can cancel under the
    // nonzero winding rule and punch a hole exactly at the corner.
    if (strokeStyle) {
      const rails = () => {
        traceInteriorEdges(ctx, state.pieces[winner], map);
        ctx.strokeStyle = strokeStyle;
        ctx.lineWidth = strokeWidth * 2;
        ctx.lineCap = "round";
        ctx.stroke();
      };
      ctx.save();
      tracePolygon(ctx, cross.poly, map);
      ctx.clip();
      rails();
      ctx.restore();
      ctx.save();
      ctx.beginPath();
      const r = strokeWidth * 3;
      for (const v of cross.poly) {
        const [cx, cy] = map(v);
        ctx.moveTo(cx + r, cy);
        ctx.arc(cx, cy, r, 0, 2 * Math.PI);
      }
      ctx.clip();
      tracePolygon(ctx, state.pieces[winner], map);
      ctx.clip();
      rails();
      ctx.restore();
    }
  });
}

function pointOnSegment(p, a, b) {
  const eps = 1e-9;
  const abx = b[0] - a[0];
  const aby = b[1] - a[1];
  // A duplicate vertex makes a zero-length edge; it must not count as a
  // boundary hit (the collinearity test below is vacuous for it).
  const len2 = abx * abx + aby * aby;
  if (len2 === 0) return false;
  const apx = p[0] - a[0];
  const apy = p[1] - a[1];
  const cross = abx * apy - aby * apx;
  if (cross * cross > eps * len2) return false;
  const dot = apx * abx + apy * aby;
  return dot >= -eps && dot <= len2 + eps;
}

function onPieceBoundary(p, piece) {
  for (let k = 0; k < piece.length; k++) {
    if (pointOnSegment(p, piece[k], piece[(k + 1) % piece.length])) return true;
  }
  return false;
}

// Trace the crossing-border edges contributed by the loser's outline (the
// ones cutting across the winner's interior).  Across such an edge lies
// winner-only area of the same color, so an unclipped stroke along it is
// invisible outside the region while fully covering the border pixels.
function traceCrossingSeams(ctx, poly, winnerPiece, map) {
  ctx.beginPath();
  for (let k = 0; k < poly.length; k++) {
    const a = poly[k];
    const b = poly[(k + 1) % poly.length];
    const mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    if (onPieceBoundary(mid, winnerPiece)) continue;
    const [xa, ya] = map(a);
    const [xb, yb] = map(b);
    ctx.moveTo(xa, ya);
    ctx.lineTo(xb, yb);
  }
}

function pointInPolygon(x, y, polygon) {
  let inside = false;
  for (let a = 0, b = polygon.length - 1; a < polygon.length; b = a++) {
    const [xa, ya] = polygon[a];
    const [xb, yb] = polygon[b];
    if ((ya > y) !== (yb > y) && x < ((xb - xa) * (y - ya)) / (yb - ya) + xa) {
      inside = !inside;
    }
  }
  return inside;
}

/* ------------------------------------------------------- editor render */

function toCanvas(point) {
  const cell = TILE / state.grid;
  return [MARGIN + point[0] * cell, MARGIN + point[1] * cell];
}

function tracePolygon(ctx, vertices, map) {
  ctx.beginPath();
  vertices.forEach((v, k) => {
    const [x, y] = map(v);
    if (k === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.closePath();
}

function renderEditor() {
  ectx.setTransform(DPR, 0, 0, DPR, 0, 0);
  ectx.clearRect(0, 0, EDGE, EDGE);
  ectx.fillStyle = "#ffffff";
  ectx.fillRect(0, 0, EDGE, EDGE);

  // Ghost copies in the eight neighbor tiles: the boundary constraints.
  const offsets = [-1, 0, 1];
  for (const ox of offsets) {
    for (const oy of offsets) {
      if (ox === 0 && oy === 0) continue;
      state.pieces.forEach((piece, index) => {
        tracePolygon(ectx, piece, (v) => {
          const [x, y] = toCanvas(v);
          return [x + ox * TILE, y + oy * TILE];
        });
        // Each neighbor tile carries its own Big Tile coloring, so a ribbon
        // keeps its color as it crosses the boundary.
        ectx.fillStyle = pieceFillAt(index, ox, oy);
        ectx.globalAlpha = 0.35;
        ectx.fill();
        ectx.globalAlpha = 1;
        ectx.strokeStyle = "rgba(27, 36, 48, 0.35)";
        ectx.lineWidth = 1;
        ectx.stroke();
      });
    }
  }

  // Grid.
  const cell = TILE / state.grid;
  ectx.strokeStyle = "#8fa2b8";
  ectx.lineWidth = 1;
  for (let k = 0; k <= state.grid; k++) {
    ectx.beginPath();
    ectx.moveTo(MARGIN + k * cell, MARGIN);
    ectx.lineTo(MARGIN + k * cell, MARGIN + TILE);
    ectx.moveTo(MARGIN, MARGIN + k * cell);
    ectx.lineTo(MARGIN + TILE, MARGIN + k * cell);
    ectx.stroke();
  }

  // Pieces, filled with their computed color at Big Tile location (0, 0).
  // While a piece is located from the list, the others fade back.
  state.pieces.forEach((piece, index) => {
    ectx.globalAlpha =
      state.highlight === null || state.highlight === index ? 1 : 0.25;
    paintPiece(ectx, piece, toCanvas, pieceFill(index), INK, 1.5);
    ectx.globalAlpha = 1;
  });
  // Weave the crossings (skip while a piece is being located, so the
  // highlight fade stays readable).  Stale crossings — the tile was edited
  // and the recompute has not landed — are normally hidden because the
  // regions would draw at the wrong places; during a drag the freshest
  // crossings are at most one grid snap (~20 ms) behind, so keep weaving
  // rather than flash the unwoven paint order.
  if (state.highlight === null && (!state.stale || state.dragging)) {
    renderWeave(ectx, toCanvas, pieceFill, INK, 1.5);
  }

  if (state.highlight !== null && state.pieces[state.highlight]) {
    tracePolygon(ectx, state.pieces[state.highlight], toCanvas);
    ectx.strokeStyle = REGISTRATION;
    ectx.lineWidth = 3;
    ectx.stroke();
  }

  // Tile boundary above the fills.
  ectx.strokeStyle = INK;
  ectx.lineWidth = 2;
  ectx.strokeRect(MARGIN, MARGIN, TILE, TILE);

  // Draggable vertex handles on the finished pieces (hidden while drawing a
  // new one, to keep the draw preview uncluttered).  The one under the cursor
  // or being dragged is emphasized.
  if (state.drawing.length === 0) {
    const active = state.dragging || state.hoverVertex;
    state.pieces.forEach((piece, pi) => {
      piece.forEach((vertex, vi) => {
        const [x, y] = toCanvas(vertex);
        const hot = active && active.piece === pi && active.vertex === vi;
        ectx.beginPath();
        ectx.rect(x - 3, y - 3, 6, 6);
        ectx.fillStyle = hot ? REGISTRATION : "#ffffff";
        ectx.fill();
        ectx.strokeStyle = hot ? REGISTRATION : INK;
        ectx.lineWidth = 1.5;
        ectx.stroke();
      });
    });
  }

  // Piece being drawn.
  if (state.drawing.length > 0) {
    ectx.beginPath();
    state.drawing.forEach((v, k) => {
      const [x, y] = toCanvas(v);
      if (k === 0) ectx.moveTo(x, y);
      else ectx.lineTo(x, y);
    });
    if (state.hover) {
      const [hx, hy] = toCanvas(state.hover);
      ectx.lineTo(hx, hy);
    }
    ectx.strokeStyle = REGISTRATION;
    ectx.lineWidth = 2;
    ectx.stroke();
    for (const v of state.drawing) {
      const [x, y] = toCanvas(v);
      ectx.beginPath();
      ectx.arc(x, y, 4, 0, 2 * Math.PI);
      ectx.fillStyle = REGISTRATION;
      ectx.fill();
    }
  }

  // Snap indicator.
  if (state.hover && !state.dragging) {
    const [x, y] = toCanvas(state.hover);
    ectx.beginPath();
    ectx.arc(x, y, 5, 0, 2 * Math.PI);
    ectx.strokeStyle = REGISTRATION;
    ectx.lineWidth = 1.5;
    ectx.stroke();
  }
}

/* ---------------------------------------------------- wallpaper render */

function renderWallpaper() {
  wctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  wctx.clearRect(0, 0, EDGE, EDGE);
  wctx.fillStyle = state.background;
  wctx.fillRect(0, 0, EDGE, EDGE);
  const result = state.result;
  if (!result || state.pieces.length === 0) return;

  const bigW = result.bigWidth;
  const bigH = result.bigHeight;
  const tiles = Math.min(24, Math.max(8, 2 * Math.max(bigW, bigH)));
  const cell = EDGE / tiles;
  // Snap tile borders to whole device pixels.  Neighboring fills then meet
  // exactly on a pixel boundary; a border inside a pixel gets only partial
  // coverage from each side and shows as a light hairline (any zoom or
  // devicePixelRatio where cell * DPR is fractional).
  const border = (t) => Math.round(t * cell * DPR) / DPR;

  // Rails are opaque ink; the weave repaint can redraw them without
  // artifacts because all strokes are idempotent.  Null hides the rails.
  const rail = state.rails ? INK : null;
  for (let ty = 0; ty < tiles; ty++) {
    const y0 = border(ty);
    const y1 = border(ty + 1);
    for (let tx = 0; tx < tiles; tx++) {
      const x0 = border(tx);
      const x1 = border(tx + 1);
      const map = (v) => [
        x0 + (v[0] / state.grid) * (x1 - x0),
        y0 + (v[1] / state.grid) * (y1 - y0),
      ];
      state.pieces.forEach((piece, index) => {
        const grid = result.colors[index];
        if (!grid) return;  // result is stale while a recompute is in flight
        const colorIndex = grid[ty % bigH][tx % bigW];
        paintPiece(wctx, piece, map, paletteColor(colorIndex), rail, 0.75);
      });
      if (!state.stale) {
        renderWeave(wctx, map, (p) => pieceFillAt(p, tx, ty), rail, 0.75);
      }
    }
  }

  // Big Tile registration outline.
  wctx.strokeStyle = REGISTRATION;
  wctx.lineWidth = 3;
  wctx.strokeRect(0, 0, bigW * cell, bigH * cell);
}

/* -------------------------------------------------------------- readout */

function periodType(naturalCount) {
  return ["trivially periodic", "singly periodic", "doubly periodic"][naturalCount];
}

function fmtVecs(vectors) {
  if (vectors.length === 0) return "—";
  return vectors.map(v => `(${v[0]}, ${v[1]})`).join("  ");
}

function renderReadout() {
  const readout = document.getElementById("readout");
  readout.innerHTML = "";
  const add = (term, detail) => {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = detail;
    readout.append(dt, dd);
  };
  const result = state.result;
  if (!result || state.pieces.length === 0) {
    add("status", "draw a motif piece to begin");
    return;
  }
  add("pieces", String(state.pieces.length));
  add("connections", String(result.connections.length));
  add("overlaps", String(result.overlaps.length));
  result.components.forEach((comp, index) => {
    add(
      `component ${index + 1}`,
      `pieces {${comp.pieces.join(", ")}} · ${periodType(comp.natural.length)}` +
      ` · natural ${fmtVecs(comp.natural)} · lattice ${fmtVecs(comp.basis)}` +
      ` · Big Tile ${comp.width}×${comp.height} · ${comp.colors} color${comp.colors > 1 ? "s" : ""}`
    );
  });
  add("big tile", `${result.bigWidth} × ${result.bigHeight} unit tiles`);
  const dt = document.createElement("dt");
  dt.textContent = "palette";
  const dd = document.createElement("dd");
  for (let k = 0; k < result.paletteSize; k++) {
    const picker = document.createElement("input");
    picker.type = "color";
    picker.value = paletteColor(k);
    picker.title = `color ${k + 1} — pick your own`;
    picker.addEventListener("input", () => {
      state.palette[k] = picker.value;
      scheduleRender();
      syncURL();
    });
    const fragment = document.createElement("input");
    fragment.type = "text";
    fragment.size = 14;
    fragment.placeholder = `color ${k + 1} prompt…`;
    fragment.value = state.regionPrompts[k] || "";
    fragment.title = "Optional prompt fragment applied only to this color's ribbons";
    fragment.addEventListener("input", () => {
      state.regionPrompts[k] = fragment.value;
    });
    dd.append(picker, fragment);
  }
  readout.append(dt, dd);
}

function renderPieceList() {
  const list = document.getElementById("piece-list");
  list.innerHTML = "";
  state.pieces.forEach((piece, index) => {
    const item = document.createElement("li");
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = pieceFill(index);
    const label = document.createElement("span");
    label.textContent = `m${index}`;
    const remove = document.createElement("button");
    remove.textContent = "✕";
    remove.setAttribute("aria-label", `Delete piece m${index}`);
    remove.addEventListener("click", () => {
      state.highlight = null;
      state.weave = {};
      state.pieces.splice(index, 1);
      tileChanged();
    });
    item.addEventListener("mouseenter", () => {
      state.highlight = index;
      renderEditor();
    });
    item.addEventListener("mouseleave", () => {
      state.highlight = null;
      renderEditor();
    });
    item.append(swatch, label, remove);
    list.append(item);
  });
}

function renderAll() {
  renderEditor();
  renderWallpaper();
  renderReadout();
  renderPieceList();
  document.getElementById("status").textContent = state.error;
}

/* ------------------------------------------------------------- server */

let debounceTimer = null;

function tileChanged() {
  state.stale = true;
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(recompute, 150);
  renderAll();
  syncURL();
}

// Guards against an older in-flight recompute landing after a newer one and
// clobbering it (drags fire recomputes in quick succession).
let recomputeSeq = 0;
// Coalesce bursts: at most one recompute in flight; a request that arrives
// meanwhile runs once more afterwards, reading the then-current state.
let recomputing = false;
let recomputeQueued = false;

async function recompute() {
  if (recomputing) {
    recomputeQueued = true;
    return;
  }
  recomputing = true;
  try {
    await recomputeNow();
  } finally {
    recomputing = false;
  }
  if (recomputeQueued) {
    recomputeQueued = false;
    recompute();
  }
}

async function recomputeNow() {
  const seq = ++recomputeSeq;
  if (state.pieces.length === 0) {
    state.result = null;
    state.stale = false;
    state.error = "";
    renderAll();
    return;
  }
  const payload = {
    grid: state.grid,
    pieces: state.pieces,
    diagonal: state.diagonal,
  };
  // Static (GitHub Pages) build has no backend: the coloring runs in-browser
  // via Pyodide (see pyodide-loader.js). The server build fetches /api/color.
  let outcome;
  if (window.ESCHER_STATIC) {
    outcome = await window.escherColor(payload);
  } else {
    const response = await fetch("/api/color", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    outcome = response.ok
      ? { ok: true, result: await response.json() }
      : {
          ok: false,
          detail: (
            await response.json().catch(() => ({ detail: "request failed" }))
          ).detail,
        };
  }
  if (seq !== recomputeSeq) return;  // superseded by a newer recompute
  if (outcome.ok) {
    state.weave = remapWeave(
      state.result?.crossings ?? [],
      outcome.result.crossings ?? []
    );
    state.result = outcome.result;
    state.stale = false;
    state.error = "";
  } else {
    state.error = outcome.detail;
  }
  renderAll();
  syncURL();  // palette in the URL now reflects the computed color count
}

/* -------------------------------------------------------- interaction */

// Cursor position in the editor's logical (EDGE-sized) coordinate space.
function eventCanvas(event) {
  const rect = editor.getBoundingClientRect();
  const scale = EDGE / rect.width;
  return [(event.clientX - rect.left) * scale, (event.clientY - rect.top) * scale];
}

function snapPoint(event) {
  const [px, py] = eventCanvas(event);
  const cell = TILE / state.grid;
  const gx = Math.round((px - MARGIN) / cell);
  const gy = Math.round((py - MARGIN) / cell);
  if (gx < 0 || gy < 0 || gx > state.grid || gy > state.grid) return null;
  return [gx, gy];
}

// Same snap, but clamped inside the tile so a vertex stays valid mid-drag.
function snapClamped(event) {
  const [px, py] = eventCanvas(event);
  const cell = TILE / state.grid;
  const gx = Math.max(0, Math.min(state.grid, Math.round((px - MARGIN) / cell)));
  const gy = Math.max(0, Math.min(state.grid, Math.round((py - MARGIN) / cell)));
  return [gx, gy];
}

// The existing piece vertex nearest the cursor within a grab radius, if any.
function vertexAt(event) {
  const [px, py] = eventCanvas(event);
  const grab = 12;  // logical pixels
  let best = null;
  let bestDist = grab * grab;
  state.pieces.forEach((piece, pi) => {
    piece.forEach((vertex, vi) => {
      const [vx, vy] = toCanvas(vertex);
      const d = (vx - px) ** 2 + (vy - py) ** 2;
      if (d <= bestDist) {
        bestDist = d;
        best = { piece: pi, vertex: vi };
      }
    });
  });
  return best;
}

editor.addEventListener("mousedown", (event) => {
  // A fresh interaction: clear any stale suppression from a drag released
  // outside the canvas (where no click followed to consume it).
  state.suppressClick = false;
  // Grab a vertex to drag it (only when not drawing and not flipping a
  // crossing); otherwise fall through to click-to-draw.
  if (event.shiftKey || state.drawing.length > 0) return;
  const hit = vertexAt(event);
  if (hit) {
    state.dragging = { ...hit, moved: false };
    event.preventDefault();
  }
});

editor.addEventListener("mousemove", (event) => {
  if (state.dragging) {
    const [gx, gy] = snapClamped(event);
    const vertex = state.pieces[state.dragging.piece][state.dragging.vertex];
    if (vertex[0] !== gx || vertex[1] !== gy) {
      vertex[0] = gx;
      vertex[1] = gy;
      state.dragging.moved = true;
      // Immediate recompute (the coloring takes ~20 ms in the browser), so
      // the weave stays correct through the whole drag; a debounce would
      // hide it during continuous motion, which read as crossings flipping.
      state.stale = true;
      clearTimeout(debounceTimer);
      renderEditor();
      recompute();
    }
    return;
  }
  state.hover = snapPoint(event);
  state.hoverVertex = state.drawing.length === 0 ? vertexAt(event) : null;
  editor.style.cursor = state.hoverVertex ? "move" : "crosshair";
  renderEditor();
});

window.addEventListener("mouseup", () => {
  if (!state.dragging) return;
  const moved = state.dragging.moved;
  state.dragging = null;
  if (moved) {
    state.suppressClick = true;  // don't let the trailing click start a piece
    clearTimeout(debounceTimer);
    recompute();
  }
});

editor.addEventListener("mouseleave", () => {
  state.hover = null;
  state.hoverVertex = null;
  renderEditor();
});

editor.addEventListener("click", (event) => {
  // A click that ended a vertex drag should not also start a new piece.
  if (state.suppressClick) {
    state.suppressClick = false;
    return;
  }
  if (event.shiftKey && state.drawing.length === 0 && state.result) {
    // Flip the over/under choice of the crossing under the cursor.
    const [px, py] = eventCanvas(event);
    const cell = TILE / state.grid;
    const gx = (px - MARGIN) / cell;
    const gy = (py - MARGIN) / cell;
    for (const cross of state.result.crossings || []) {
      if (pointInPolygon(gx, gy, cross.poly)) {
        const { i, j, k } = cross;
        const winner = weaveWinner(i, j, k);
        state.weave[weaveKey(i, j, k)] = winner === i ? j : i;
        renderAll();
        syncURL();
        return;
      }
    }
    return;
  }
  const point = snapPoint(event);
  if (!point) return;
  const first = state.drawing[0];
  if (state.drawing.length >= 3 && first[0] === point[0] && first[1] === point[1]) {
    state.pieces.push(state.drawing);
    state.drawing = [];
    tileChanged();
    return;
  }
  const last = state.drawing[state.drawing.length - 1];
  if (last && last[0] === point[0] && last[1] === point[1]) return;
  state.drawing.push(point);
  renderEditor();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    state.drawing = [];
    renderEditor();
  } else if (event.key === "Backspace" && state.drawing.length > 0) {
    state.drawing.pop();
    renderEditor();
    event.preventDefault();
  } else if (event.key === "Enter" && state.drawing.length >= 3) {
    state.pieces.push(state.drawing);
    state.drawing = [];
    tileChanged();
  }
});

/* ----------------------------------------------------------- controls */

document.getElementById("grid-size").addEventListener("change", (event) => {
  const value = parseInt(event.target.value, 10);
  if (Number.isNaN(value)) {
    event.target.value = String(state.grid);
    return;
  }
  state.grid = Math.max(2, Math.min(33, value));
  event.target.value = String(state.grid);
  state.pieces = [];
  state.drawing = [];
  state.weave = {};
  tileChanged();
});

document.getElementById("diagonal-conn").addEventListener("change", (event) => {
  state.diagonal = event.target.checked;
  tileChanged();
});

document.getElementById("bg-color").addEventListener("input", (event) => {
  state.background = event.target.value;
  scheduleRender();
});

document.getElementById("bg-prompt").addEventListener("input", (event) => {
  state.backgroundPrompt = event.target.value;
});

document.getElementById("rails").addEventListener("change", (event) => {
  state.rails = event.target.checked;
  renderWallpaper();
});

document.getElementById("clear").addEventListener("click", () => {
  state.pieces = [];
  state.drawing = [];
  state.weave = {};
  tileChanged();
});

const PRESETS = {
  strip: {
    grid: 6,
    pieces: [[[0, 2], [6, 2], [6, 4], [0, 4]]],
  },
  weave: {
    grid: 6,
    pieces: [
      [[0, 1], [6, 1], [6, 2], [0, 2]],
      [[1, 0], [2, 0], [2, 6], [1, 6]],
      [[0, 4], [6, 4], [6, 5], [0, 5]],
      [[4, 0], [5, 0], [5, 6], [4, 6]],
    ],
    // Flip the upper-right crossing (top strip over right strip by default)
    // so the four corners alternate into a proper over/under basket weave.
    weave: { "0,3,0": 3 },
  },
  // Two families of constant-width diagonal bands (along x-y and x+y) crossing
  // over and under: a uniform-width diagonal basket weave.  The band period
  // divides the grid, so it tiles seamlessly; both crossings sit in the tile
  // interior.  Doubly periodic, 2 colors in a 1x1 Big Tile.
  diagonal: {
    grid: 24,
    pieces: [
      [[6, 24], [16, 24], [0, 8], [0, 18]],
      [[24, 18], [24, 8], [16, 0], [6, 0]],
      [[5, 0], [0, 0], [0, 5]],
      [[24, 5], [24, 0], [19, 0], [0, 19], [0, 24], [5, 24]],
      [[19, 24], [24, 24], [24, 19]],
    ],
  },
  // Ogden's thesis tile (Figure 2.1): nine ribbon pieces, singly periodic with
  // natural period (1,3); colored with 3 colors in a 1x3 Big Tile.  Ships with
  // its tuned over/under weave.
  ogden: {
    grid: 24,
    pieces: [
      [[5, 0], [9, 0], [14, 4], [20, 0], [24, 0], [24, 0], [14, 7]],
      [[0, 0], [4, 0], [7, 10], [15, 24], [11, 24], [4, 11], [0, 0]],
      [[24, 5], [24, 8], [18, 11], [24, 16], [24, 19], [14, 11]],
      [[0, 16], [12, 9], [19, 24], [16, 24], [11, 13], [0, 19]],
      [[16, 0], [19, 0], [24, 10], [24, 13], [9, 24], [5, 24], [22, 11]],
      [[0, 10], [1, 12], [0, 13]],
      [[0, 20], [0, 24], [4, 24]],
      [[20, 24], [24, 20], [24, 24]],
      [[0, 8], [14, 2], [15, 0], [11, 0], [0, 5]],
    ],
    weave: {
      "0,8,0": 8, "1,8,0": 1, "3,4,0": 3, "2,4,1": 4,
      "1,4,0": 4, "2,4,0": 2, "0,4,0": 4, "1,3,0": 1,
    },
    palette: { 0: "#ff2929", 1: "#009400", 2: "#4d4dfe" },
  },
  fishnet: {
    grid: 24,
    pieces: [
      [[0, 3], [3, 2], [4, 0], [6, 0], [6, 2], [4, 4], [1, 5], [0, 5]],
      [[24, 3], [22, 2], [21, 1], [21, 0], [20, 0], [20, 2], [21, 3], [22, 4], [24, 5]],
      [[4, 24], [4, 23], [3, 22], [2, 21], [0, 21], [0, 19], [2, 19], [4, 20], [5, 21], [6, 23], [6, 24]],
      [[20, 24], [20, 22], [21, 20], [24, 19], [24, 21], [22, 21], [21, 24]],
      [[23, 24], [0, 1], [0, 0], [1, 0], [24, 23], [24, 24]],
      [[0, 23], [1, 24], [0, 24]],
      [[23, 0], [24, 1], [24, 0]],
      [[0, 23], [23, 0], [24, 0], [24, 1], [1, 24], [0, 24]],
    ],
    weave: { "4,7,0": 7, "3,4,0": 3, "1,7,0": 1, "2,7,0": 7 },
    palette: { 0: "#ff2929", 1: "#009400", 2: "#4d4dfe" },
  },
};

document.getElementById("preset").addEventListener("change", (event) => {
  const preset = PRESETS[event.target.value];
  if (!preset) return;
  state.grid = preset.grid;
  document.getElementById("grid-size").value = String(preset.grid);
  state.pieces = preset.pieces.map(p => p.map(v => [...v]));
  state.drawing = [];
  state.weave = { ...(preset.weave || {}) };
  // The old result describes the previous tile; drop it so the preset weave
  // keys are not remapped against the wrong regions.
  state.result = null;
  state.palette = { ...(preset.palette || {}) };
  tileChanged();
});

/* ------------------------------------------------------------ downloads */

// Paint one unit tile (pieces plus weave) with its own Big Tile coloring.
function paintTileAt(ctx, originX, originY, cellPx, tileX, tileY, strokeStyle, lw) {
  const sub = cellPx / state.grid;
  const map = (v) => [originX + v[0] * sub, originY + v[1] * sub];
  state.pieces.forEach((piece, index) => {
    paintPiece(ctx, piece, map, pieceFillAt(index, tileX, tileY), strokeStyle, lw);
  });
  renderWeave(ctx, map, (p) => pieceFillAt(p, tileX, tileY), strokeStyle, lw);
}

function downloadCanvas(canvas, name) {
  canvas.toBlob((blob) => {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = name;
    link.click();
    URL.revokeObjectURL(link.href);
  });
}

const HIRES_TILE = 2048;

document.getElementById("download-tile").addEventListener("click", () => {
  if (state.pieces.length === 0) return;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = HIRES_TILE;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = state.background;
  ctx.fillRect(0, 0, HIRES_TILE, HIRES_TILE);
  // Exports follow the live-view rails toggle.
  const rail = state.rails ? INK : null;
  paintTileAt(ctx, 0, 0, HIRES_TILE, 0, 0, rail, HIRES_TILE / 512);
  downloadCanvas(canvas, "escher-tile.png");
});

document.getElementById("download-bigtile").addEventListener("click", () => {
  if (state.pieces.length === 0 || !state.result) return;
  const bigW = state.result.bigWidth;
  const bigH = state.result.bigHeight;
  const cell = 1024;
  const canvas = document.createElement("canvas");
  canvas.width = bigW * cell;
  canvas.height = bigH * cell;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = state.background;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  const rail = state.rails ? INK : null;
  for (let ty = 0; ty < bigH; ty++) {
    for (let tx = 0; tx < bigW; tx++) {
      paintTileAt(ctx, tx * cell, ty * cell, cell, tx, ty, rail, cell / 512);
    }
  }
  downloadCanvas(canvas, `escher-big-tile-${bigW}x${bigH}.png`);
});

document.getElementById("export").addEventListener("click", () => {
  // Save the effective color of each class so the tile reloads with the same
  // palette (user overrides and defaults alike).
  const palette = state.result
    ? Array.from({ length: state.result.paletteSize }, (_, k) => paletteColor(k))
    : [];
  const blob = new Blob(
    [JSON.stringify(
      { grid: state.grid, pieces: state.pieces, weave: state.weave, palette },
      null, 2
    )],
    { type: "application/json" }
  );
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "escher-tile.json";
  link.click();
  URL.revokeObjectURL(link.href);
});

document.getElementById("import").addEventListener("click", () => {
  document.getElementById("import-file").click();
});

// Load a tile from a parsed {grid, pieces, weave, palette} object (from an
// imported file or the shareable URL).
function loadTile(data) {
  state.grid = data.grid;
  document.getElementById("grid-size").value = String(data.grid);
  state.pieces = data.pieces;
  state.drawing = [];
  state.weave = data.weave ?? {};
  // The old result describes the previous tile; drop it so the loaded weave
  // keys are not remapped against the wrong regions.
  state.result = null;
  state.palette = {};
  (data.palette ?? []).forEach((hex, k) => {
    if (hex) state.palette[k] = hex;
  });
  tileChanged();
}

document.getElementById("import-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  loadTile(JSON.parse(await file.text()));
  event.target.value = "";
});

/* --------------------------------------------------------- shareable URL */

// The whole tile — geometry, weave, and colors — fits in the address bar
// (deflated, then base64url), so a link is self-contained and needs no
// server or file.

function tilePayload() {
  const palette = state.result
    ? Array.from({ length: state.result.paletteSize }, (_, k) => paletteColor(k))
    : [];
  return { grid: state.grid, pieces: state.pieces, weave: state.weave, palette };
}

function b64urlDecode(text) {
  let s = text.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  return atob(s);
}

function b64urlEncodeBytes(bytes) {
  let text = "";
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecodeBytes(text) {
  return Uint8Array.from(b64urlDecode(text), (c) => c.charCodeAt(0));
}

async function deflate(text) {
  const stream = new Blob([text]).stream()
    .pipeThrough(new CompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

async function inflate(bytes) {
  const stream = new Blob([bytes]).stream()
    .pipeThrough(new DecompressionStream("deflate-raw"));
  return new Response(stream).text();
}

// Keep the address bar in sync with the current tile (replaceState, so it
// doesn't spam history).  An empty tile drops the fragment.  Compression is
// async, so a token guards against an older sync finishing after a newer
// one and writing a stale fragment.
let syncToken = 0;
async function syncURL() {
  const token = ++syncToken;
  if (state.pieces.length === 0) {
    history.replaceState(null, "", location.pathname + location.search);
    return;
  }
  const packed = b64urlEncodeBytes(await deflate(JSON.stringify(tilePayload())));
  if (token !== syncToken) return;
  history.replaceState(null, "", "#z=" + packed);
}

async function loadFromURL() {
  const packed = location.hash.match(/[#&]z=([^&]+)/);
  if (!packed) return false;
  loadTile(JSON.parse(await inflate(b64urlDecodeBytes(packed[1]))));
  return true;
}

document.getElementById("copy-link").addEventListener("click", async () => {
  if (state.pieces.length === 0) return;
  await syncURL();
  const status = document.getElementById("status");
  navigator.clipboard.writeText(location.href).then(
    () => { status.textContent = "link copied to clipboard"; },
    () => { status.textContent = location.href; }
  );
});

/* ------------------------------------------------------------ generate */

document.getElementById("generate").addEventListener("click", async () => {
  if (state.pieces.length === 0 || !state.result) return;
  const button = document.getElementById("generate");
  const status = document.getElementById("gen-status");
  button.disabled = true;
  status.textContent = "starting…";
  const job = crypto.randomUUID();
  const poll = setInterval(async () => {
    const p = await (await fetch(`/api/generate/progress?job=${job}`)).json();
    if (p.state === "queued") {
      status.textContent = p.behind > 0
        ? `queued behind ${p.behind} job${p.behind > 1 ? "s" : ""}…`
        : "queued…";
    } else if (p.state === "loading") {
      status.textContent = "loading models — the first run downloads ~5 GB";
    } else if (p.state === "rendering") {
      status.textContent = "rendering conditioning maps…";
    } else if (p.state === "sampling") {
      const which = p.count > 1 ? `image ${p.image}/${p.count}, ` : "";
      status.textContent = `sampling ${which}step ${p.step}/${p.total}`;
    }
  }, 500);
  const strength = document.getElementById("gen-strength").value / 100;
  const response = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      grid: state.grid,
      pieces: state.pieces,
      diagonal: state.diagonal,
      weave: state.weave,
      prompt: document.getElementById("prompt").value,
      palette: Array.from(
        { length: state.result.paletteSize },
        (_, k) => paletteColor(k)
      ),
      region_prompts: Array.from(
        { length: state.result.paletteSize },
        (_, k) => state.regionPrompts[k] || ""
      ),
      background: state.background,
      background_prompt: state.backgroundPrompt,
      job,
      seed: parseInt(document.getElementById("gen-seed").value, 10) || 0,
      count: parseInt(document.getElementById("gen-count").value, 10) || 1,
      color_strength: strength,
    }),
  });
  clearInterval(poll);
  button.disabled = false;
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "generation failed" }));
    status.textContent = body.detail;
    return;
  }
  const data = await response.json();
  status.textContent =
    `done — ${data.tilesX}×${data.tilesY} unit tiles, seamlessly tileable`;
  const container = document.getElementById("gen-result");
  container.innerHTML = "";
  const img = document.createElement("img");
  img.src = `data:image/png;base64,${data.images[0]}`;
  img.alt = "Generated artwork";
  img.style.width = "100%";
  const save = document.createElement("a");
  save.href = img.src;
  save.download = "escher-artwork.png";
  save.textContent = "Download artwork PNG";
  if (data.images.length > 1) {
    const sheet = document.createElement("div");
    sheet.style.display = "flex";
    sheet.style.gap = "4px";
    sheet.style.margin = "4px 0";
    data.images.forEach((b64, k) => {
      const thumb = document.createElement("img");
      thumb.src = `data:image/png;base64,${b64}`;
      thumb.style.width = `${100 / data.images.length - 1}%`;
      thumb.style.cursor = "pointer";
      thumb.title = `seed ${k}`;
      thumb.addEventListener("click", () => {
        img.src = thumb.src;
        save.href = thumb.src;
      });
      sheet.append(thumb);
    });
    container.append(sheet);
  }
  container.append(img, save);
});

/* ---------------------------------------------------------------- boot */

// A shared link carries the whole tile in its fragment; otherwise start empty.
if (location.hash.includes("z=")) {
  loadFromURL().then(
    (loaded) => { if (!loaded) renderAll(); },
    () => {
      document.getElementById("status").textContent = "couldn't read tile from link";
      renderAll();
    }
  );
} else {
  renderAll();
}
