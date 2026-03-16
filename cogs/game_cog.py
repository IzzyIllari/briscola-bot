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

`piacentine` (default) -- Piacenza, Northern Italy
`napoletane` -- Naples, Southern Italy
`siciliane` -- Sicily
`romagnole` -- Emilia-Romagna
`triestine` -- Trieste, Northeast Italy

All five are Spanish-suited Italian regional decks: straight swords, \
cudgel clubs, rounded cups, coin aces. Same 40 cards, same rules, \
different artwork from different corners of Italy.

Use `/briscola_deck` to see the 4 aces and read about any deck before picking.

Start a game with a specific deck:
`/briscola_vs_bot deck:napoletane`
`/briscola_1v1 deck:siciliane`\
"""

# Per-deck descriptions used by /briscola_deck
# Written from research, no AI filler.
_DECK_INFO: dict = {
    "piacentine": (
        "**Piacentine** -- Piacenza, Emilia-Romagna\n\n"
        "The only Spanish-suited deck from Northern Italy. "
        "Piacenza was under Spanish Bourbon rule, but the deck's current form "
        "actually traces to French Aluette cards brought during the late 18th century "
        "occupation -- it then drifted toward its own look over the following hundred years. "
        "One of the two most-played decks in Italy (along with the Napoletane). "
        "The courts are double-headed and reversible, unusual for Italian cards. "
        "The Ace of Swords is held by a cherub; the Ace of Coins carries an eagle. "
        "Straight swords and knotted cudgel clubs mark it as Spanish-style, "
        "which makes it look out of place for a northern deck -- but that's the history."
    ),
    "napoletane": (
        "**Napoletane** -- Naples, Campania\n\n"
        "The most widely used deck across southern and central Italy. "
        "Single-headed court cards, no frames around the card face, "
        "and a handful of distinctive details that players recognize on sight: "
        "the 3 of Clubs has a yellow grotesque face with a large moustache (the Gatto Mammone), "
        "the 5 of Swords shows a small rural scene with figures in the background, "
        "and the Knight of Swords is depicted as a Moorish rider in a turban. "
        "The Ace of Coins has a double-headed eagle. "
        "Cards are slightly shorter than Piacentine. "
        "If you only ever play with one Italian deck, most people in the south would say this one."
    ),
    "siciliane": (
        "**Siciliane** -- Sicily\n\n"
        "The Sicilian deck shares the Spanish-suited structure of the Napoletane "
        "but has its own regional character built up since the early 19th century. "
        "The Ace of Coins features an eagle, similar to the Piacentine, "
        "and the swords have a drop-point blade rather than a straight edge -- "
        "a small but visible difference from the Neapolitan pattern. "
        "All the knights and kings face left instead of right. "
        "Used in Sicily for Briscola, Scopa, and local variants."
    ),
    "romagnole": (
        "**Romagnole** -- Emilia-Romagna\n\n"
        "Played mainly in the provinces of Rimini, Forli-Cesena, Ravenna, Ferrara, "
        "and Imola, and across the border in the Republic of San Marino. "
        "Sits stylistically between the Napoletane and the Piacentine: "
        "the aces follow the Northern Italian look, the cups and swords lean Southern, "
        "and the clubs are nearly identical to Spanish batons. "
        "Full-figure (non-reversible) court cards. "
        "If you drew a line between Naples and Piacenza on a map, "
        "the Romagnole would be somewhere in the middle -- geographically and artistically."
    ),
    "triestine": (
        "**Triestine** -- Trieste, Friuli-Venezia Giulia\n\n"
        "Descends from the old Venice pattern, which held its Italian character "
        "through Austria's occupation of the Veneto. "
        "By around 1850 a distinct Trieste style had emerged, "
        "the most recognizable feature being labeled title banners on the court cards -- "
        "each one names the figure it depicts, which no other Italian regional deck does. "
        "Narrower than most Italian cards, solid colors, minimal shading. "
        "Modiano, the company that makes most Italian regional decks and has been "
        "the official card supplier for the World Series of Poker since 2015, "
        "was founded in Trieste in 1868 -- so this deck is essentially their home turf."
    ),
}


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
        goes_first="you / bot / random  (default: random)",
    )
    async def vs_bot(
        self,
        interaction: discord.Interaction,
        difficulty: str = DEFAULT_DIFFICULTY,
        deck: str = DEFAULT_DECK,
        goes_first: str = "random",
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

        goes_first = goes_first.lower()
        if goes_first not in ("you", "bot", "random"):
            await interaction.response.send_message(
                "goes_first must be: `you`, `bot`, or `random`.",
                ephemeral=True,
            )
            return

        import random as _random
        if goes_first == "you":
            first_player = 0   # human is always slot 0 in vs_bot
            first_label = "You go first."
        elif goes_first == "bot":
            first_player = 1
            first_label = "Bot goes first."
        else:
            first_player = _random.randint(0, 1)
            first_label = "You go first. (coin toss)" if first_player == 0 else "Bot goes first. (coin toss)"

        game = BriscolaGame(deck_config=cfg, first_player=first_player)
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
        embed.add_field(name="First move", value=first_label, inline=False)
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
        import random as _random
        first_player = _random.randint(0, 1)
        game = BriscolaGame(deck_config=cfg, first_player=first_player)
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
        first_mention = (
            (challenger.mention if challenger else str(challenge.challenger_id))
            if first_player == 0
            else interaction.user.mention
        )
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
        embed.add_field(name="First move", value=f"{first_mention} (coin toss)", inline=False)
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
            import asyncio as _asyncio
            from engine.cards import PIACENTINE
            from engine.card_renderer import render_hand
            cfg = PIACENTINE
            all_cards = cfg.build_deck(shuffle=False)
            aces = [c for c in all_cards if c.rank == "A"]
            buf = await _asyncio.to_thread(render_hand, aces, cfg)
            file = discord.File(buf, filename="piacentine_aces.png")
            await interaction.response.send_message(
                content=content, file=file, ephemeral=True
            )
            return

        await interaction.response.send_message(content=content, ephemeral=True)


    # ------------------------------------------------------------------
    # /briscola_deck  — preview a deck's aces + read its background
    # ------------------------------------------------------------------

    @app_commands.command(
        name="briscola_deck",
        description="Preview a deck's 4 aces and read about its regional history.",
    )
    @app_commands.describe(
        deck="piacentine / napoletane / siciliane / romagnole / triestine"
    )
    async def deck_preview(
        self,
        interaction: discord.Interaction,
        deck: str = DEFAULT_DECK,
    ) -> None:
        deck = deck.lower()
        cfg = DECK_REGISTRY.get(deck)
        if cfg is None:
            await interaction.response.send_message(
                f"Unknown deck `{deck}`. Options: {', '.join(DECK_REGISTRY)}",
                ephemeral=True,
            )
            return

        info = _DECK_INFO.get(deck, f"**{cfg.label}**\nNo additional info yet.")

        all_cards = cfg.build_deck(shuffle=False)
        aces = [c for c in all_cards if c.rank == "A"]

        content = (
            f"{info}\n\n"
            f"Start a game with this deck:\n"
            f"`/briscola_vs_bot deck:{deck}`  or  `/briscola_1v1 deck:{deck}`"
        )

        import asyncio as _asyncio
        from engine.card_renderer import render_hand
        buf = await _asyncio.to_thread(render_hand, aces, cfg)
        file = discord.File(buf, filename=f"{deck}_aces.png")
        await interaction.response.send_message(
            content=content, file=file, ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameCog(bot))
