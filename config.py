"""
config.py
All tuneable constants and environment-variable references.
"""
import os

# Discord
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")

# Timeouts
TURN_TOTAL_SECONDS: int = int(os.getenv("TURN_TOTAL_SECONDS", "180"))
TURN_WARNING_SECONDS: int = int(os.getenv("TURN_WARNING_SECONDS", "120"))
CHALLENGE_TIMEOUT_SECONDS: int = int(os.getenv("CHALLENGE_TIMEOUT_SECONDS", "300"))

# AI
DEFAULT_DIFFICULTY: str = "medium"
VALID_DIFFICULTIES: tuple = ("easy", "medium", "hard", "extreme")
EXTREME_ROLLOUTS: int = int(os.getenv("EXTREME_ROLLOUTS", "100"))

# Leaderboard
LEADERBOARD_PAGE_SIZE: int = 10

# Deck
DEFAULT_DECK: str = "piacentine"
VALID_DECKS: tuple = ("piacentine", "siciliane", "napoletane", "romagnole", "triestine")
