"""
cogs/hand_cog.py
/briscola_hand  — ephemeral card display + dropdown to play a card.
/briscola_status — public game-state embed.
"""
from __future__ import annotations
import time
from typing import List, Optional
import discord
from discord.ext import commands
from discord import app_commands
from sessions import registry
from views.hand_view import HandView
from game_flow import seat_mention


class HandCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------
    # /briscola_hand
    # ------------------------------------------------------------------

    @app_commands.command(
        name="briscola_hand",
        description="View your hand (private) and choose a card to play.",
    )
    async def hand(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Use this in a server text channel.", ephemeral=True
            )
            return

        session = registry.get(channel.id)
        if session is None:
            await interaction.response.send_message(
                "No active Briscola game in this channel.", ephemeral=True
            )
            return

        seat = session.slot_for_user(interaction.user.id)
        if seat is None:
            await interaction.response.send_message(
                "You're not part of the current game.", ephemeral=True
            )
            return

        game = session.game
        cfg = game.deck_config
        hand = game.hands[seat]

        if not hand:
            await interaction.response.send_message("Your hand is empty.", ephemeral=True)
            return

        # Build hand description (trump cards flagged)
        trump = game.trump_suit
        lines: List[str] = []
        for i, card in enumerate(hand):
            trump_marker = " 🌟 *(trump)*" if card.suit == trump else ""
            lines.append(
                f"`{i+1}.` **{cfg.short(card)}** "
                f"— {card.rank} of {card.suit}  ·  {card.points} pts{trump_marker}"
            )
        hand_text = "\n".join(lines)

        # Card image embeds (Discord allows up to 10 embeds but 3 is cleaner)
        embeds: List[discord.Embed] = []
        for card in hand[:3]:
            url = cfg.image_url(card)
            if url:
                e = discord.Embed(description=cfg.short(card), color=0x2F3136)
                e.set_image(url=url)
                embeds.append(e)

        # Sync view timeout with remaining turn time
        view_timeout = 150.0
        if session.turn_deadline:
            view_timeout = max(10.0, min(150.0, session.turn_deadline - time.time()))

        view = HandView(session, seat=seat, timeout=view_timeout)

        await interaction.response.send_message(
            content=(
                f"**Your hand:**\n{hand_text}\n\n"
                "Select a card from the dropdown to play it:"
            ),
            view=view,
            embeds=embeds if embeds else None,
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # /briscola_status
    # ------------------------------------------------------------------

    @app_commands.command(
        name="briscola_status",
        description="Show the current game state in this channel.",
    )
    async def status(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Use this in a server text channel.", ephemeral=True
            )
            return

        session = registry.get(channel.id)
        challenge = registry.get_challenge(channel.id)

        if session is None and challenge is None:
            await interaction.response.send_message(
                "No active game or pending challenge in this channel.", ephemeral=True
            )
            return

        # ---- Pending challenge ----
        if session is None:
            assert challenge is not None
            challenger = channel.guild.get_member(challenge.challenger_id)
            opponent = channel.guild.get_member(challenge.opponent_id)
            remaining = max(0, int(challenge.created_at + 300 - time.time()))
            embed = discord.Embed(title="⚔️ Pending Challenge", color=0xF39C12)
            embed.add_field(
                name="Challenger",
                value=challenger.mention if challenger else str(challenge.challenger_id),
            )
            embed.add_field(
                name="Opponent",
                value=opponent.mention if opponent else str(challenge.opponent_id),
            )
            embed.add_field(name="Deck", value=challenge.deck_name.capitalize())
            embed.add_field(name="Expires in", value=f"{remaining}s")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # ---- Active game ----
        game = session.game
        cfg = game.deck_config
        pts = game.points
        current_seat = game.turn
        current_mention = seat_mention(channel.guild, session, current_seat)

        embed = discord.Embed(title="🃏 Briscola — Game Status", color=0x3498DB)
        embed.add_field(name="Mode", value=session.mode)
        embed.add_field(name="Deck", value=cfg.label)
        embed.add_field(name="Trump suit", value=game.trump_suit)
        embed.add_field(name="Cards in stock", value=str(game.cards_remaining_in_stock()))
        embed.add_field(name="Current turn", value=current_mention, inline=False)

        for seat_i, slot in enumerate(session.slots):
            mention = seat_mention(channel.guild, session, seat_i)
            hand_size = len(game.hands[seat_i])
            embed.add_field(
                name=mention,
                value=f"{pts[seat_i]} pts  ·  {hand_size} cards in hand",
            )

        if session.turn_deadline:
            remaining = max(0, int(session.turn_deadline - time.time()))
            embed.set_footer(text=f"Current turn expires in {remaining}s")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HandCog(bot))
