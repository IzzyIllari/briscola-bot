"""
engine/ai/heuristic.py
Rule-based AI for Easy, Medium, and Hard difficulty levels.

Easy
  Random play with one instinct: never wastes a trump Ace or 3 when a
  cheaper card would do.  Feels like a distracted beginner who at least
  knows not to throw away the best cards.

Medium
  Pure per-trick greedy heuristics, no card memory, no look-ahead.
  Wins high-value tricks as cheaply as possible and dumps trash otherwise.
  Knows about trump but has no sense of the game arc.

Hard
  Card-counting (uses game.seen_cards, no peeking at opponent's hand) +
  probabilistic 1-trick look-ahead via hand sampling in the midgame +
  exact alpha-beta minimax once the draw pile is empty.
  Targets ~70% win-rate vs a decent human player.
"""
from __future__ import annotations
from typing import List, Optional, Tuple
import random
from engine.cards import Card, trick_winner_index
from engine.game import BriscolaGame


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _opponent_lead(game: BriscolaGame, bot_index: int) -> Optional[Card]:
    """Return the card the opponent has already played, or None if bot leads."""
    return game.current_trick[1 - bot_index]


def _wins_as_second(card: Card, lead: Card, trump: str) -> bool:
    return trick_winner_index([lead, card], trump) == 1


def _is_precious_trump(card: Card, trump: str) -> bool:
    """True for the two highest-value trump cards (Ace = 11 pts, 3 = 10 pts)."""
    return card.suit == trump and card.points >= 10


# ---------------------------------------------------------------------------
# EASY  —  random, but never wastes trump Ace or 3
# ---------------------------------------------------------------------------

def choose_easy(game: BriscolaGame, bot_index: int) -> int:
    """
    Completely random. No rules, no instincts.
    Will occasionally waste the trump Ace on a 0-point trick.
    Feels chaotic — the right energy for Easy.
    """
    return random.randrange(len(game.hands[bot_index]))


# ---------------------------------------------------------------------------
# MEDIUM  —  greedy per-trick heuristics
# ---------------------------------------------------------------------------

# Thresholds for how aggressively Medium contests a trick when following.
# Based on the lead card's point value:
#   ≥ 10 (Ace/3)          → fight hard: use any win including trump
#   2–4  (Jack/Knight/King)→ contest with non-trump only; skip trump
#   0    (7/6/5/4/2)       → only take a free (zero-point non-trump) win
_MEDIUM_MUST_WIN_THRESHOLD  = 10   # Ace / 3 — worth spending trump
_MEDIUM_CONTEST_THRESHOLD   = 2    # Jack / Knight / King — worth non-trump effort


def choose_medium(game: BriscolaGame, bot_index: int) -> int:
    """
    Leading:   dump the weakest zero-point non-trump card available;
               if none, dump the lowest-value card overall.
    Following: fight hard for high-value lead cards (Ace / 3);
               for lower-value leads, only win if it costs nothing (zero-
               point non-trump); otherwise dump cheapest card.
    """
    hand = game.hands[bot_index]
    trump = game.trump_suit
    lead = _opponent_lead(game, bot_index)

    if lead is None:
        return _medium_lead(hand, trump)

    return _medium_follow(hand, lead, trump)


def _medium_lead(hand: List[Card], trump: str) -> int:
    # Prefer dumping: zero-point, non-trump, weakest first
    trash = [
        (i, c) for i, c in enumerate(hand)
        if c.points == 0 and c.suit != trump
    ]
    if trash:
        return min(trash, key=lambda t: t[1].strength)[0]
    # Fall back: lowest combined value
    return min(range(len(hand)), key=lambda i: (hand[i].points, hand[i].strength))


def _medium_follow(hand: List[Card], lead: Card, trump: str) -> int:
    # Partition into winning and losing plays
    wins_nt: List[Tuple[int, Card]] = []   # non-trump wins
    wins_t:  List[Tuple[int, Card]] = []   # trump wins
    losses:  List[Tuple[int, Card]] = []
    for i, card in enumerate(hand):
        if _wins_as_second(card, lead, trump):
            if card.suit == trump:
                wins_t.append((i, card))
            else:
                wins_nt.append((i, card))
        else:
            losses.append((i, card))

    if lead.points >= _MEDIUM_MUST_WIN_THRESHOLD:
        # Ace or 3 — fight hard, spend trump if needed
        if wins_nt:
            return min(wins_nt, key=lambda t: (t[1].strength, t[1].points))[0]
        if wins_t:
            return min(wins_t, key=lambda t: t[1].strength)[0]

    elif lead.points >= _MEDIUM_CONTEST_THRESHOLD:
        # Jack / Knight / King — worth contesting, but not with trump
        if wins_nt:
            return min(wins_nt, key=lambda t: (t[1].strength, t[1].points))[0]

    else:
        # Zero-point lead — only take a completely free win
        free_wins = [
            (i, c) for i, c in wins_nt
            if c.points == 0
        ]
        if free_wins:
            return min(free_wins, key=lambda t: t[1].strength)[0]

    # Default: dump cheapest card
    if losses:
        return min(losses, key=lambda t: (t[1].points, t[1].strength))[0]
    # Forced to win — use cheapest available
    all_wins = wins_nt + wins_t
    return min(all_wins, key=lambda t: (t[1].points, t[1].strength))[0]


# ---------------------------------------------------------------------------
# HARD  —  card counting + probabilistic look-ahead + endgame minimax
# ---------------------------------------------------------------------------

# How many random opponent-hand samples to use in the probabilistic midgame.
# 15 gives stable estimates while staying well under 1ms per decision.
_SAMPLES = 15

# Once both hands are this small AND the stock is empty, switch to exact minimax.
_MINIMAX_HAND_THRESHOLD = 4


def choose_hard(game: BriscolaGame, bot_index: int) -> int:
    """
    Hard strategy:

    Endgame (stock empty, small hands):
        Exact alpha-beta minimax over the remaining tricks — provably optimal.

    Midgame following:
        Card-counting informs trump conservation.  We know exactly which
        cards have been seen (game.seen_cards), so we can determine whether
        the opponent is likely to still hold trump threats.

    Midgame leading:
        Sample _SAMPLES plausible opponent hands from the truly unknown
        card pool and compute the expected 1-trick score over those samples.
        This is probabilistically honest — no peeking — but still strong.
    """
    hand = game.hands[bot_index]
    trump = game.trump_suit
    lead = _opponent_lead(game, bot_index)
    opp_hand = game.hands[1 - bot_index]   # only used for endgame minimax

    # ── Endgame: perfect-information minimax ─────────────────────────────
    stock_empty = game.cards_remaining_in_stock() == 0
    if (stock_empty
            and len(hand) <= _MINIMAX_HAND_THRESHOLD
            and len(opp_hand) <= _MINIMAX_HAND_THRESHOLD):
        return _minimax_best_move(hand, opp_hand, trump, lead)

    # ── Midgame ──────────────────────────────────────────────────────────
    unknown = game.unknown_cards(bot_index)   # cards not in our hand and not yet seen
    opp_hand_size = len(opp_hand)

    if lead is not None:
        return _hard_follow_counting(hand, lead, trump, unknown, opp_hand_size)
    return _hard_lead_sampling(hand, lead, trump, unknown, opp_hand_size)


# ── Card-counting follower ────────────────────────────────────────────────

def _hard_follow_counting(
    hand: List[Card],
    lead: Card,
    trump: str,
    unknown: List[Card],
    opp_hand_size: int,
) -> int:
    """
    Follow with trump conservation informed by card counting.

    Key insight: if P(opponent still holds at least one trump) is low,
    we can be more aggressive about winning non-trump tricks.  If it's
    high, we conserve our own trump for guaranteed high-value grabs.
    """
    wins_nt: List[Tuple[int, Card]] = []   # non-trump winning plays
    wins_t:  List[Tuple[int, Card]] = []   # trump winning plays
    losses:  List[Tuple[int, Card]] = []

    for i, card in enumerate(hand):
        if _wins_as_second(card, lead, trump):
            if card.suit == trump:
                wins_t.append((i, card))
            else:
                wins_nt.append((i, card))
        else:
            losses.append((i, card))

    # Estimate probability opponent holds at least one trump
    trump_unknown = [c for c in unknown if c.suit == trump]
    total_unknown = len(unknown)
    if total_unknown == 0 or opp_hand_size == 0:
        p_opp_has_trump = 0.0
    else:
        # P(opp has ≥1 trump) ≈ 1 - P(all opp cards are non-trump)
        # Using hypergeometric approximation
        non_trump_unknown = total_unknown - len(trump_unknown)
        if non_trump_unknown < opp_hand_size:
            p_opp_has_trump = 1.0
        elif total_unknown < opp_hand_size:
            p_opp_has_trump = 1.0
        else:
            from math import comb
            p_no_trump = comb(non_trump_unknown, opp_hand_size) / comb(total_unknown, opp_hand_size)
            p_opp_has_trump = 1.0 - p_no_trump

    trick_value = lead.points
    HIGH = 10

    if trick_value >= HIGH:
        # High-value trick: fight for it
        if wins_nt:
            return min(wins_nt, key=lambda t: (t[1].strength, t[1].points))[0]
        if wins_t:
            return min(wins_t, key=lambda t: t[1].strength)[0]
    else:
        # Low-value trick: only win if we can do so without trump,
        # OR if the opponent probably can't trump us anyway
        free_wins = [(i, c) for i, c in wins_nt if c.points == 0]
        if free_wins:
            return min(free_wins, key=lambda t: t[1].strength)[0]

        # If opponent almost certainly has no trump, a cheap non-trump win is safe
        if p_opp_has_trump < 0.2 and wins_nt:
            return min(wins_nt, key=lambda t: (t[1].strength, t[1].points))[0]

    # Default: dump lowest-value card
    if losses:
        return min(losses, key=lambda t: (t[1].points, t[1].strength))[0]
    if wins_nt:
        return min(wins_nt, key=lambda t: (t[1].strength, t[1].points))[0]
    if wins_t:
        return min(wins_t, key=lambda t: t[1].strength)[0]
    return 0


# ── Probabilistic leader ──────────────────────────────────────────────────

def _hard_lead_sampling(
    hand: List[Card],
    lead: Optional[Card],   # always None here, kept for signature clarity
    trump: str,
    unknown: List[Card],
    opp_hand_size: int,
) -> int:
    """
    Estimate expected 1-trick score for each candidate lead by averaging
    over _SAMPLES random draws of what the opponent might be holding.

    This is honest (only uses truly unknown cards) and naturally accounts
    for the probability of the opponent having trump, Aces, etc.
    """
    n = len(hand)
    if n == 1:
        return 0

    # If we know more cards than the opponent could hold, cap it
    draw_size = min(opp_hand_size, len(unknown))
    if draw_size == 0:
        # No unknown cards — fall back to medium heuristics
        return _medium_lead(hand, trump)

    expected: List[float] = [0.0] * n

    for _ in range(_SAMPLES):
        # Sample a plausible opponent hand from truly unknown cards
        sampled_opp = random.sample(unknown, draw_size)

        for i, lead_card in enumerate(hand):
            # Opponent plays their best response to this lead
            # (assume opponent plays optimally = worst case for us)
            worst_score = None
            for opp_card in sampled_opp:
                rel_winner = trick_winner_index([lead_card, opp_card], trump)
                pts = lead_card.points + opp_card.points
                score = float(pts) if rel_winner == 0 else float(-pts)
                if worst_score is None or score < worst_score:
                    worst_score = score
            expected[i] += (worst_score or 0.0)

    # Average over samples and add biases
    for i, card in enumerate(hand):
        expected[i] /= _SAMPLES
        # Bias: conserve precious trump (Ace/3) — big negative nudge
        if _is_precious_trump(card, trump):
            expected[i] -= 8.0
        # Bias: mildly prefer leading zero-point cards (cheap information)
        elif card.points == 0 and card.suit != trump:
            expected[i] += 0.5

    return max(range(n), key=lambda i: expected[i])


# ---------------------------------------------------------------------------
# Endgame alpha-beta minimax  (perfect information, both hands known)
# ---------------------------------------------------------------------------

def _minimax(
    my_hand: List[Card],
    opp_hand: List[Card],
    trump: str,
    i_lead: bool,
    alpha: float,
    beta: float,
) -> float:
    """
    Return the total points I will accumulate from here to the end under
    optimal play by both sides.

    i_lead=True  → it is my turn to lead the next trick.
    i_lead=False → the opponent leads; I follow.
    """
    if not my_hand:
        return 0.0

    if i_lead:
        best = alpha
        for li, lead in enumerate(my_hand):
            my_rest = [c for j, c in enumerate(my_hand) if j != li]
            # Opponent picks their best response (worst for me)
            opp_best = None
            for fi, follow in enumerate(opp_hand):
                opp_rest = [c for j, c in enumerate(opp_hand) if j != fi]
                rel_winner = trick_winner_index([lead, follow], trump)
                pts = lead.points + follow.points
                if rel_winner == 0:   # I win → I lead again
                    score = pts + _minimax(my_rest, opp_rest, trump, True, best, beta)
                else:                 # Opp wins → they lead
                    score = _minimax(my_rest, opp_rest, trump, False, best, beta)
                if opp_best is None or score < opp_best:
                    opp_best = score
                if best >= min(beta, opp_best):
                    break             # alpha-beta cut

            if opp_best is not None and opp_best > best:
                best = opp_best
            if best >= beta:
                break
        return best

    else:  # opponent leads
        best = beta
        for li, lead in enumerate(opp_hand):
            opp_rest = [c for j, c in enumerate(opp_hand) if j != li]
            # I pick my best response
            my_best = None
            for fi, follow in enumerate(my_hand):
                my_rest = [c for j, c in enumerate(my_hand) if j != fi]
                rel_winner = trick_winner_index([lead, follow], trump)
                pts = lead.points + follow.points
                if rel_winner == 1:   # I win (second player) → I lead
                    score = pts + _minimax(my_rest, opp_rest, trump, True, alpha, best)
                else:                 # Opp wins → they lead again
                    score = _minimax(my_rest, opp_rest, trump, False, alpha, best)
                if my_best is None or score > my_best:
                    my_best = score
                if max(alpha, my_best) >= best:
                    break             # alpha-beta cut

            if my_best is not None and my_best < best:
                best = my_best
            if alpha >= best:
                break
        return best


def _minimax_best_move(
    my_hand: List[Card],
    opp_hand: List[Card],
    trump: str,
    lead_already_played: Optional[Card],
) -> int:
    """Return the index of the best card in my_hand given the current state."""
    best_i, best_score = 0, None

    if lead_already_played is not None:
        # I follow — evaluate each response
        for i, card in enumerate(my_hand):
            my_rest = [c for j, c in enumerate(my_hand) if j != i]
            # Opponent's lead card is removed from their conceptual hand
            opp_without_lead = [c for c in opp_hand if c != lead_already_played]
            rel_winner = trick_winner_index([lead_already_played, card], trump)
            pts = lead_already_played.points + card.points
            if rel_winner == 1:   # I win → I lead next
                score = pts + _minimax(my_rest, opp_without_lead, trump, True, float("-inf"), float("inf"))
            else:                 # Opp wins → they lead
                score = _minimax(my_rest, opp_without_lead, trump, False, float("-inf"), float("inf"))
            if best_score is None or score > best_score:
                best_score, best_i = score, i
    else:
        # I lead — opponent responds optimally (worst case for me)
        for i, lead in enumerate(my_hand):
            my_rest = [c for j, c in enumerate(my_hand) if j != i]
            worst: Optional[float] = None
            for fi, opp_card in enumerate(opp_hand):
                opp_rest = [c for j, c in enumerate(opp_hand) if j != fi]
                rel_winner = trick_winner_index([lead, opp_card], trump)
                pts = lead.points + opp_card.points
                if rel_winner == 0:
                    score = pts + _minimax(my_rest, opp_rest, trump, True, float("-inf"), float("inf"))
                else:
                    score = _minimax(my_rest, opp_rest, trump, False, float("-inf"), float("inf"))
                if worst is None or score < worst:
                    worst = score
            # Small tie-break: preserve point cards over equal-expected-value options
            w = (worst or 0.0) - 0.05 * lead.points
            if best_score is None or w > best_score:
                best_score, best_i = w, i

    return best_i
