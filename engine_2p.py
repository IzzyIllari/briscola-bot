# engine_2p.py
from __future__ import annotations

from typing import List, Optional

from cards import Card, Suit, new_deck, trick_winner_index, trick_points


class BriscolaGame2P:
    """
    Minimal 2-player Briscola game engine.

    - Does NOT know about Discord / images; just state & rules.
    - Players are indexed 0 and 1.
    """

    def __init__(self, player_ids: List[object]):
        if len(player_ids) != 2:
            raise ValueError("BriscolaGame2P requires exactly 2 players")
        self.player_ids = list(player_ids)
        self.num_players = 2

        # Core state
        self.deck: List[Card] = new_deck(shuffle=True)
        self.hands: List[List[Card]] = [[] for _ in range(self.num_players)]
        self.piles: List[List[Card]] = [[] for _ in range(self.num_players)]
        self.points: List[int] = [0 for _ in range(self.num_players)]

        # Deal 3 cards to each player (P0, P1, P0, P1, ...)
        for _ in range(3):
            for p in range(self.num_players):
                self.hands[p].append(self.deck.pop())

        # Reveal trump
        self.trump_card: Optional[Card] = self.deck.pop()
        self.trump_suit: Suit = self.trump_card.suit  # type: ignore[assignment]

        # Trick state
        self.leader: int = 0  # who leads the current trick
        self.turn: int = self.leader  # whose turn to play now
        self.current_trick: List[Optional[Card]] = [None for _ in range(self.num_players)]

    def hand_for_player(self, player_index: int) -> List[Card]:
        """Return a copy of the player's hand."""
        return list(self.hands[player_index])

    def play_card(self, player_index: int, card_index: int) -> None:
        """
        Player `player_index` plays the card at `card_index` in their hand.

        This advances the trick; if the trick becomes complete, it is resolved.
        """
        if self.is_over():
            raise RuntimeError("Game is already over")
        if player_index != self.turn:
            raise ValueError(f"It is not player {player_index}'s turn")
        if not (0 <= card_index < len(self.hands[player_index])):
            raise IndexError("Invalid card index")

        card = self.hands[player_index].pop(card_index)
        self.current_trick[player_index] = card

        if any(c is None for c in self.current_trick):
            self.turn = 1 - player_index
            return

        # Everyone has played: resolve this trick
        self._resolve_trick()

    def _resolve_trick(self) -> None:
        """Resolve the current trick: determine winner, assign points, draw cards."""
        played_in_order: List[Card] = []
        for i in range(self.num_players):
            idx = (self.leader + i) % self.num_players
            card = self.current_trick[idx]
            assert card is not None, "Trick incomplete"
            played_in_order.append(card)

        rel_winner = trick_winner_index(played_in_order, self.trump_suit)
        abs_winner = (self.leader + rel_winner) % self.num_players

        pts = trick_points(played_in_order)
        self.piles[abs_winner].extend(
            [c for c in self.current_trick if c is not None]
        )
        self.points[abs_winner] += pts

        # Draw new cards if any remain in deck / trump card pile
        self._draw_after_trick(abs_winner)

        # Next trick
        self.leader = abs_winner
        self.turn = abs_winner
        self.current_trick = [None for _ in range(self.num_players)]

    def _draw_after_trick(self, starting_player: int) -> None:
        """
        After each trick, winner draws first, then the other player,
        until everyone has 3 cards or no cards remain.

        The face-up trump card is drawn LAST when the deck runs out.
        """
        for offset in range(self.num_players):
            p = (starting_player + offset) % self.num_players
            if self.deck:
                self.hands[p].append(self.deck.pop())
            elif self.trump_card is not None:
                self.hands[p].append(self.trump_card)
                self.trump_card = None

    def is_over(self) -> bool:
        """Return True when all cards have been played and taken."""
        if self.deck or self.trump_card is not None:
            return False
        if any(self.hands[p] for p in range(self.num_players)):
            return False
        if any(c is not None for c in self.current_trick):
            return False
        return True

    def winner(self) -> Optional[int]:
        """
        Return:
        - 0 or 1 if that player wins with >= 61 points
        - None for tie (e.g., 60-60) or if game not over yet.
        """
        if not self.is_over():
            return None
        p0, p1 = self.points
        if p0 > p1 and p0 >= 61:
            return 0
        if p1 > p0 and p1 >= 61:
            return 1
        return None

    def total_points(self) -> int:
        """Total points collected by both players (should be 120 at end)."""
        return sum(self.points)

    def __repr__(self) -> str:
        return (
            f"<BriscolaGame2P trump={self.trump_suit.value} "
            f"points={self.points} deck={len(self.deck)} cards>"
        )
