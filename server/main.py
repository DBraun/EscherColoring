"""FastAPI server for the interactive Escher tiling and coloring demo.

Run from the repository root:

    .venv/bin/uvicorn server.main:app --reload --port 8123
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from escher.api import color_response
from escher.coloring import color_tile
from escher.tile import Tile, digitize

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="Escher Tiling and Coloring")


class TileRequest(BaseModel):
    """A tile as drawn in the design pane."""

    grid: int = Field(ge=2, le=32, description="Subdivisions per tile side")
    pieces: list[list[tuple[int, int]]] = Field(
        description="Motif pieces as vertex lists in grid coordinates"
    )
    diagonal: bool = Field(
        default=True,
        description="Count corner contact between diagonal tiles as a connection",
    )


@app.post("/api/color")
def color(request: TileRequest) -> dict:
    """Digitize the tile and compute the Big Tile coloring."""
    try:
        return color_response(request.grid, request.pieces, request.diagonal)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


class GenerateRequest(TileRequest):
    """Generation request: the tile plus prompt and sampling settings."""

    prompt: str = Field(min_length=1, max_length=500)
    weave: dict[str, int] = Field(default_factory=dict)
    seed: int = 0
    steps: int = Field(default=28, ge=4, le=75)
    color_strength: float = Field(default=0.9, ge=0.1, le=1.0)
    palette: list[str] = Field(default_factory=list, description="Hex color per class")
    region_prompts: list[str] = Field(
        default_factory=list, description="Prompt fragment per color class"
    )
    count: int = Field(default=1, ge=1, le=6, description="Seeds to generate")
    background: str = Field(default="#ffffff", description="Background hex color")
    background_prompt: str = Field(default="", description="Background prompt fragment")
    job: str = Field(default="", max_length=64, description="Client job id for progress")


# Per-job progress so simultaneous users each see their own state; the GPU
# itself is serialized behind _GEN_LOCK and waiting jobs report their queue
# position.
import threading

_jobs: dict[str, dict] = {}
_pending: list[str] = []
_GEN_LOCK = threading.Lock()


@app.get("/api/generate/progress")
def generate_progress(job: str = "") -> dict:
    """Progress of one generation job, polled by the front end."""
    entry = _jobs.get(job)
    if entry is None:
        return {"state": "idle", "step": 0, "total": 0}
    if entry["state"] == "queued" and job in _pending:
        return {**entry, "behind": _pending.index(job)}
    return entry


@app.post("/api/generate")
def generate(request: GenerateRequest) -> dict:
    """Generate artwork constrained by the tile (SD 1.5 + lineart ControlNet)."""
    import base64
    import io
    import uuid

    import escher.generate as generation
    from escher.generate import generate as run_generation
    from escher.generate import window_shape
    from escher.raster import render_region

    job = request.job or uuid.uuid4().hex

    tile = Tile(grid=request.grid, pieces=[list(map(tuple, p)) for p in request.pieces])
    try:
        connections, overlaps = digitize(tile, diagonal=request.diagonal)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    result = color_tile(len(tile.pieces), connections, overlaps)

    palette = [
        tuple(int(hex_color.lstrip("#")[k : k + 2], 16) for k in (0, 2, 4))
        for hex_color in request.palette
    ] or None

    tiles_x, tiles_y, cell = window_shape(result.big_width, result.big_height)
    lineart = render_region(
        tile, result, request.weave, cell, tiles_x, tiles_y, mode="lineart"
    )
    hex_bg = request.background.lstrip("#")
    bg_color = tuple(int(hex_bg[k : k + 2], 16) for k in (0, 2, 4))
    color = render_region(
        tile, result, request.weave, cell, tiles_x, tiles_y,
        mode="color", rails=False, palette=palette, background=bg_color,
    )
    depth = render_region(
        tile, result, request.weave, cell, tiles_x, tiles_y, mode="depth"
    )

    regions = None
    fragments = list(request.region_prompts)
    if any(f.strip() for f in fragments) or request.background_prompt.strip():
        import numpy as np
        from PIL import Image

        ids = render_region(
            tile, result, request.weave, cell, tiles_x, tiles_y,
            mode="color", rails=False,
            palette=[(10 * (k + 1), 0, 0) for k in range(result.palette_size)],
        )
        red = np.asarray(ids)[:, :, 0]
        green = np.asarray(ids)[:, :, 1]
        regions = []
        for k, fragment in enumerate(fragments[: result.palette_size]):
            mask = ((red == 10 * (k + 1)) & (green == 0)).astype("uint8") * 255
            regions.append((fragment, Image.fromarray(mask)))
        if request.background_prompt.strip():
            mask = ((red == 255) & (green == 255)).astype("uint8") * 255
            regions.append((request.background_prompt, Image.fromarray(mask)))
    images = []
    _jobs[job] = {"state": "queued", "step": 0, "total": 0}
    _pending.append(job)
    try:
        with _GEN_LOCK:
            _jobs[job]["state"] = (
                "rendering" if generation._PIPELINE is not None else "loading"
            )
            for index in range(request.count):
                def on_step(step: int, total: int, index=index) -> None:
                    _jobs[job].update(
                        state="sampling", step=step, total=total,
                        image=index + 1, count=request.count,
                    )

                images.append(run_generation(
                    lineart,
                    color,
                    depth,
                    prompt=request.prompt,
                    seed=request.seed + index,
                    steps=request.steps,
                    color_strength=request.color_strength,
                    on_step=on_step,
                    regions=regions,
                    period=(result.big_width * cell, result.big_height * cell),
                ))
    finally:
        _pending.remove(job)
        _jobs.pop(job, None)

    def encode(img) -> str:
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()

    return {
        "images": [encode(img) for img in images],
        "lineart": encode(lineart),
        "color": encode(color),
        "tilesX": tiles_x,
        "tilesY": tiles_y,
        "cell": cell,
    }


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
