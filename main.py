"""
main.py
Bot entry point.

Usage:
    cp .env.example .env        # fill in DISCORD_TOKEN
    pip install -r requirements.txt
    python main.py
"""
from __future__ import annotations
import asyncio
import pathlib
import discord
from discord.ext import commands

# Load .env if python-dotenv is installed (optional but convenient)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from config import DISCORD_TOKEN
from db.database import init_db


_COGS = [
    "cogs.game_cog",
    "cogs.hand_cog",
    "cogs.leaderboard_cog",
]


async def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN is not set.\n"
            "Copy .env.example → .env and add your bot token."
        )

    intents = discord.Intents.default()
    intents.message_content = False   # not needed for slash-only bots

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready() -> None:
        print(f"✅  Logged in as {bot.user}  (ID: {bot.user.id})")
        try:
            synced = await bot.tree.sync()
            print(f"✅  Synced {len(synced)} slash command(s).")
        except Exception as exc:
            print(f"❌  Failed to sync commands: {exc}")

    # Initialise SQLite database (creates tables if missing)
    await init_db()
    print("✅  Database ready.")

    # Load cogs
    for cog in _COGS:
        await bot.load_extension(cog)
    print(f"✅  Loaded {len(_COGS)} cog(s).")

    await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
