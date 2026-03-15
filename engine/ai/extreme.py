"""
engine/ai/extreme.py

Extreme difficulty: The Dark Souls of Briscola.

Architecture (three phases):

1. ENDGAME  (stock empty, ≤4 cards each)
   Exact alpha-beta minimax — imported from heuristic.py.
   Provably optimal. There is no escape once the draw pile is gone.

2. MIDGAME FOLLOWING
   Card-counting follow logic from Hard, but with a denial twist:
   if we can capture an opponent Ace or 3, we *always* do, even if
   it costs us more than the trick is worth in raw points.

3. MIDGAME LEADING  —  Monte Carlo with denial-shaped reward
   For each candidate card:
     • Play it, then simulate 100 full games with Hard vs Hard rollouts.
     • Score each simulation with a shaped reward:
         base_score = final points scored
         + DENIAL_BONUS  per opponent Ace/3 captured
         - OWN_LOSS_PEN  per own Ace/3 lost to opponent
     • Average over rollouts to get expected shaped score.
   After MC, apply a predatory bias:
     • Cards that card-counting suggests will flush opponent trump are
       nudged upward (small bonus — don't override MC, just break ties).
     • Preserving our own Ace/3 for later gets a small positive nudge.
"""
from __future__ import annotations
import copy
import random
from math import comb
from typing import List, Optional, Set

from engine.cards import Card, trick_winner_index
from engine.game import BriscolaGame
from engine.ai.heuristic import (
    _minimax_best_move,
    _is_precious_trump,
    _wins_as_second,
    _hard_follow_counting,
    _medium_lead,
)


# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

EXTREME_ROLLOUTS: int = 100

_MINIMAX_THRESHOLD: int = 4   # switch to exact play once hands ≤ this size

# Reward shaping weights
_DENIAL_BONUS: float   = 6.0   # per opponent Ace/3 we captured
_OWN_LOSS_PEN: float   = 9.0   # per own Ace/3 the opponent captured
_TRUMP_DRAIN:  float   = 2.5   # per opponent non-high trump we captured
                                # (weakens their trump hand for future tricks)

# Predatory bias (applied after MC, so it only breaks near-ties)
_HUNT_BIAS:     float  = 2.0   # bonus for leading into a suit the opponent is low on
_FLUSH_BIAS:    float  = 1.5   # bonus for leading a mid-trump (drains their trump hand)
_PROTECT_BIAS:  float  = 1.8   # bonus for NOT leading our own Ace/3 when we don't have to


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def choose_extreme(
    game: BriscolaGame,
    bot_index: int,
    rollouts: int = EXTREME_ROLLOUTS,
) -> int:
    """
    Select the best card index for the bot in Extreme mode.
    """
    hand  = game.hands[bot_index]
    opp   = game.hands[1 - bot_index]
    trump = game.trump_suit
    lead  = game.current_trick[1 - bot_index]

    # ── Phase 1: endgame minimax ──────────────────────────────────────────
    if (game.cards_remaining_in_stock() == 0
            and len(hand) <= _MINIMAX_THRESHOLD
            and len(opp) <= _MINIMAX_THRESHOLD):
        return _minimax_best_move(hand, opp, trump, lead)

    # ── Phase 2: midgame following — denial-priority ──────────────────────
    if lead is not None:
        return _extreme_follow(hand, lead, trump, game, bot_index)

    # ── Phase 3: midgame leading — MC + predatory bias ───────────────────
    return _extreme_lead_mc(game, bot_index, rollouts)


# ---------------------------------------------------------------------------
# Phase 2 — denial-priority following
# ---------------------------------------------------------------------------

def _extreme_follow(
    hand: List[Card],
    lead: Card,
    trump: str,
    game: BriscolaGame,
    bot_index: int,
) -> int:
    """
    Follow with ruthless denial priority.

    Priority order:
    1. If we can capture an opponent Ace or 3 → always do it, cheapest first.
    2. High-value lead (≥10 pts) → win as cheaply as possible.
    3. Mid-value lead (face card) → win with non-trump if possible.
    4. Zero-point lead → only take a free (zero-cost non-trump) win.
    5. Dump the lowest-value card.
    """
    wins_nt: List[tuple] = []   # (index, card) non-trump wins
    wins_t:  List[tuple] = []   # (index, card) trump wins
    losses:  List[tuple] = []

    for i, card in enumerate(hand):
        if _wins_as_second(card, lead, trump):
            (wins_t if card.suit == trump else wins_nt).append((i, card))
        else:
            losses.append((i, card))

    trick_value = lead.points

    # ── Rule 1: always capture an opponent Ace/3 if we can ────────────────
    # (this is the denial instinct — the "it's personal" rule)
    if trick_value >= 10:
        # Lead card IS an Ace or 3 — this is a high-value trick by definition
        # Spend whatever it takes, cheapest trump win if no non-trump win exists
        if wins_nt:
            return min(wins_nt, key=lambda t: (t[1].strength, t[1].points))[0]
        if wins_t:
            return min(wins_t, key=lambda t: t[1].strength)[0]

    elif trick_value >= 2:
        # Face card lead — contest without trump
        if wins_nt:
            return min(wins_nt, key=lambda t: (t[1].strength, t[1].points))[0]
        # If trump is ALL we have to win with, only use it if the trick
        # also contains another pointed card (our played card)
        trump_wins_worth_it = [
            (i, c) for i, c in wins_t
            if trick_value + c.points >= 6   # at least King + Jack combo
        ]
        if trump_wins_worth_it:
            return min(trump_wins_worth_it, key=lambda t: t[1].strength)[0]

    else:
        # Zero-point lead: only take a completely free win
        free = [(i, c) for i, c in wins_nt if c.points == 0]
        if free:
            return min(free, key=lambda t: t[1].strength)[0]

    # Default: dump the card that hurts us least
    if losses:
        # Among losing plays: never dump our own Ace/3 if alternatives exist
        non_precious = [(i, c) for i, c in losses if not _is_precious_trump(c, trump)]
        if non_precious:
            return min(non_precious, key=lambda t: (t[1].points, t[1].strength))[0]
        return min(losses, key=lambda t: (t[1].points, t[1].strength))[0]

    # Forced to win — cheapest available
    all_wins = wins_nt + wins_t
    return min(all_wins, key=lambda t: (t[1].points, t[1].strength))[0]


# ---------------------------------------------------------------------------
# Phase 3 — denial-shaped Monte Carlo leading
# ---------------------------------------------------------------------------

def _extreme_lead_mc(
    game: BriscolaGame,
    bot_index: int,
    rollouts: int,
) -> int:
    hand = game.hands[bot_index]
    n    = len(hand)
    if n == 1:
        return 0

    # Cards in our hand right now — used to measure "own losses" in reward
    initial_hand: Set[Card] = set(hand)

    scores: List[float] = [0.0] * n

    for i, card in enumerate(hand):
        total = 0.0
        completed = 0
        for _ in range(rollouts):
            sim = copy.deepcopy(game)
            try:
                sim_idx = next(
                    j for j, c in enumerate(sim.hands[bot_index]) if c == card
                )
            except StopIteration:
                continue
            sim.play_card(bot_index, sim_idx)
            _hard_vs_hard_playout(sim, bot_index)
            total += _shaped_reward(sim, bot_index, initial_hand)
            completed += 1
        scores[i] = total / max(1, completed)

    # Apply predatory bias (small nudges that respect MC signal)
    _predatory_bias(scores, hand, game, bot_index)

    return max(range(n), key=lambda i: scores[i])


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------

def _fast_rollout_policy(game: BriscolaGame, player: int) -> int:
    """
    Fast rollout policy for MC simulations.

    Uses Hard's card-counting FOLLOW logic (cheap, no sampling) but
    Medium's LEAD logic — this avoids the nested 15-sample inner loop
    that makes full Hard prohibitively slow inside 100 outer rollouts.

    Still much stronger than random or pure Medium because it plays the
    tactical following game correctly (trump conservation, denial instinct).
    """
    hand  = game.hands[player]
    trump = game.trump_suit
    lead  = game.current_trick[1 - player]

    if lead is not None:
        # Hard's card-counting follow (fast — no random sampling)
        unknown = game.unknown_cards(player)
        opp_size = len(game.hands[1 - player])
        return _hard_follow_counting(hand, lead, trump, unknown, opp_size)

    # Medium's lead (fast — pure heuristic, no sampling)
    return _medium_lead(hand, trump)


def _hard_vs_hard_playout(game: BriscolaGame, bot_index: int) -> None:
    """Complete the game in-place using the fast rollout policy for both players."""
    while not game.is_over():
        p = game.turn
        if not game.hands[p]:
            break
        idx = _fast_rollout_policy(game, p)
        game.play_card(p, idx)


def _shaped_reward(
    sim: BriscolaGame,
    bot_index: int,
    initial_hand: Set[Card],
) -> float:
    """
    Compute the denial-shaped reward for a completed simulation.

      base     = raw points scored (0–120)
      +bonus   for each opponent Ace/3 we captured
      +bonus   for each opponent non-high trump we captured (weakens them)
      -penalty for each own Ace/3 that ended up in opponent's pile
    """
    opp_index = 1 - bot_index
    base = float(sim.points[bot_index])

    bonus = 0.0
    for card in sim.piles[bot_index]:
        if card in initial_hand:
            continue   # was already ours — not a "denial" capture
        if card.points >= 10:
            bonus += _DENIAL_BONUS     # captured opponent Ace or 3
        elif card.suit == sim.trump_suit and card.points > 0:
            bonus += _TRUMP_DRAIN      # captured opponent's face-card trump

    penalty = 0.0
    for card in sim.piles[opp_index]:
        if card in initial_hand and card.points >= 10:
            penalty += _OWN_LOSS_PEN   # we lost one of our own Aces or 3s

    return base + bonus - penalty


# ---------------------------------------------------------------------------
# Predatory bias
# ---------------------------------------------------------------------------

def _predatory_bias(
    scores: List[float],
    hand: List[Card],
    game: BriscolaGame,
    bot_index: int,
) -> None:
    """
    Apply small additive biases to MC scores based on card counting.
    These never override a clear MC signal; they only resolve near-ties.

    Biases applied:
    • Leading a non-precious trump (flushes opponent's trump hand)
    • Leading a suit with high exhaustion (opponent probably can't follow)
    • NOT leading our own Ace/3 when other leads are available
    """
    trump   = game.trump_suit
    unknown = game.unknown_cards(bot_index)

    # Suit exhaustion: how many of each suit have been seen already
    # High exhaustion → opponent is likely low in that suit → safe lead
    suit_seen: dict = {}
    for c in game.seen_cards:
        suit_seen[c.suit] = suit_seen.get(c.suit, 0) + 1

    # Are there still opponent high-value trump cards floating?
    opp_high_trump_unknown = [
        c for c in unknown
        if c.suit == trump and c.points >= 10
    ]
    opp_trump_unknown = [c for c in unknown if c.suit == trump]
    total_unknown = len(unknown)
    opp_hand_size = len(game.hands[1 - bot_index])

    # P(opponent holds at least one non-high trump) — for flush bias
    p_opp_has_trump = _p_at_least_one(
        total_unknown, len(opp_trump_unknown), opp_hand_size
    )

    precious_in_hand = [i for i, c in enumerate(hand) if _is_precious_trump(c, trump)]
    non_precious_available = len(precious_in_hand) < len(hand)

    for i, card in enumerate(hand):
        # Protect our own Ace/3 — don't lead them when other options exist
        if _is_precious_trump(card, trump) and non_precious_available:
            scores[i] -= _PROTECT_BIAS

        # Flush bias: lead a non-precious trump to drain their trump hand
        if (card.suit == trump
                and not _is_precious_trump(card, trump)
                and p_opp_has_trump > 0.3):
            scores[i] += _FLUSH_BIAS

        # Suit exhaustion hunt: lead suits the opponent is likely dry in
        exhaustion = suit_seen.get(card.suit, 0)
        if exhaustion >= 4 and card.suit != trump:
            # This suit is heavily depleted — a safe probe lead
            scores[i] += _HUNT_BIAS * (exhaustion / 10.0)


def _p_at_least_one(
    total_unknown: int,
    target_unknown: int,
    draw_size: int,
) -> float:
    """
    Hypergeometric: P(opponent holds ≥1 card from a target set of size
    `target_unknown`, given `total_unknown` unknown cards and opponent
    holds `draw_size` of them).
    """
    if total_unknown == 0 or draw_size == 0 or target_unknown == 0:
        return 0.0
    non_target = total_unknown - target_unknown
    if non_target < 0:
        return 1.0
    draw_size = min(draw_size, total_unknown)
    if non_target < draw_size:
        return 1.0
    try:
        p_none = comb(non_target, draw_size) / comb(total_unknown, draw_size)
        return 1.0 - p_none
    except ZeroDivisionError:
        return 0.0
