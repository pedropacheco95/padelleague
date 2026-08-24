"""Generate division artwork with an image model.

The league already generates this artwork with AI by hand (the posters in
production carry a Grok watermark). This module does the same thing through the
OpenAI images API so it can run unattended as part of creating an edition.

Two deliberately different styles, matching what is already on the site:

- poster — photorealistic padel action with a Porto backdrop, portrait
- banner — flat stylised illustration of a Porto landmark, very wide strip

Neither carries text. The site renders the division name over/next to these, so
baking words into the image would duplicate it — and image models render text
badly anyway.

The model's aspect ratios don't match the site's exactly, so output always goes
through `artwork.normalise`, which cover-crops to the exact pixel size.
"""

import base64
import os

from padel_league.services.artwork import ArtworkError

# gpt-image-1 only accepts these; pick the closest to each target ratio and let
# the cover-crop do the rest.
MODEL = "gpt-image-1"
GENERATION_SIZES = {
    "poster": "1024x1536",  # 0.67 vs the poster's 0.71 — a light crop
    "banner": "1536x1024",  # cropped hard vertically into the 4.35:1 strip
}

PROMPTS = {
    "poster": (
        "A photorealistic vertical photograph of a padel player mid-rally on a "
        "rooftop padel court in Porto, Portugal. Glass and black metal court "
        "walls. Behind the court, the Porto skyline with terracotta rooftops, "
        "church domes and pale buildings under a bright hazy sky. Natural "
        "daylight, shallow depth of field, muted contemporary sports "
        "photography, clean and uncluttered. No text, no logos, no watermarks."
    ),
    "banner": (
        "A wide flat vector illustration of the Dom Luis I bridge in Porto seen "
        "from above, spanning the Douro river. Deep blue steel ironwork, "
        "turquoise water, terracotta rooftops and pale buildings along the "
        "banks. Bold flat colour, minimal shading, stylised editorial "
        "illustration, panoramic composition filling the full width. No text, "
        "no logos, no watermarks."
    ),
}


def _api_key():
    key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ArtworkError(
            "no image-model API key: set LLM_API_KEY (the name production uses) "
            "or OPENAI_API_KEY"
        )
    return key


def _default_client():
    from openai import OpenAI

    return OpenAI(api_key=_api_key())


def build_prompt(kind, extra=None):
    if kind not in PROMPTS:
        raise ArtworkError(
            f"unknown artwork kind {kind!r}; expected one of {sorted(PROMPTS)}"
        )
    prompt = PROMPTS[kind]
    if extra:
        prompt = f"{prompt} {extra.strip()}"
    return prompt


def generate(kind, extra=None, client=None, model=MODEL):
    """Return raw image bytes for `kind`.

    `extra` is appended to the base prompt so a caller can vary the scene per
    division (otherwise all six divisions get near-identical artwork).
    `client` is injectable for tests.
    """
    prompt = build_prompt(kind, extra)
    client = client or _default_client()

    try:
        response = client.images.generate(
            model=model,
            prompt=prompt,
            size=GENERATION_SIZES[kind],
            n=1,
        )
    except Exception as exc:
        raise ArtworkError(f"image generation failed for {kind}: {exc}")

    try:
        payload = response.data[0].b64_json
    except (AttributeError, IndexError, TypeError) as exc:
        raise ArtworkError(f"unexpected image API response shape: {exc}")

    if not payload:
        raise ArtworkError(f"image API returned no image data for {kind}")

    return base64.b64decode(payload)


# Small per-division variations so a six-division edition doesn't end up with
# six copies of the same picture.
POSTER_VARIATIONS = [
    "Shot from behind the glass back wall at court level.",
    "Shot from the side, player stretching wide for a forehand.",
    "Low angle looking slightly up, player about to serve.",
    "Shot through the court fencing, player waiting at the net.",
    "Wider framing showing two players and more of the skyline.",
    "Late afternoon light with long shadows across the court.",
]

BANNER_VARIATIONS = [
    "Seen from the Gaia side, looking across to Ribeira.",
    "Seen from the Ribeira side at river level.",
    "Higher aerial angle showing more of the river bend.",
    "Focused on the upper deck of the bridge.",
    "Including rabelo boats moored along the quay.",
    "Warmer palette, late afternoon light.",
]


def variation_for(kind, index):
    """Pick a scene variation for the division at `index` (0-based)."""
    pool = POSTER_VARIATIONS if kind == "poster" else BANNER_VARIATIONS
    return pool[index % len(pool)]
