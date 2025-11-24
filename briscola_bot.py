# briscola_bot.py
import os
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

import discord
from discord.ext import commands
from discord import app_commands

from cards import Card, Suit, short_card, card_image_url, trick_winner_index, trick_points
from engine_2p import BriscolaGame2P
from bot_ai import bot_choose_card


# ======== In-memory game sessions ========

@dataclass
class PlayerSlot:
    user_id: int
    is_bot: bool = False
    team: int = 0  # for future 2v2 support


@dataclass
class GameSession:
    channel_id: int
    mode: str  # "1v1" or "vs_bot" (later "2v2")
    engine: BriscolaGame2P
    slots: List[PlayerSlot]
    bot_difficulty: Optional[str] = None
    # (seat_index, card) in play order for current trick
    trick_cards: List[Tuple[int, Card]] = field(default_factory=list)


sessions: Dict[int, GameSession] = {}


# ======== Discord bot setup ========

intents = discord.Intents.default()
intents.message_content = False  # not needed for slash commands

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        await bot.tree.sync()
        print("Slash commands synced.")
    except Exception as e:
        print("Failed to sync commands:", e)


# ======== Helper functions ========

def get_session(channel_id: int) -> Optional[GameSession]:
    return sessions.get(channel_id)


def find_seat_for_user(session: GameSession, user_id: int) -> Optional[int]:
    for i, slot in enumerate(session.slots):
        if slot.user_id == user_id:
            return i
    return None


def seat_to_mention(channel: discord.TextChannel, session: GameSession, seat: int) -> str:
    slot = session.slots[seat]
    if slot.is_bot:
        return "🤖 Bot"
    member = channel.guild.get_member(slot.user_id)
    return member.mention if member else f"<@{slot.user_id}>"


async def announce_next_turn(channel: discord.TextChannel, session: GameSession):
    engine = session.engine
    seat = engine.turn
    mention = seat_to_mention(channel, session, seat)
    await channel.send(
        f"🕑 It’s now {mention}'s turn. "
        f"Humans: use `/briscola_hand` to see your cards and play."
    )

    slot = session.slots[seat]
    if slot.is_bot and not engine.is_over():
        await bot_take_turn(channel, session)


async def bot_take_turn(channel: discord.TextChannel, session: GameSession):
    engine = session.engine
    seat = engine.turn
    slot = session.slots[seat]
    if not slot.is_bot or engine.is_over():
        return

    hand = engine.hands[seat]
    if not hand:
        return

    difficulty = session.bot_difficulty or "medium"
    idx = bot_choose_card(engine, seat, difficulty=difficulty)
    card = hand[idx]
    engine.play_card(seat, idx)
    session.trick_cards.append((seat, card))

    desc = f"{seat_to_mention(channel, session, seat)} plays **{short_card(card)}**"
    url = card_image_url(card)
    if url:
        embed = discord.Embed(description=desc)
        embed.set_image(url=url)
        await channel.send(embed=embed)
    else:
        await channel.send(desc)

    await handle_after_play(channel, session)


async def handle_after_play(channel: discord.TextChannel, session: GameSession):
    engine = session.engine

    num_players = len(session.slots)
    if len(session.trick_cards) < num_players:
        # Trick not finished yet
        await announce_next_turn(channel, session)
        return

    # Trick completed – announce winner
    played_cards = [card for (_, card) in session.trick_cards]
    trump = engine.trump_suit
    rel_winner = trick_winner_index(played_cards, trump)
    winner_seat = session.trick_cards[rel_winner][0]
    winner_mention = seat_to_mention(channel, session, winner_seat)
    pts = trick_points(played_cards)

    text = f"💥 {winner_mention} wins the trick"
    if pts > 0:
        text += f" and takes **{pts}** points."
    else:
        text += ". (No points in this trick.)"

    trick_desc = " • ".join(
        f"{seat_to_mention(channel, session, seat)}: {short_card(card)}"
        for (seat, card) in session.trick_cards
    )
    text += f"\nCards played: {trick_desc}"

    await channel.send(text)

    session.trick_cards.clear()

    if engine.is_over():
        await announce_game_over(channel, session)
        sessions.pop(session.channel_id, None)
        return

    await announce_next_turn(channel, session)


async def announce_game_over(channel: discord.TextChannel, session: GameSession):
    engine = session.engine
    pts = engine.points

    lines = []
    for seat in range(len(session.slots)):
        mention = seat_to_mention(channel, session, seat)
        lines.append(f"{mention}: **{pts[seat]}** points")

    w = engine.winner()
    if w is None:
        result = "Result: tie (60–60 or both under 61)."
    else:
        winner_mention = seat_to_mention(channel, session, w)
        result = f"Result: {winner_mention} wins! 🎉"

    await channel.send(
        "🏁 **Game over!**\n" + "\n".join(lines) + "\n\n" + result
    )


# ======== UI Components for /briscola_hand ========

class HandSelect(discord.ui.Select):
    def __init__(self, session: GameSession, seat_index: int):
        self.session = session
        self.seat_index = seat_index

        engine = session.engine
        hand = engine.hands[seat_index]

        if not hand:
            options = [
                discord.SelectOption(
                    label="No cards",
                    description="You have no cards to play.",
                    value="-1",
                    default=True,
                )
            ]
            super().__init__(placeholder="No cards", options=options, disabled=True)
            return

        options: List[discord.SelectOption] = []
        for idx, card in enumerate(hand):
            options.append(
                discord.SelectOption(
                    label=f"Card {idx + 1}",
                    description=short_card(card),
                    value=str(idx),
                )
            )

        super().__init__(
            placeholder="Choose a card to play",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "This must be used in a server text channel.",
                ephemeral=True,
            )
            return

        session = get_session(channel.id)
        if session is None:
            await interaction.response.send_message(
                "No Briscola game is running in this channel.",
                ephemeral=True,
            )
            return

        engine = session.engine
        seat = self.seat_index
        slot = session.slots[seat]

        if interaction.user.id != slot.user_id:
            await interaction.response.send_message(
                "This isn’t your hand.",
                ephemeral=True,
            )
            return

        if engine.turn != seat:
            await interaction.response.send_message(
                "It’s not your turn.",
                ephemeral=True,
            )
            return

        idx = int(self.values[0])
        hand = engine.hands[seat]
        if not (0 <= idx < len(hand)):
            await interaction.response.send_message(
                "Invalid card index.",
                ephemeral=True,
            )
            return

        card = hand[idx]
        engine.play_card(seat, idx)
        session.trick_cards.append((seat, card))

        await interaction.response.edit_message(
            content=f"You played **{short_card(card)}**.",
            view=None,
        )

        desc = f"{interaction.user.mention} plays **{short_card(card)}**"
        url = card_image_url(card)
        if url:
            embed = discord.Embed(description=desc)
            embed.set_image(url=url)
            await channel.send(embed=embed)
        else:
            await channel.send(desc)

        await handle_after_play(channel, session)


class HandView(discord.ui.View):
    def __init__(self, session: GameSession, seat_index: int, *, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.add_item(HandSelect(session, seat_index))


# ======== Slash commands ========

@bot.tree.command(name="briscola_1v1", description="Start a 1v1 human vs human Briscola game.")
async def briscola_1v1(interaction: discord.Interaction, opponent: discord.Member):
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "Please start games in a server text channel.",
            ephemeral=True,
        )
        return

    if get_session(channel.id):
        await interaction.response.send_message(
            "A Briscola game is already running in this channel.",
            ephemeral=True,
        )
        return

    if opponent.id == interaction.user.id:
        await interaction.response.send_message(
            "You can’t play against yourself.",
            ephemeral=True,
        )
        return

    engine = BriscolaGame2P(player_ids=[interaction.user.id, opponent.id])
    slots = [
        PlayerSlot(user_id=interaction.user.id, is_bot=False, team=0),
        PlayerSlot(user_id=opponent.id,       is_bot=False, team=1),
    ]
    session = GameSession(
        channel_id=channel.id,
        mode="1v1",
        engine=engine,
        slots=slots,
    )
    sessions[channel.id] = session

    trump = engine.trump_suit
    await interaction.response.send_message(
        f"🃏 **Briscola 1v1** started: {interaction.user.mention} vs {opponent.mention}\n"
        f"Trump suit: **{trump.name}**",
        allowed_mentions=discord.AllowedMentions(users=True),
    )

    await announce_next_turn(channel, session)


@bot.tree.command(name="briscola_vs_bot", description="Start a Briscola game vs the bot.")
@app_commands.describe(difficulty="easy / medium / hard / extreme")
async def briscola_vs_bot(interaction: discord.Interaction, difficulty: str = "medium"):
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "Please start games in a server text channel.",
            ephemeral=True,
        )
        return

    if get_session(channel.id):
        await interaction.response.send_message(
            "A Briscola game is already running in this channel.",
            ephemeral=True,
        )
        return

    difficulty = difficulty.lower()
    if difficulty not in ("easy", "medium", "hard", "extreme"):
        await interaction.response.send_message(
            "Difficulty must be one of: easy, medium, hard, extreme.",
            ephemeral=True,
        )
        return

    engine = BriscolaGame2P(player_ids=[interaction.user.id, "Bot"])
    slots = [
        PlayerSlot(user_id=interaction.user.id, is_bot=False, team=0),
        PlayerSlot(user_id=0,                  is_bot=True,  team=1),
    ]
    session = GameSession(
        channel_id=channel.id,
        mode="vs_bot",
        engine=engine,
        slots=slots,
        bot_difficulty=difficulty,
    )
    sessions[channel.id] = session

    trump = engine.trump_suit
    await interaction.response.send_message(
        f"🤖 **Briscola vs Bot** started for {interaction.user.mention}.\n"
        f"Bot difficulty: **{difficulty}**\n"
        f"Trump suit: **{trump.name}**",
        allowed_mentions=discord.AllowedMentions(users=True),
    )

    await announce_next_turn(channel, session)


@bot.tree.command(name="briscola_hand", description="Show your Briscola hand (ephemeral) and play a card.")
async def briscola_hand(interaction: discord.Interaction):
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "Use this in a server text channel with an active game.",
            ephemeral=True,
        )
        return

    session = get_session(channel.id)
    if session is None:
        await interaction.response.send_message(
            "No Briscola game is running in this channel.",
            ephemeral=True,
        )
        return

    seat = find_seat_for_user(session, interaction.user.id)
    if seat is None:
        await interaction.response.send_message(
            "You’re not part of the current Briscola game in this channel.",
            ephemeral=True,
        )
        return

    engine = session.engine
    hand = engine.hands[seat]
    if not hand:
        await interaction.response.send_message(
            "You have no cards in hand.",
            ephemeral=True,
        )
        return

    lines = [f"{i+1}. {short_card(c)}" for i, c in enumerate(hand)]
    desc = "\n".join(lines)

    view = HandView(session, seat_index=seat)
    await interaction.response.send_message(
        f"Your current hand:\n{desc}\n\n"
        "Choose a card from the dropdown below to play it.",
        view=view,
        ephemeral=True,
    )


@bot.tree.command(name="briscola_end", description="Force-end the Briscola game in this channel.")
async def briscola_end(interaction: discord.Interaction):
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "Use this in a server text channel.",
            ephemeral=True,
        )
        return

    session = get_session(channel.id)
    if session is None:
        await interaction.response.send_message(
            "No Briscola game is running in this channel.",
            ephemeral=True,
        )
        return

    sessions.pop(channel.id, None)
    await interaction.response.send_message(
        "Briscola game in this channel has been ended.",
        ephemeral=True,
    )
    await channel.send("The current Briscola game was ended by a user.")


# ======== Run the bot ========

def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Set DISCORD_TOKEN environment variable with your bot token.")
    bot.run(token)


if __name__ == "__main__":
    main()
