"""
engine/cards.py
Card primitives, deck configurations, and display helpers.

Design: Card is a frozen dataclass with all game-relevant data (points,
strength) baked in at construction time by DeckConfig.build_deck().
The engine never needs to consult a config at runtime; the bot layer
uses the config only for display (emoji, image URLs, labels).
"""
from __future__ import annotations
import pathlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import random


# ---------------------------------------------------------------------------
# Core card type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Card:
    """
    Immutable, hashable card. Points and strength are baked in at
    construction so the engine needs no external lookup tables.
    """
    suit: str      # Human-readable suit name, e.g. "Denari", "Oros", "Hearts"
    rank: str      # Rank string, e.g. "A", "3", "R", "7"
    points: int    # Point value (11 / 10 / 4 / 3 / 2 / 0)
    strength: int  # Trick-taking strength (0 = weakest in the deck)
    suit_key: str  # Normalised key for image filenames, e.g. "denari"

    def __str__(self) -> str:
        return f"{self.rank} of {self.suit}"

    def __repr__(self) -> str:
        return f"Card({self.suit!r}, {self.rank!r}, pts={self.points})"


# ---------------------------------------------------------------------------
# Deck configuration
# ---------------------------------------------------------------------------

@dataclass
class DeckConfig:
    """
    All variant-specific data: suits, rank ordering, point values, images.
    Use build_deck() to create a game-ready list of Card objects.
    """
    name: str                             # registry key, e.g. "piacentine"
    label: str                            # human-readable label for embeds
    suits: List[Tuple[str, str]]          # [(display_name, suit_key), ...]
    rank_order: List[str]                 # weakest → strongest
    rank_points: Dict[str, int]
    image_base_url: str                   # base URL; cards are {suit_key}_{rank}.png
    symbol_map: Dict[str, str]            # suit_key → Unicode / emoji symbol

    # ------------------------------------------------------------------
    # Deck factory
    # ------------------------------------------------------------------

    def build_deck(self, shuffle: bool = True) -> List[Card]:
        """Return all 40 cards for this config, optionally shuffled."""
        strength_map = {rank: i for i, rank in enumerate(self.rank_order)}
        cards: List[Card] = []
        for suit_name, suit_key in self.suits:
            for rank in self.rank_order:
                cards.append(Card(
                    suit=suit_name,
                    rank=rank,
                    points=self.rank_points[rank],
                    strength=strength_map[rank],
                    suit_key=suit_key,
                ))
        if shuffle:
            random.shuffle(cards)
        return cards

    def all_cards(self) -> List[Card]:
        """Return the complete unshuffled deck (useful for AI card counting)."""
        return self.build_deck(shuffle=False)

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def symbol(self, card: Card) -> str:
        return self.symbol_map.get(card.suit_key, "?")

    def short(self, card: Card) -> str:
        """e.g. 'A♦' or '3♥'"""
        return f"{card.rank}{self.symbol(card)}"

    def image_url(self, card: Card) -> Optional[str]:
        """
        Builds the GitHub raw URL for a card image.
        Path:     decks/{name}/use/
        Filename: {name}_{suit_key}_{rank_filename}.png
        e.g.  decks/piacentine/use/piacentine_bastoni_asso.png
        Used for single-card embeds (trump display, deck preview).
        """
        rank_filename = _RANK_FILENAME.get(card.rank, card.rank.lower())
        filename = f"{self.name}_{card.suit_key}_{rank_filename}.png"
        return f"{self.image_base_url}/{filename}"

    def local_image_path(self, card: Card) -> pathlib.Path:
        """
        Returns the local filesystem path for a card image.
        Used by the Pillow hand compositor — much faster than fetching
        from GitHub for frequently-called operations like /briscola_hand.

        NOTE: Only works when the bot runs from the repo root with the
        decks/ folder present locally. If you move to a hosted server,
        copy the decks/ folder alongside the code.
        """
        rank_filename = _RANK_FILENAME.get(card.rank, card.rank.lower())
        filename = f"{self.name}_{card.suit_key}_{rank_filename}.png"
        return pathlib.Path("decks") / self.name / "use" / filename


# ---------------------------------------------------------------------------
# Standard rank definitions shared across Italian / Spanish variants
# ---------------------------------------------------------------------------

_ITALIAN_RANK_ORDER: List[str] = [
    "2", "4", "5", "6", "7",  # 0–4  (0 points each)
    "F", "C", "R",             # 5–7  (2, 3, 4 points)
    "3", "A",                  # 8–9  (10, 11 points) — the classic Briscola surprise
]
_ITALIAN_RANK_POINTS: Dict[str, int] = {
    "A": 11, "3": 10, "R": 4, "C": 3, "F": 2,
    "7": 0,  "6": 0,  "5": 0, "4": 0, "2": 0,
}

_GITHUB_BASE = (
    "https://raw.githubusercontent.com/IzzyIllari/briscola-bot/main/decks"
)

# Maps the engine's internal rank codes to the filenames used in decks/*/use/
_RANK_FILENAME: Dict[str, str] = {
    "A": "asso",
    "R": "re",
    "C": "cavallo",
    "F": "fante",
    "2": "2", "3": "3", "4": "4",
    "5": "5", "6": "6", "7": "7",
}


# ---------------------------------------------------------------------------
# Deck registry
# ---------------------------------------------------------------------------

PIACENTINE = DeckConfig(
    name="piacentine",
    label="Piacentine (Italian, 40-card)",
    suits=[
        ("Denari",  "denari"),
        ("Coppe",   "coppe"),
        ("Spade",   "spade"),
        ("Bastoni", "bastoni"),
    ],
    rank_order=_ITALIAN_RANK_ORDER,
    rank_points=_ITALIAN_RANK_POINTS,
    image_base_url=f"{_GITHUB_BASE}/piacentine/use",
    symbol_map={
        "denari":  "♦",
        "coppe":   "♥",
        "spade":   "♠",
        "bastoni": "♣",
    },
)

# All Italian regional decks share the same suits and rank structure.
# The only difference between them is the artwork (image_base_url).
# Additional deck folders (siciliane, napoletane, romagnole, triestine)
# can be added to cropped_cards/ and they will work immediately.

_ITALIAN_SUITS = [
    ("Denari",  "denari"),
    ("Coppe",   "coppe"),
    ("Spade",   "spade"),
    ("Bastoni", "bastoni"),
]

_ITALIAN_SYMBOLS = {
    "denari":  "♦",
    "coppe":   "♥",
    "spade":   "♠",
    "bastoni": "♣",
}


def _italian_deck(name: str, label: str) -> DeckConfig:
    return DeckConfig(
        name=name,
        label=label,
        suits=_ITALIAN_SUITS,
        rank_order=_ITALIAN_RANK_ORDER,
        rank_points=_ITALIAN_RANK_POINTS,
        image_base_url=f"{_GITHUB_BASE}/{name}/use",
        symbol_map=_ITALIAN_SYMBOLS,
    )


SICILIANE  = _italian_deck("siciliane",  "Siciliane")
NAPOLETANE = _italian_deck("napoletane", "Napoletane")
ROMAGNOLE  = _italian_deck("romagnole",  "Romagnole")
TRIESTINE  = _italian_deck("triestine",  "Triestine")

DECK_REGISTRY: Dict[str, DeckConfig] = {
    "piacentine": PIACENTINE,
    "siciliane":  SICILIANE,
    "napoletane": NAPOLETANE,
    "romagnole":  ROMAGNOLE,
    "triestine":  TRIESTINE,
}

DEFAULT_DECK_CONFIG = PIACENTINE


# ---------------------------------------------------------------------------
# Trick resolution  (deck-agnostic — works on any Card objects)
# ---------------------------------------------------------------------------

def trick_winner_index(played: List[Card], trump_suit: str) -> int:
    """
    Returns the 0-based index (relative to play order) of the winning card.
    Lead suit is inferred from played[0].
    Rules:
      - Highest trump beats everything.
      - Otherwise highest card in the lead suit wins.
      - Off-suit non-trump cards can never win.
    """
    if not played:
        raise ValueError("No cards played")
    lead_suit = played[0].suit

    def key(card: Card) -> Tuple[int, int]:
        if card.suit == trump_suit:
            return (2, card.strength)
        if card.suit == lead_suit:
            return (1, card.strength)
        return (0, card.strength)

    best_idx, best_key = 0, key(played[0])
    for i, c in enumerate(played[1:], start=1):
        k = key(c)
        if k > best_key:
            best_key, best_idx = k, i
    return best_idx


def trick_points(played: List[Card]) -> int:
    return sum(c.points for c in played)
