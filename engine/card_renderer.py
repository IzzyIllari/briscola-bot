"""
engine/card_renderer.py
Composites 1-3 card images side by side into an in-memory PNG buffer
using Pillow. The buffer is sent directly to Discord as a file attachment,
which bypasses the single-image-per-ephemeral-message limitation.

NOTE: Reads card images from the local decks/ folder.
This works when the bot runs from the repo root with decks/ present.
If you move to a hosted server, copy decks/ alongside the code.
See DeckConfig.local_image_path() in engine/cards.py.
"""
from __future__ import annotations
import io
from typing import List

from PIL import Image

from engine.cards import Card, DeckConfig


# Gap between cards in pixels
_CARD_GAP = 12
# Padding around the whole image
_PADDING = 16
# Height to scale each card to (width scales proportionally)
_CARD_HEIGHT = 200


def render_hand(cards: List[Card], cfg: DeckConfig) -> io.BytesIO:
    """
    Render a list of cards (1-3) side by side.
    Returns a BytesIO PNG buffer ready to pass to discord.File().

    Falls back gracefully: if a card image is missing on disk,
    a blank placeholder is used so the rest still render.
    """
    card_images: List[Image.Image] = []

    for card in cards:
        path = cfg.local_image_path(card)
        if path.exists():
            img = Image.open(path).convert("RGBA")
            # Scale to target height, preserve aspect ratio
            ratio = _CARD_HEIGHT / img.height
            new_w = int(img.width * ratio)
            img = img.resize((new_w, _CARD_HEIGHT), Image.LANCZOS)
        else:
            # Placeholder: grey rectangle if file missing
            img = Image.new("RGBA", (int(_CARD_HEIGHT * 0.7), _CARD_HEIGHT), (80, 80, 80, 255))
        card_images.append(img)

    if not card_images:
        # Should never happen, but return a tiny blank image rather than crash
        buf = io.BytesIO()
        Image.new("RGBA", (1, 1)).save(buf, format="PNG")
        buf.seek(0)
        return buf

    total_width = (
        sum(img.width for img in card_images)
        + _CARD_GAP * (len(card_images) - 1)
        + _PADDING * 2
    )
    total_height = _CARD_HEIGHT + _PADDING * 2

    # Dark background matching Discord's dark theme
    canvas = Image.new("RGBA", (total_width, total_height), (32, 34, 37, 255))

    x = _PADDING
    for img in card_images:
        canvas.paste(img, (x, _PADDING), img)
        x += img.width + _CARD_GAP

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return buf
