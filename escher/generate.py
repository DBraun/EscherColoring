"""Text-to-image generation constrained by the tile structure.

Stable Diffusion 1.5 with a lineart ControlNet, conditioned on the exact
rasterized rails of the wallpaper (weave included), plus the flat color map
as the img2img init so the computed coloring survives stylization.  Every
convolution in the UNet, VAE and ControlNet is switched to circular padding,
which makes the sample toroidal: the output tiles seamlessly with the same
periods as the Big Tile window it was conditioned on.  When the window holds
several Big Tile copies, the latents are additionally averaged over the Big
Tile translates at every denoising step, so the artwork repeats exactly per
Big Tile.

The models (~5 GB) download from the Hugging Face hub on first use and are
cached; the pipeline stays loaded on the GPU afterwards.
"""

from PIL import Image, ImageFilter, ImageOps

BASE_MODEL = "Lykon/dreamshaper-8"
CONTROLNET_MODEL = "lllyasviel/control_v11p_sd15_lineart"
DEPTH_MODEL = "lllyasviel/control_v11f1p_sd15_depth"

# SD 1.5-class models need verbose style language to leave their default
# illustration register; appended to every prompt (regional ones included).
STYLE_SUFFIX = "poster art, ornate, intricate, highly detailed"

_PIPELINE = None
_LOCK = None


def _lock():
    global _LOCK
    if _LOCK is None:
        import threading

        _LOCK = threading.Lock()
    return _LOCK


def _patch_circular(module) -> None:
    """Switch every Conv2d to circular padding for toroidal outputs."""
    import torch

    for layer in module.modules():
        if isinstance(layer, torch.nn.Conv2d):
            layer.padding_mode = "circular"


def _pipeline():
    global _PIPELINE
    if _PIPELINE is None:
        import torch
        from diffusers import (
            ControlNetModel,
            StableDiffusionControlNetImg2ImgPipeline,
            UniPCMultistepScheduler,
        )

        controlnets = [
            ControlNetModel.from_pretrained(CONTROLNET_MODEL, torch_dtype=torch.float16),
            ControlNetModel.from_pretrained(DEPTH_MODEL, torch_dtype=torch.float16),
        ]
        pipe = StableDiffusionControlNetImg2ImgPipeline.from_pretrained(
            BASE_MODEL,
            controlnet=controlnets,
            torch_dtype=torch.float16,
            safety_checker=None,
            requires_safety_checker=False,
        )
        pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)
        pipe.to("cuda")
        for module in (pipe.unet, pipe.vae, *pipe.controlnet.nets):
            _patch_circular(module)
        # Eager fp16 with SDPA attention; channels-last and cuDNN autotuning
        # are free wins.  torch.compile is opt-in (ESCHER_COMPILE=1) because
        # the first call per shape stalls for minutes while compiling.
        import os

        torch.backends.cudnn.benchmark = True
        pipe.unet.to(memory_format=torch.channels_last)
        pipe.vae.to(memory_format=torch.channels_last)
        if os.environ.get("ESCHER_COMPILE") == "1":
            pipe.unet = torch.compile(pipe.unet)
        _PIPELINE = pipe
    return _PIPELINE


def window_shape(big_width: int, big_height: int) -> tuple[int, int, int]:
    """Choose a near-square window of whole Big Tiles and a cell size.

    Returns:
        ``(tiles_x, tiles_y, cell)`` with dimensions divisible by 8 and the
        longer side at most ~832 px.
    """
    tiles_x, tiles_y = big_width, big_height
    while tiles_x < tiles_y and tiles_x + big_width <= 6:
        tiles_x += big_width
    while tiles_y < tiles_x and tiles_y + big_height <= 6:
        tiles_y += big_height
    cell = max(64, (832 // (8 * max(tiles_x, tiles_y))) * 8)
    return tiles_x, tiles_y, cell


def generate(
    lineart: Image.Image,
    color: Image.Image,
    depth: Image.Image,
    prompt: str,
    negative_prompt: str = (
        "blurry, low quality, photo frame, watermark, translucent, "
        "transparent overlaps, blended colors"
    ),
    steps: int = 28,
    seed: int = 0,
    color_strength: float = 0.9,
    control_scale: float = 0.9,
    on_step=None,
    regions: list[tuple[str, Image.Image]] | None = None,
    period: tuple[int, int] | None = None,
) -> Image.Image:
    """Generate artwork over the conditioning maps.

    Args:
        lineart: Black rails on white from :func:`escher.raster.render_region`.
        color: Matching flat color map (same size).
        depth: Matching weave depth map (white = near).
        prompt: Text prompt for the artwork.
        negative_prompt: Negative prompt.
        steps: Denoising steps.
        seed: Random seed.
        color_strength: img2img strength (the demo's "stylization"); 1.0
            ignores the color map entirely, lower values keep the computed
            palette more literally.  High values also ease the ControlNets:
            the rails weight drops, conditioning stops before the final
            denoising steps, and classifier-free guidance rises, so the
            model can paint texture instead of flat fills while the early
            steps still lock the geometry.
        control_scale: ControlNet conditioning scale for the rails at
            stylization 0; the effective scale eases as stylization rises.
        on_step: Optional callback ``(step, total_steps)`` for progress.
        regions: Optional regional prompts as ``(fragment, mask)`` pairs; the
            fragment is prepended to the prompt and applies only inside the
            (white-on-black) mask.  Implemented as batched denoising with the
            latents blended through the masks at every step.
        period: Big Tile period of the conditioning window in pixels
            ``(width, height)``.  When the window holds several Big Tile
            copies, the latents are averaged over all Big Tile translates at
            every denoising step, so every copy is stylized identically and
            the artwork repeats exactly per Big Tile (not just per window).

    Returns:
        The generated image (same size as the inputs, toroidally seamless).
    """
    import torch

    with _lock():
        pipe = _pipeline()
    # The exact depth render puts a hard-edged bright box at every crossing,
    # which the depth net reads as a separate raised object; blurring turns it
    # into a smooth lift of the over strand.
    soft_depth = depth.filter(ImageFilter.GaussianBlur(max(2, min(depth.size) // 128)))
    control = [ImageOps.invert(lineart.convert("L")).convert("RGB"), soft_depth]

    # Held at full strength for every step, the lineart net corners the
    # model into flat vector fills no matter what the prompt asks for, so
    # stylization eases the ControlNets alongside the color init.  The
    # easing is deliberately shallow: the rails net is what preserves the
    # ribbon topology, so it never drops below ~0.7 and keeps conditioning
    # through ~85% of the steps even at maximum stylization.
    rails_scale = control_scale * (1 - 0.2 * color_strength)
    depth_scale = 0.5 * (1 - 0.4 * color_strength)
    control_end = 1 - 0.15 * color_strength
    guidance_scale = 7.5 + 2.0 * color_strength

    regions = [r for r in (regions or []) if r[0].strip()]
    prompts = [f"{prompt}, {STYLE_SUFFIX}"] + [
        f"{fragment}, {prompt}, {STYLE_SUFFIX}" for fragment, _ in regions
    ]
    batch = len(prompts)
    generator = [
        torch.Generator(device="cuda").manual_seed(seed) for _ in range(batch)
    ]

    masks = None
    if regions:
        import numpy as np

        w, h = lineart.size
        stack = []
        for _, mask in regions:
            soft = mask.convert("L").filter(ImageFilter.GaussianBlur(3))
            arr = np.asarray(soft.resize((w // 8, h // 8)), dtype="float32") / 255
            stack.append(torch.from_numpy(arr))
        stack = torch.stack(stack).clamp(0, 1)
        base = (1 - stack.sum(0)).clamp(0, 1)
        masks = torch.cat([base[None], stack]).to("cuda", torch.float16)
        masks = masks / masks.sum(0, keepdim=True).clamp(min=1e-4)
        masks = masks[:, None]  # (batch, 1, h/8, w/8)

    # Big Tile translates of the window, in latent units (1 latent px = 8
    # image px; the cell size is a multiple of 8 so these are exact).
    shifts = []
    if period is not None:
        width, height = lineart.size
        px, py = period[0] // 8, period[1] // 8
        nx, ny = (width // 8) // px, (height // 8) // py
        shifts = [
            (ky * py, kx * px) for ky in range(ny) for kx in range(nx)
        ][1:]  # (0, 0) is the identity; the accumulator starts from it.

    def callback(pipeline, step, timestep, kwargs):
        if masks is not None:
            latents = kwargs["latents"]
            blended = (masks * latents).sum(0, keepdim=True)
            kwargs["latents"] = blended.expand_as(latents).contiguous()
        if shifts:
            # The trajectory starts periodic (see the randn_tensor patch at
            # the pipe call), so this averaging only corrects the small
            # equivariance leaks of the strided UNet convolutions instead of
            # deleting real sampling variance.
            latents = kwargs["latents"]
            acc = latents.clone()
            for sy, sx in shifts:
                acc += torch.roll(latents, shifts=(sy, sx), dims=(2, 3))
            kwargs["latents"] = acc / (1 + len(shifts))
        if on_step is not None:
            on_step(step + 1, pipeline.num_timesteps)
        return kwargs

    with _lock():
        # The initial img2img noise must itself be Big Tile periodic, or the
        # denoising trajectory starts with a non-periodic component that the
        # per-step averaging can only delete (which starves the sampler of
        # variance and turns the output murky).  prepare_latents draws its
        # noise through this module-level randn_tensor, so it is patched to
        # tile one Big Tile block across the window for the duration of the
        # call; the GPU lock makes this thread-safe.
        from diffusers.pipelines.controlnet import pipeline_controlnet_img2img

        original_randn = pipeline_controlnet_img2img.randn_tensor

        def periodic_randn(shape, *args, **kw):
            noise = original_randn(shape, *args, **kw)
            if (
                shifts
                and noise.ndim == 4
                and noise.shape[2] % py == 0
                and noise.shape[3] % px == 0
            ):
                block = noise[:, :, :py, :px]
                noise = block.repeat(
                    1, 1, noise.shape[2] // py, noise.shape[3] // px
                )
            return noise

        pipeline_controlnet_img2img.randn_tensor = periodic_randn
        try:
            result = pipe(
                prompt=prompts,
                negative_prompt=[negative_prompt] * batch,
                image=color,
                control_image=control,
                strength=color_strength if color_strength < 1 else 0.999,
                num_inference_steps=steps,
                controlnet_conditioning_scale=[rails_scale, depth_scale],
                control_guidance_end=control_end,
                guidance_scale=guidance_scale,
                generator=generator,
                callback_on_step_end=callback,
            )
        finally:
            pipeline_controlnet_img2img.randn_tensor = original_randn
    return result.images[0]
