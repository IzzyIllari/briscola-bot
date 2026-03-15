"""
cogs/game_cog.py
Slash commands for starting, accepting, declining, and ending games.
All game-flow logic lives in game_flow.py; this file is pure Discord plumbing.
"""
from __future__ import annotations
import discord
from discord.ext import commands
from discord import app_commands
from engine.cards import DECK_REGISTRY, DEFAULT_DECK_CONFIG
from engine.game import BriscolaGame
from engine.ai import VALID_DIFFICULTIES
from sessions import GameSession, PlayerSlot, PendingChallenge, registry
from game_flow import show_trump, announce_next_turn, seat_mention
from config import (
    DEFAULT_DIFFICULTY, DEFAULT_DECK,
    CHALLENGE_TIMEOUT_SECONDS,
)


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

_RULES_TEXT = """\
**Briscola: How to Play**

**The deck**
40 cards, 4 suits: Denari (♦), Coppe (♥), Spade (♠), Bastoni (♣).
Rank order, strongest first: `A  3  R  C  F  7  6  5  4  2`

**Points per card**
```
Ace  (A) = 11     King   (R) = 4
Three(3) = 10     Knight (C) = 3
                  Jack   (F) = 2
7 through 2 = 0 each     Total in deck = 120
```

**Setup**
Deal 3 cards to each player. Flip the next card face-up next to the deck. That card's suit is the **Briscola** (trump) for the whole game.

**On your turn**
Play one card. No follow-suit rule; you can play anything from your hand.

**Who wins the trick**
1. Highest trump card, if any trump was played
2. Otherwise, highest card in the lead suit
3. Off-suit, non-trump cards never win

**Drawing**
After each trick, both players draw one card (winner first) until the deck is gone. The face-up trump card is drawn last.

**Winning**
First to 61+ points wins. 60-60 is a tie.\
"""

_DIFFICULTY_TEXT = """\
**Bot Difficulty Levels**

`easy`
Plays a random card every turn. No strategy at all. Will throw its trump Ace into a 0-point trick without hesitation.

`medium`
Greedy heuristics. Contests any trick with a pointed lead card, dumps trash when leading. No card memory.

`hard`
Tracks every card played. Uses probabilistic look-ahead in the midgame by sampling possible opponent hands from the unseen card pool. Switches to exact alpha-beta minimax once the draw pile empties. Does not cheat or peek at your hand.

`extreme`
Monte Carlo with 100 simulations per candidate card. The reward function specifically bonuses capturing your Ace and 3, and penalizes losing its own. Reads suit exhaustion from played cards and leads into suits you're likely dry in. Switches to exact minimax at endgame. It will hunt you.\
"""

_DECKS_TEXT = """\
**Available Decks**

`piacentine` (default) - Piacentine regional deck, Northern Italy
`napoletane` - Napoletane regional deck, Naples
`siciliane` - Siciliane regional deck, Sicily
`romagnole` - Romagnole regional deck, Emilia-Romagna
`triestine` - Triestine regional deck, Trieste

All decks use the same rules and rank structure. The artwork is different. Piacentine images are live now; others coming as art gets added.

Pick a deck when starting a game:
`/briscola_vs_bot deck:napoletane`
`/briscola_1v1 deck:siciliane`\
"""


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class GameCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------
    # /briscola_vs_bot
    # ------------------------------------------------------------------

    @app_commands.command(
        name="briscola_vs_bot",
        description="Start a Briscola game against the bot.",
    )
    @app_commands.describe(
        difficulty="easy / medium / hard / extreme  (default: medium)",
        deck="piacentine / napoletane / siciliane / romagnole / triestine",
    )
    async def vs_bot(
        self,
        interaction: discord.Interaction,
        difficulty: str = DEFAULT_DIFFICULTY,
        deck: str = DEFAULT_DECK,
    ) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Use this in a server text channel.", ephemeral=True
            )
            return
        if registry.get(channel.id):
            await interaction.response.send_message(
                "A game is already running in this channel.", ephemeral=True
            )
            return

        difficulty = difficulty.lower()
        if difficulty not in VALID_DIFFICULTIES:
            await interaction.response.send_message(
                f"Invalid difficulty. Options: {', '.join(VALID_DIFFICULTIES)}",
                ephemeral=True,
            )
            return

        deck = deck.lower()
        cfg = DECK_REGISTRY.get(deck)
        if cfg is None:
            await interaction.response.send_message(
                f"Invalid deck. Options: {', '.join(DECK_REGISTRY)}",
                ephemeral=True,
            )
            return

        game = BriscolaGame(deck_config=cfg)
        slots = [
            PlayerSlot(user_id=interaction.user.id, is_bot=False),
            PlayerSlot(user_id=0, is_bot=True),
        ]
        session = GameSession(
            channel_id=channel.id,
            guild_id=interaction.guild_id,
            mode="vs_bot",
            game=game,
            slots=slots,
            bot_difficulty=difficulty,
        )
        registry.add(session)

        embed = discord.Embed(title="🃏 Briscola vs Bot", color=0x2ECC71)
        embed.add_field(name="Player", value=interaction.user.mention)
        embed.add_field(name="Difficulty", value=difficulty.capitalize())
        embed.add_field(name="Deck", value=cfg.label)
        embed.add_field(name="Trump suit", value=game.trump_suit)
        embed.set_footer(text="Use /briscola_hand on your turn.")
        await interaction.response.send_message(embed=embed)
        await show_trump(channel, session)
        await announce_next_turn(channel, session)

    # ------------------------------------------------------------------
    # /briscola_1v1  /briscola_accept  /briscola_decline
    # ------------------------------------------------------------------

    @app_commands.command(
        name="briscola_1v1",
        description="Challenge another player to a 1v1 Briscola game.",
    )
    @app_commands.describe(
        opponent="The player you want to challenge.",
        deck="piacentine / napoletane / siciliane / romagnole / triestine",
    )
    async def challenge(
        self,
        interaction: discord.Interaction,
        opponent: discord.Member,
        deck: str = DEFAULT_DECK,
    ) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Use this in a server text channel.", ephemeral=True
            )
            return
        if registry.get(channel.id) or registry.get_challenge(channel.id):
            await interaction.response.send_message(
                "A game or pending challenge already exists here.", ephemeral=True
            )
            return
        if opponent.id == interaction.user.id:
            await interaction.response.send_message("You can't challenge yourself.", ephemeral=True)
            return
        if opponent.bot:
            await interaction.response.send_message(
                "To play against the bot, use `/briscola_vs_bot`.", ephemeral=True
            )
            return

        deck = deck.lower()
        if deck not in DECK_REGISTRY:
            await interaction.response.send_message(
                f"Invalid deck. Options: {', '.join(DECK_REGISTRY)}", ephemeral=True
            )
            return

        challenge = PendingChallenge(
            channel_id=channel.id,
            guild_id=interaction.guild_id,
            challenger_id=interaction.user.id,
            opponent_id=opponent.id,
            deck_name=deck,
        )
        registry.add_challenge(challenge)

        timeout_min = CHALLENGE_TIMEOUT_SECONDS // 60
        await interaction.response.send_message(
            f"⚔️ {interaction.user.mention} challenges {opponent.mention} to Briscola!\n"
            f"**Deck:** {DECK_REGISTRY[deck].label}\n"
            f"{opponent.mention}: use `/briscola_accept` to accept "
            f"or `/briscola_decline` to decline.\n"
            f"This challenge expires in {timeout_min} minutes.",
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    @app_commands.command(
        name="briscola_accept",
        description="Accept a pending 1v1 Briscola challenge in this channel.",
    )
    async def accept(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Use this in a server text channel.", ephemeral=True
            )
            return
        if registry.get(channel.id):
            await interaction.response.send_message(
                "A game is already running here.", ephemeral=True
            )
            return

        challenge = registry.get_challenge(channel.id)
        if challenge is None:
            await interaction.response.send_message(
                "No pending challenge in this channel.", ephemeral=True
            )
            return
        if interaction.user.id != challenge.opponent_id:
            await interaction.response.send_message(
                "Only the challenged player can accept.", ephemeral=True
            )
            return
        if challenge.is_expired(CHALLENGE_TIMEOUT_SECONDS):
            registry.remove_challenge(channel.id)
            await interaction.response.send_message(
                "That challenge has expired. Ask the challenger to send a new one.",
                ephemeral=True,
            )
            return

        cfg = DECK_REGISTRY.get(challenge.deck_name, DEFAULT_DECK_CONFIG)
        game = BriscolaGame(deck_config=cfg)
        slots = [
            PlayerSlot(user_id=challenge.challenger_id, is_bot=False),
            PlayerSlot(user_id=challenge.opponent_id, is_bot=False),
        ]
        session = GameSession(
            channel_id=channel.id,
            guild_id=interaction.guild_id,
            mode="1v1",
            game=game,
            slots=slots,
        )
        registry.add(session)
        registry.remove_challenge(channel.id)

        challenger = channel.guild.get_member(challenge.challenger_id)
        embed = discord.Embed(title="⚔️ Briscola 1v1", color=0xE74C3C)
        embed.add_field(
            name="Players",
            value=(
                f"{challenger.mention if challenger else challenge.challenger_id} "
                f"vs {interaction.user.mention}"
            ),
            inline=False,
        )
        embed.add_field(name="Deck", value=cfg.label)
        embed.add_field(name="Trump suit", value=game.trump_suit)
        embed.set_footer(text="Use /briscola_hand on your turn.")
        await interaction.response.send_message(embed=embed)
        await show_trump(channel, session)
        await announce_next_turn(channel, session)

    @app_commands.command(
        name="briscola_decline",
        description="Decline or cancel a pending Briscola challenge.",
    )
    async def decline(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Use this in a server text channel.", ephemeral=True
            )
            return
        challenge = registry.get_challenge(channel.id)
        if challenge is None:
            await interaction.response.send_message(
                "No pending challenge here.", ephemeral=True
            )
            return
        if interaction.user.id not in {challenge.challenger_id, challenge.opponent_id}:
            await interaction.response.send_message(
                "Only the challenger or challenged player can cancel.", ephemeral=True
            )
            return
        registry.remove_challenge(channel.id)
        await interaction.response.send_message("Challenge cancelled.", ephemeral=True)
        await channel.send(
            f"❌ Briscola challenge cancelled by {interaction.user.mention}."
        )

    # ------------------------------------------------------------------
    # /briscola_end
    # ------------------------------------------------------------------

    @app_commands.command(
        name="briscola_end",
        description="Force-end the current Briscola game in this channel.",
    )
    async def end_game(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "Use this in a server text channel.", ephemeral=True
            )
            return
        session = registry.get(channel.id)
        if session is None:
            await interaction.response.send_message(
                "No active game here.", ephemeral=True
            )
            return
        registry.cancel_timeout(session)
        registry.remove(channel.id)
        await interaction.response.send_message("Game ended.", ephemeral=True)
        await channel.send(
            f"🚫 Briscola game ended by {interaction.user.mention}."
        )

    # ------------------------------------------------------------------
    # /briscola_help
    # ------------------------------------------------------------------

    @app_commands.command(
        name="briscola_help",
        description="Briscola rules, AI difficulty levels, and available decks.",
    )
    @app_commands.describe(section="rules / difficulty / decks / all  (default: all)")
    async def help_cmd(
        self, interaction: discord.Interaction, section: str = "all"
    ) -> None:
        s = section.lower().strip()
        parts = []
        show_deck_preview = False

        if s in ("all", "rules"):
            parts.append(_RULES_TEXT)
        if s in ("all", "difficulty", "difficulties"):
            parts.append(_DIFFICULTY_TEXT)
        if s in ("all", "decks", "deck"):
            parts.append(_DECKS_TEXT)
            show_deck_preview = True
        if not parts:
            parts.append(
                "Unknown section. Options: `rules`, `difficulty`, `decks`, `all`."
            )

        content = "\n\n".join(parts)

        if show_deck_preview:
            # Show the 4 Aces of the default (Piacentine) deck as a visual preview.
            from engine.cards import PIACENTINE
            cfg = PIACENTINE
            all_cards = cfg.build_deck(shuffle=False)
            aces = [c for c in all_cards if c.rank == "A"]
            embeds = []
            for card in aces:
                url = cfg.image_url(card)
                if url:
                    e = discord.Embed(
                        description=f"{cfg.short(card)}  ({card.suit})",
                        color=0xFFD700,
                    )
                    e.set_image(url=url)
                    embeds.append(e)

            if embeds:
                await interaction.response.send_message(
                    content=content, embeds=embeds, ephemeral=True
                )
                return

        await interaction.response.send_message(content=content, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameCog(bot))
