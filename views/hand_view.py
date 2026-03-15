"""
views/hand_view.py
Ephemeral HandView: shows a player's cards and lets them pick one to play.

Trump cards are marked with 🌟 in the dropdown for easy identification.
The view timeout is synced to the session's remaining turn time.
"""
from __future__ import annotations
import time
from typing import TYPE_CHECKING, List
import discord

if TYPE_CHECKING:
    from sessions import GameSession


class HandSelect(discord.ui.Select):
    def __init__(self, session: "GameSession", seat: int):
        self._session = session
        self._seat = seat
        game = session.game
        cfg = game.deck_config
        hand = game.hands[seat]

        if not hand:
            opts = [discord.SelectOption(
                label="No cards", description="Your hand is empty.", value="-1", default=True,
            )]
            super().__init__(placeholder="No cards", options=opts, disabled=True)
            return

        options: List[discord.SelectOption] = []
        for i, card in enumerate(hand):
            trump_flag = " 🌟" if card.suit == game.trump_suit else ""
            options.append(discord.SelectOption(
                label=f"{i+1}. {cfg.short(card)}{trump_flag}",
                description=f"{card.rank} of {card.suit}  ·  {card.points} pts",
                value=str(i),
            ))

        super().__init__(
            placeholder="Choose a card to play…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        # Deferred imports to avoid circular dependency
        from sessions import registry
        from game_flow import handle_after_play, seat_mention

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Must be used in a server text channel.", ephemeral=True
            )
            return

        session = registry.get(channel.id)
        if session is None:
            await interaction.response.send_message(
                "No active game in this channel.", ephemeral=True
            )
            return

        seat = self._seat
        slot = session.slots[seat]

        if interaction.user.id != slot.user_id:
            await interaction.response.send_message(
                "This isn't your hand.", ephemeral=True
            )
            return

        game = session.game
        if game.turn != seat:
            await interaction.response.send_message(
                "It's not your turn yet.", ephemeral=True
            )
            return

        idx = int(self.values[0])
        hand = game.hands[seat]
        if not (0 <= idx < len(hand)):
            await interaction.response.send_message(
                "Invalid card selection.", ephemeral=True
            )
            return

        card = hand[idx]
        cfg = game.deck_config
        game.play_card(seat, idx)
        session.trick_log.append((seat, card))

        # Update the ephemeral message to confirm the play
        await interaction.response.edit_message(
            content=(
                f"✅ You played **{cfg.short(card)}** "
                f"({card.rank} of {card.suit}, {card.points} pts)."
            ),
            view=None,
        )

        # Announce the play publicly in the channel
        desc = f"{interaction.user.mention} plays **{cfg.short(card)}**"
        url = cfg.image_url(card)
        if url:
            embed = discord.Embed(description=desc, color=0x2F3136)
            embed.set_image(url=url)
            await channel.send(embed=embed)
        else:
            await channel.send(desc)

        await handle_after_play(channel, session)


class HandView(discord.ui.View):
    def __init__(self, session: "GameSession", seat: int, *, timeout: float = 150.0):
        super().__init__(timeout=timeout)
        self.add_item(HandSelect(session, seat))
