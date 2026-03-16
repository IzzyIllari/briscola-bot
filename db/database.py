"""
db/database.py
Async SQLite wrapper for the per-server leaderboard.

Uses aiosqlite so all I/O is non-blocking inside discord.py's event loop.
Elo rating is updated for human-vs-human games only.
"""
from __future__ import annotations
import pathlib
import aiosqlite
from typing import List, Optional, Tuple

DB_PATH = pathlib.Path("briscola.db")
SCHEMA_PATH = pathlib.Path(__file__).parent / "schema.sql"

# Elo constants
_ELO_K = 32
_ELO_DEFAULT = 1500.0


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

async def init_db(db_path: pathlib.Path = DB_PATH) -> None:
    """
    Create all tables and indexes if they don't exist.
    Call once at bot startup before any other DB operations.
    """
    global DB_PATH
    DB_PATH = db_path
    schema = SCHEMA_PATH.read_text()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(schema)
        await db.commit()


# ---------------------------------------------------------------------------
# Elo helpers
# ---------------------------------------------------------------------------

def _expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def _updated_elo(rating: float, expected: float, actual: float) -> float:
    return rating + _ELO_K * (actual - expected)


# ---------------------------------------------------------------------------
# Writing results
# ---------------------------------------------------------------------------

async def record_game_result(
    guild_id: int,
    channel_id: int,
    p0_id: int,
    p1_id: int,           # pass 0 for the bot
    p0_points: int,
    p1_points: int,
    winner_id: Optional[int],   # None = tie; 0 = bot won
    deck_name: str = "piacentine",
    difficulty: Optional[str] = None,
) -> None:
    """
    Persist a completed game:
    - Inserts a row into game_history.
    - Updates wins/losses/ties/streak/total_points for each human player.
    - Updates Elo for human-vs-human games (skips ties and vs-bot games).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # ---- Game history ----
        await db.execute(
            """
            INSERT INTO game_history
                (guild_id, channel_id, p0_id, p1_id,
                 p0_points, p1_points, winner_id, deck_name, difficulty)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (guild_id, channel_id, p0_id, p1_id,
             p0_points, p1_points, winner_id, deck_name, difficulty),
        )

        # ---- Helper: ensure a player row exists ----
        async def ensure(uid: int) -> None:
            await db.execute(
                """
                INSERT INTO player_stats (guild_id, user_id)
                VALUES (?,?)
                ON CONFLICT(guild_id, user_id) DO NOTHING
                """,
                (guild_id, uid),
            )

        # ---- Update stats for each human player ----
        human_ids = [p0_id] + ([p1_id] if p1_id != 0 else [])
        pts_map = {p0_id: p0_points, p1_id: p1_points}

        for uid in human_ids:
            await ensure(uid)
            is_win  = 1 if winner_id == uid else 0
            is_loss = 1 if (winner_id is not None and winner_id != uid) else 0
            is_tie  = 1 if winner_id is None else 0
            delta   = 1 if is_win else (-1 if is_loss else 0)
            await db.execute(
                """
                UPDATE player_stats SET
                    wins         = wins  + ?,
                    losses       = losses + ?,
                    ties         = ties  + ?,
                    games_played = games_played + 1,
                    total_points = total_points + ?,
                    streak       = CASE
                                     WHEN ? > 0 AND streak >= 0 THEN streak + 1
                                     WHEN ? < 0 AND streak <= 0 THEN streak - 1
                                     ELSE ?
                                   END,
                    last_played  = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE guild_id = ? AND user_id = ?
                """,
                (is_win, is_loss, is_tie, pts_map.get(uid, 0),
                 delta, delta, delta,
                 guild_id, uid),
            )

        # ---- Elo update (human-vs-human, non-tie games only) ----
        if p1_id != 0 and winner_id is not None:
            async with db.execute(
                "SELECT elo FROM player_stats WHERE guild_id=? AND user_id=?",
                (guild_id, p0_id),
            ) as cur:
                row = await cur.fetchone()
                elo0 = row[0] if row else _ELO_DEFAULT

            async with db.execute(
                "SELECT elo FROM player_stats WHERE guild_id=? AND user_id=?",
                (guild_id, p1_id),
            ) as cur:
                row = await cur.fetchone()
                elo1 = row[0] if row else _ELO_DEFAULT

            actual0 = 1.0 if winner_id == p0_id else 0.0
            new_elo0 = _updated_elo(elo0, _expected_score(elo0, elo1), actual0)
            new_elo1 = _updated_elo(elo1, _expected_score(elo1, elo0), 1.0 - actual0)

            await db.execute(
                "UPDATE player_stats SET elo=? WHERE guild_id=? AND user_id=?",
                (new_elo0, guild_id, p0_id),
            )
            await db.execute(
                "UPDATE player_stats SET elo=? WHERE guild_id=? AND user_id=?",
                (new_elo1, guild_id, p1_id),
            )

        await db.commit()


# ---------------------------------------------------------------------------
# Reading leaderboard data
# ---------------------------------------------------------------------------

async def get_leaderboard(
    guild_id: int,
    page: int = 0,
    page_size: int = 10,
    sort_by: str = "elo",
) -> List[Tuple]:
    """
    Returns list of (user_id, wins, losses, ties, total_points, elo, streak).
    sort_by: 'elo' | 'wins' | 'total_points'
    """
    col = {"elo": "elo", "wins": "wins", "total_points": "total_points"}.get(
        sort_by, "elo"
    )
    offset = page * page_size
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            f"""
            SELECT user_id, wins, losses, ties, total_points, elo, streak
            FROM player_stats
            WHERE guild_id = ? AND games_played > 0
            ORDER BY {col} DESC
            LIMIT ? OFFSET ?
            """,
            (guild_id, page_size, offset),
        ) as cur:
            return await cur.fetchall()


async def get_leaderboard_count(guild_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM player_stats WHERE guild_id=? AND games_played>0",
            (guild_id,),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_bot_stats(guild_id: int) -> dict:
    """
    Returns the bot's all-time record for this server, broken down by difficulty.
    Pulls from game_history where p1_id = 0 (vs_bot games only).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Overall record
        async with db.execute(
            """
            SELECT
                COUNT(*) as games,
                SUM(CASE WHEN winner_id = 0 THEN 1 ELSE 0 END) as bot_wins,
                SUM(CASE WHEN winner_id != 0 AND winner_id IS NOT NULL THEN 1 ELSE 0 END) as human_wins,
                SUM(CASE WHEN winner_id IS NULL THEN 1 ELSE 0 END) as ties
            FROM game_history
            WHERE guild_id = ? AND p1_id = 0
            """,
            (guild_id,),
        ) as cur:
            overall = await cur.fetchone()

        # By difficulty
        async with db.execute(
            """
            SELECT
                difficulty,
                COUNT(*) as games,
                SUM(CASE WHEN winner_id = 0 THEN 1 ELSE 0 END) as bot_wins
            FROM game_history
            WHERE guild_id = ? AND p1_id = 0 AND difficulty IS NOT NULL
            GROUP BY difficulty
            ORDER BY difficulty
            """,
            (guild_id,),
        ) as cur:
            by_diff = await cur.fetchall()

    return {
        "overall": overall,   # (games, bot_wins, human_wins, ties)
        "by_difficulty": by_diff,  # [(difficulty, games, bot_wins), ...]
    }


async def get_player_stats(guild_id: int, user_id: int) -> Optional[Tuple]:
    """Returns (user_id, wins, losses, ties, total_points, elo, streak) or None."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """
            SELECT user_id, wins, losses, ties, total_points, elo, streak
            FROM player_stats
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        ) as cur:
            return await cur.fetchone()
