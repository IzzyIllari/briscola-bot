# cards.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List
import random


class Suit(str, Enum):
    DENARI = "Denari"
    COPPE = "Coppe"
    SPADE = "Spade"
    BASTONI = "Bastoni"


RANK_ORDER: List[str] = ["2", "4", "5", "6", "7", "F", "C", "R", "3", "A"]
RANK_STRENGTH = {rank: i for i, rank in enumerate(RANK_ORDER)}

RANK_POINTS = {
    "A": 11,
    "3": 10,
    "R": 4,
    "C": 3,
    "F": 2,
    "7": 0,
    "6": 0,
    "5": 0,
    "4": 0,
    "2": 0,
}


@dataclass(frozen=True)
class Card:
    suit: Suit
    rank: str

    @property
    def points(self) -> int:
        return RANK_POINTS[self.rank]

    @property
    def strength(self) -> int:
        return RANK_STRENGTH[self.rank]

    def __str__(self) -> str:
        return f"{self.rank} of {self.suit.value}"

    def __repr__(self) -> str:
        return f"Card({self.suit.name}, {self.rank!r})"


def new_deck(shuffle: bool = True) -> List[Card]:
    deck = [Card(suit, rank) for suit in Suit for rank in RANK_ORDER]
    if shuffle:
        random.shuffle(deck)
    return deck


def trick_winner_index(played: List[Card], trump: Suit) -> int:
    assert played, "No cards played in this trick"
    lead_suit = played[0].suit

    def key(card: Card):
        if card.suit == trump:
            category = 2
        elif card.suit == lead_suit:
            category = 1
        else:
            category = 0
        return (category, card.strength)

    best_index = 0
    best_key = key(played[0])
    for i, c in enumerate(played[1:], start=1):
        k = key(c)
        if k > best_key:
            best_key = k
            best_index = i
    return best_index


def trick_points(played: List[Card]) -> int:
    return sum(c.points for c in played)


def format_cards(cards: List[Card]) -> str:
    return ", ".join(str(c) for c in cards)


SUIT_SYMBOLS = {
    Suit.DENARI:  "♦",
    Suit.COPPE:   "♥",
    Suit.SPADE:   "♠",
    Suit.BASTONI: "♣",
}


def short_card(card: Card) -> str:
    return f"{card.rank}{SUIT_SYMBOLS[card.suit]}"


# ---------- Image URL helpers ----------

# Your public GitHub repo path
BASE_CARDS_URL = (
    "https://raw.githubusercontent.com/IzzyIllari/briscola-bot/main/cropped_cards"
)

SUIT_FILE_PREFIX = {
    Suit.DENARI:  "denari",
    Suit.COPPE:   "coppe",
    Suit.SPADE:   "spade",
    Suit.BASTONI: "bastoni",
}


def card_image_url(card: Card, deck: str = "piacentine") -> str:
    """
    e.g. Card(Suit.BASTONI, "2")
    -> https://raw.githubusercontent.com/IzzyIllari/briscola-bot/main/
       cropped_cards/piacentine/bastoni_2.png
    """
    prefix = SUIT_FILE_PREFIX[card.suit]
    return f"{BASE_CARDS_URL}/{deck}/{prefix}_{card.rank}.png"

