"""
engine/game.py
Core 2-player Briscola game engine.

Intentionally free of all Discord / UI code.
`seen_cards` tracks every card that has left concealment, enabling
AI card-counting without peeking at the opponent's hand.
"""
from __future__ import annotations
from typing import List, Optional, Set
from engine.cards import (
    Card, DeckConfig, DEFAULT_DECK_CONFIG,
    trick_winner_index, trick_points,
)


class BriscolaGame:
    """
    2-player Briscola game engine.

    State machine:
      1. __init__: shuffle, deal 3 cards each, flip trump card.
      2. play_card(player, card_index): advance the trick.
         - If trick complete → _resolve_trick (score + draw).
      3. is_over() → True once all cards have been played and scored.
      4. winner() → 0, 1, or None (tie).
    """

    def __init__(
        self,
        deck_config: DeckConfig = DEFAULT_DECK_CONFIG,
        first_player: int = 0,
    ):
        if first_player not in (0, 1):
            raise ValueError("first_player must be 0 or 1")
        self.deck_config: DeckConfig = deck_config
        self.deck: List[Card] = deck_config.build_deck(shuffle=True)
        self.num_players: int = 2

        self.hands: List[List[Card]] = [[], []]
        self.piles: List[List[Card]] = [[], []]   # won tricks
        self.points: List[int] = [0, 0]

        # Deal 3 cards each: P0, P1, P0, P1, P0, P1
        for _ in range(3):
            for p in range(self.num_players):
                self.hands[p].append(self.deck.pop())

        # Reveal trump card (remains face-up until drawn last)
        self.trump_card: Optional[Card] = self.deck.pop()
        self.trump_suit: str = self.trump_card.suit

        # Trick state — first_player leads the opening trick
        self.leader: int = first_player
        self.turn: int = first_player
        self.current_trick: List[Optional[Card]] = [None, None]

        # Card memory — every card visible to all players:
        # the face-up trump is immediately known; played cards are added as played.
        self.seen_cards: Set[Card] = {self.trump_card}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def play_card(self, player_index: int, card_index: int) -> None:
        """
        Player `player_index` plays the card at position `card_index`
        in their hand. Advances the trick; resolves it when both players
        have played.

        Raises:
            RuntimeError  – game is already over
            ValueError    – wrong player's turn
            IndexError    – card_index out of range
        """
        if self.is_over():
            raise RuntimeError("Game is already over")
        if player_index != self.turn:
            raise ValueError(
                f"Not player {player_index}'s turn (current turn: {self.turn})"
            )
        hand = self.hands[player_index]
        if not (0 <= card_index < len(hand)):
            raise IndexError(
                f"card_index {card_index} out of range for hand of {len(hand)}"
            )

        card = hand.pop(card_index)
        self.seen_cards.add(card)
        self.current_trick[player_index] = card

        if any(c is None for c in self.current_trick):
            # Trick not yet complete — let the other player go
            self.turn = 1 - player_index
        else:
            self._resolve_trick()

    def is_over(self) -> bool:
        """True once deck is empty, trump card drawn, hands empty, trick clear."""
        if self.deck or self.trump_card is not None:
            return False
        if any(self.hands[p] for p in range(self.num_players)):
            return False
        if any(c is not None for c in self.current_trick):
            return False
        return True

    def winner(self) -> Optional[int]:
        """
        Returns the winning player index (0 or 1), or None for a tie
        or if the game isn't over yet.
        Win condition: strictly more than the opponent AND ≥ 61 points.
        """
        if not self.is_over():
            return None
        p0, p1 = self.points
        if p0 > p1 and p0 >= 61:
            return 0
        if p1 > p0 and p1 >= 61:
            return 1
        return None  # tie (60–60 or both < 61, which shouldn't happen with 120 total)

    def cards_remaining_in_stock(self) -> int:
        """Cards left in deck plus 1 if trump card is still on the table."""
        return len(self.deck) + (1 if self.trump_card else 0)

    def unknown_cards(self, from_perspective_of: int) -> List[Card]:
        """
        Cards not in the given player's hand and not yet seen.
        These are either still in the deck or in the opponent's hand —
        the player cannot know which without peeking.
        Useful for probabilistic AI reasoning.
        """
        known = self.seen_cards | set(self.hands[from_perspective_of])
        return [c for c in self.deck_config.all_cards() if c not in known]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_trick(self) -> None:
        """Score, update piles, draw new cards, and reset trick state."""
        # Build the play-order list starting from who led
        played_in_order: List[Card] = [
            self.current_trick[(self.leader + i) % self.num_players]  # type: ignore[index]
            for i in range(self.num_players)
        ]

        rel_winner = trick_winner_index(played_in_order, self.trump_suit)
        abs_winner = (self.leader + rel_winner) % self.num_players
        pts = trick_points(played_in_order)

        self.piles[abs_winner].extend(c for c in self.current_trick if c is not None)
        self.points[abs_winner] += pts

        self._draw_after_trick(abs_winner)

        self.leader = abs_winner
        self.turn = abs_winner
        self.current_trick = [None, None]

    def _draw_after_trick(self, starting_player: int) -> None:
        """
        Winner draws first, then the other player.
        The face-up trump card is drawn LAST once the regular deck is empty.
        """
        for offset in range(self.num_players):
            p = (starting_player + offset) % self.num_players
            if self.deck:
                self.hands[p].append(self.deck.pop())
                # Drawn from the hidden deck — NOT added to seen_cards
            elif self.trump_card is not None:
                self.hands[p].append(self.trump_card)
                # trump_card was already in seen_cards from __init__
                self.trump_card = None

    def __repr__(self) -> str:
        return (
            f"<BriscolaGame deck={self.deck_config.name!r} "
            f"trump={self.trump_suit!r} "
            f"pts={self.points} "
            f"stock={self.cards_remaining_in_stock()}>"
        )
