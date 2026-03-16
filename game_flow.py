"""
game_flow.py
Core async game-flow helpers: turn routing, trick resolution, bot AI turns,
and AFK timeout management.

Lives at the top level so both cogs/ and views/ can import from here
without any circular dependency.
"""
from __future__ import annotations
import asyncio
import time
from typing import TYPE_CHECKING
import discord
from engine.cards import trick_winner_index, trick_points
from engine.ai import choose_card
from sessions import registry, GameSession
from config import TURN_TOTAL_SECONDS, TURN_WARNING_SECONDS, DEFAULT_DIFFICULTY
from db.database import record_game_result

if TYPE_CHECKING:
    pass  # avoid heavy imports at type-check time only


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def seat_mention(guild: discord.Guild, session: GameSession, seat: int) -> str:
    return session.slots[seat].mention_str(guild)


async def show_trump(channel: discord.TextChannel, session: GameSession) -> None:
    """Post the trump suit + trump card image (if the card is still on the table)."""
    game = session.game
    cfg = game.deck_config
    card = game.trump_card

    if card is None:
        await channel.send(
            f"🌟 Trump suit: **{game.trump_suit}** *(trump card already drawn)*"
        )
        return

    text = f"🌟 Trump (**{game.trump_suit}**) — trump card: **{cfg.short(card)}**"
    url = cfg.image_url(card)
    if url:
        embed = discord.Embed(description=text, color=0xFFD700)
        embed.set_image(url=url)
        await channel.send(embed=embed)
    else:
        await channel.send(text)


# ---------------------------------------------------------------------------
# Turn routing
# ---------------------------------------------------------------------------

async def announce_next_turn(
    channel: discord.TextChannel,
    session: GameSession,
) -> None:
    """Decide whether the next player is a human or bot and act accordingly."""
    game = session.game
    seat = game.turn
    slot = session.slots[seat]

    if slot.is_bot:
        registry.cancel_timeout(session)
        await channel.send("🤖 Bot is thinking…")
        await bot_take_turn(channel, session)
    else:
        mention = seat_mention(channel.guild, session, seat)
        await channel.send(
            f"🕑 It's {mention}'s turn. "
            "Use `/briscola_hand` to view your cards and play."
        )
        await _schedule_turn_timeout(channel, session)


async def bot_take_turn(
    channel: discord.TextChannel,
    session: GameSession,
) -> None:
    """Have the bot choose and play a card, then continue the flow."""
    game = session.game
    seat = game.turn
    slot = session.slots[seat]
    if not slot.is_bot or game.is_over():
        return

    hand = game.hands[seat]
    if not hand:
        return

    difficulty = session.bot_difficulty or DEFAULT_DIFFICULTY
    # Run AI in a thread so it doesn't block the event loop (matters for Extreme)
    idx = await asyncio.to_thread(choose_card, game, seat, difficulty)
    card = hand[idx]
    cfg = game.deck_config
    game.play_card(seat, idx)
    session.trick_log.append((seat, card))

    desc = f"🤖 Bot plays **{cfg.short(card)}**"
    url = cfg.image_url(card)
    if url:
        embed = discord.Embed(description=desc, color=0x2F3136)
        embed.set_image(url=url)
        await channel.send(embed=embed)
    else:
        await channel.send(desc)

    await handle_after_play(channel, session)


# ---------------------------------------------------------------------------
# Trick completion and game-over logic
# ---------------------------------------------------------------------------

async def handle_after_play(
    channel: discord.TextChannel,
    session: GameSession,
) -> None:
    """
    Called after every card play (human or bot).
    If the trick is complete, score it and move on; otherwise prompt the
    next player.
    """
    game = session.game
    cfg = game.deck_config
    num_players = len(session.slots)

    if len(session.trick_log) < num_players:
        # Trick not yet complete — prompt next player
        await announce_next_turn(channel, session)
        return

    # ---- Trick complete ----
    played_cards = [card for _, card in session.trick_log]
    rel_winner = trick_winner_index(played_cards, game.trump_suit)
    winner_seat = session.trick_log[rel_winner][0]
    pts = trick_points(played_cards)
    winner_mention = seat_mention(channel.guild, session, winner_seat)

    trick_summary = " · ".join(
        f"{seat_mention(channel.guild, session, s)}: **{cfg.short(c)}**"
        for s, c in session.trick_log
    )
    result_line = f"💥 {winner_mention} wins the trick"
    result_line += (
        f" and scores **{pts}** points!" if pts > 0
        else ". (No points this trick.)"
    )
    await channel.send(f"{result_line}\n{trick_summary}")

    session.trick_log.clear()

    if game.is_over():
        await _announce_game_over(channel, session)
        registry.cancel_timeout(session)
        registry.remove(channel.id)
        return

    await show_trump(channel, session)
    await announce_next_turn(channel, session)


async def _announce_game_over(
    channel: discord.TextChannel,
    session: GameSession,
) -> None:
    game = session.game
    pts = game.points
    w = game.winner()

    score_lines = []
    for seat, slot in enumerate(session.slots):
        mention = seat_mention(channel.guild, session, seat)
        score_lines.append(f"{mention}: **{pts[seat]}** points")

    if w is None:
        result = "🤝 It's a tie!"
    else:
        result = f"🎉 {seat_mention(channel.guild, session, w)} wins!"

    await channel.send(
        "🏁 **Game over!**\n"
        + "\n".join(score_lines)
        + f"\n\n{result}"
    )

    # Persist to leaderboard
    p0 = session.slots[0]
    p1 = session.slots[1]
    winner_user_id: int | None
    if w is None:
        winner_user_id = None
    elif session.slots[w].is_bot:
        winner_user_id = 0   # convention: 0 = bot won
    else:
        winner_user_id = session.slots[w].user_id

    await record_game_result(
        guild_id=session.guild_id,
        channel_id=session.channel_id,
        p0_id=p0.user_id,
        p1_id=0 if p1.is_bot else p1.user_id,
        p0_points=pts[0],
        p1_points=pts[1],
        winner_id=winner_user_id,
        deck_name=game.deck_config.name,
        difficulty=session.bot_difficulty,
    )


# ---------------------------------------------------------------------------
# AFK timeout
# ---------------------------------------------------------------------------

async def _schedule_turn_timeout(
    channel: discord.TextChannel,
    session: GameSession,
) -> None:
    """Start the AFK countdown for the current human player's turn."""
    registry.cancel_timeout(session)
    deadline = time.time() + TURN_TOTAL_SECONDS
    session.turn_deadline = deadline

    async def worker() -> None:
        try:
            # ---- Warning ----
            await asyncio.sleep(TURN_WARNING_SECONDS)
            s = registry.get(channel.id)
            if not s or s.turn_deadline != deadline or s.game.is_over():
                return
            seat = s.game.turn
            mention = seat_mention(channel.guild, s, seat)
            remaining = TURN_TOTAL_SECONDS - TURN_WARNING_SECONDS
            await channel.send(
                f"⏰ {mention}, you have **{remaining}s** left to play or the game will end."
            )

            # ---- Expiry ----
            await asyncio.sleep(remaining)
            s = registry.get(channel.id)
            if not s or s.turn_deadline != deadline or s.game.is_over():
                return
            mention = seat_mention(channel.guild, s, s.game.turn)
            await channel.send(f"⌛ Game ended — {mention} ran out of time.")
            registry.cancel_timeout(s)
            registry.remove(channel.id)

        except asyncio.CancelledError:
            pass  # Normal cancellation when a new turn starts or game ends

    session.turn_timeout_task = asyncio.create_task(worker())
