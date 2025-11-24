# bot_ai.py
from __future__ import annotations

from typing import List
import random
import copy

from cards import Card, Suit, new_deck, trick_winner_index
from engine_2p import BriscolaGame2P


ALL_CARDS = new_deck(shuffle=False)


def _would_win_as_second(card: Card, lead_card: Card, trump: Suit) -> bool:
    """Given [lead_card, card], does `card` win the trick?"""
    if lead_card.suit == trump:
        if card.suit != trump:
            return False
        return card.strength > lead_card.strength
    if card.suit == trump and lead_card.suit != trump:
        return True
    if card.suit == lead_card.suit:
        return card.strength > lead_card.strength
    return False


# ---------- EASY ----------

def bot_choose_easy(game: BriscolaGame2P, bot_index: int) -> int:
    """Totally random card."""
    hand = game.hands[bot_index]
    return random.randrange(len(hand))


# ---------- MEDIUM ----------

def bot_choose_medium(game: BriscolaGame2P, bot_index: int) -> int:
    hand = game.hands[bot_index]
    trump = game.trump_suit
    other = 1 - bot_index
    lead_card = game.current_trick[other]

    # Bot leads
    if lead_card is None:
        zero_non_trump = [
            (i, c) for i, c in enumerate(hand)
            if c.points == 0 and c.suit != trump
        ]
        if zero_non_trump:
            i, card = min(zero_non_trump, key=lambda ic: ic[1].strength)
            return i
        return min(range(len(hand)),
                   key=lambda i: (hand[i].points, hand[i].strength))

    # Bot plays second
    winning_moves = []
    losing_moves = []
    for i, card in enumerate(hand):
        wins = _would_win_as_second(card, lead_card, trump)
        pts_trick = lead_card.points + card.points
        if wins:
            winning_moves.append((i, card, pts_trick))
        else:
            losing_moves.append((i, card, pts_trick))

    HIGH_VALUE = 10

    good_wins = [m for m in winning_moves if m[2] >= HIGH_VALUE]
    if good_wins:
        i, card, pts = min(good_wins,
                           key=lambda m: (m[1].strength, m[1].points))
        return i

    if losing_moves:
        i, card, pts = min(losing_moves,
                           key=lambda m: (m[1].points, m[1].strength))
        return i

    if winning_moves:
        i, card, pts = min(winning_moves,
                           key=lambda m: (m[1].strength, m[1].points))
        return i

    return random.randrange(len(hand))


# ---------- HARD ----------

def bot_choose_hard(game: BriscolaGame2P, bot_index: int) -> int:
    """
    Hard mode:
    - If leading: for each lead card, consider all opponent replies from their hand,
      assume they choose the reply that's worst for us (minimax), and pick the lead
      whose worst-case trick outcome is best.
    - If second: evaluate each card by whether it wins/loses and the trick points.
    """
    hand = game.hands[bot_index]
    other = 1 - bot_index
    opp_hand = game.hands[other]
    trump = game.trump_suit
    lead_card = game.current_trick[other]

    # ---- Case 1: bot is second (opponent already led) ----
    if lead_card is not None:
        best_score = None
        best_index = 0
        for i, card in enumerate(hand):
            pts_trick = lead_card.points + card.points
            wins = _would_win_as_second(card, lead_card, trump)
            if wins:
                score = +pts_trick + 0.5 * card.points
            else:
                score = -card.points
            if best_score is None or score > best_score:
                best_score = score
                best_index = i
        return best_index

    # ---- Case 2: bot is leading this trick ----
    best_index = 0
    best_worst_case = None

    for i, lead in enumerate(hand):
        worst_case = None
        for reply in opp_hand:
            trick = [lead, reply]
            rel_winner = trick_winner_index(trick, trump)
            pts_trick = lead.points + reply.points
            if rel_winner == 0:  # bot wins
                score = +pts_trick
            else:
                score = -pts_trick
            if worst_case is None or score < worst_case:
                worst_case = score

        # small bias to keep strong cards if tie
        worst_case -= 0.2 * lead.points

        if best_worst_case is None or worst_case > best_worst_case:
            best_worst_case = worst_case
            best_index = i

    return best_index


# ---------- EXTREME: Monte Carlo ----------

def simulate_game_from(game: BriscolaGame2P, bot_index: int) -> int:
    sim = copy.deepcopy(game)
    while not sim.is_over():
        current = sim.turn
        if not sim.hands[current]:
            break
        if current == bot_index:
            idx = bot_choose_medium(sim, bot_index)
        else:
            idx = random.randrange(len(sim.hands[current]))
        sim.play_card(current, idx)
    return sim.points[bot_index]


def bot_choose_extreme(
    game: BriscolaGame2P,
    bot_index: int,
    rollouts_per_card: int = 20,
) -> int:
    """Extreme mode: Monte Carlo look-ahead over full games."""
    hand = game.hands[bot_index]
    if len(hand) <= 1:
        return 0

    scores = [0.0] * len(hand)

    for i, card in enumerate(hand):
        total = 0.0
        for _ in range(rollouts_per_card):
            sim = copy.deepcopy(game)
            try:
                sim_idx = sim.hands[bot_index].index(card)
            except ValueError:
                continue
            sim.play_card(bot_index, sim_idx)
            total += simulate_game_from(sim, bot_index)
        scores[i] = total / max(1, rollouts_per_card)

    return max(range(len(hand)), key=lambda i: scores[i])


# ---------- Selector ----------

def bot_choose_card(
    game: BriscolaGame2P,
    bot_index: int,
    difficulty: str = "medium",
) -> int:
    d = difficulty.lower()
    if d in ("easy", "e"):
        return bot_choose_easy(game, bot_index)
    if d in ("medium", "m", "normal"):
        return bot_choose_medium(game, bot_index)
    if d in ("hard", "h"):
        return bot_choose_hard(game, bot_index)
    if d in ("extreme", "x", "insane"):
        return bot_choose_extreme(game, bot_index)
    raise ValueError(f"Unknown difficulty '{difficulty}'")
