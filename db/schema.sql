-- db/schema.sql
-- Per-server Briscola leaderboard schema.

PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;

CREATE TABLE IF NOT EXISTS player_stats (
    guild_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    wins          INTEGER NOT NULL DEFAULT 0,
    losses        INTEGER NOT NULL DEFAULT 0,
    ties          INTEGER NOT NULL DEFAULT 0,
    games_played  INTEGER NOT NULL DEFAULT 0,
    total_points  INTEGER NOT NULL DEFAULT 0,   -- cumulative pts scored across all games
    elo           REAL    NOT NULL DEFAULT 1500.0,
    streak        INTEGER NOT NULL DEFAULT 0,   -- positive = win streak, negative = loss streak
    last_played   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS game_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id      INTEGER NOT NULL,
    channel_id    INTEGER NOT NULL,
    p0_id         INTEGER NOT NULL,
    p1_id         INTEGER NOT NULL,   -- 0 if the opponent was the bot
    p0_points     INTEGER NOT NULL,
    p1_points     INTEGER NOT NULL,
    winner_id     INTEGER,            -- NULL = tie; 0 = bot won
    deck_name     TEXT    NOT NULL DEFAULT 'piacentine',
    difficulty    TEXT,               -- NULL for 1v1 games
    played_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Indexes for fast leaderboard queries
CREATE INDEX IF NOT EXISTS idx_stats_guild_elo    ON player_stats(guild_id, elo DESC);
CREATE INDEX IF NOT EXISTS idx_stats_guild_wins   ON player_stats(guild_id, wins DESC);
CREATE INDEX IF NOT EXISTS idx_stats_guild_pts    ON player_stats(guild_id, total_points DESC);
CREATE INDEX IF NOT EXISTS idx_history_guild_time ON game_history(guild_id, played_at DESC);
