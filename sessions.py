"""
sessions.py
In-memory session management: active games and pending PvP challenges.

The SessionRegistry is a single asyncio-safe (single-threaded event loop)
store for all live game state. Import `registry` from here everywhere.
"""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from engine.game import BriscolaGame
from engine.cards import Card


@dataclass
class PlayerSlot:
    user_id: int
    is_bot: bool = False

    def mention_str(self, guild) -> str:
        if self.is_bot:
            return "🤖 Bot"
        if guild is None:
            return f"<@{self.user_id}>"
        member = guild.get_member(self.user_id)
        return member.mention if member else f"<@{self.user_id}>"


@dataclass
class GameSession:
    channel_id: int
    guild_id: int
    mode: str                         # "vs_bot" | "1v1"
    game: BriscolaGame
    slots: List[PlayerSlot]           # index matches game player 0/1
    bot_difficulty: Optional[str] = None

    # Cards played in the current trick (for public display)
    trick_log: List[Tuple[int, Card]] = field(default_factory=list)

    # AFK timeout bookkeeping
    turn_deadline: Optional[float] = None
    turn_timeout_task: Optional[asyncio.Task] = field(default=None, repr=False)

    def slot_for_user(self, user_id: int) -> Optional[int]:
        for i, slot in enumerate(self.slots):
            if slot.user_id == user_id:
                return i
        return None

    def is_bot_turn(self) -> bool:
        return self.slots[self.game.turn].is_bot


@dataclass
class PendingChallenge:
    channel_id: int
    guild_id: int
    challenger_id: int
    opponent_id: int
    deck_name: str
    created_at: float = field(default_factory=time.time)

    def is_expired(self, timeout_seconds: int) -> bool:
        return time.time() - self.created_at > timeout_seconds


class SessionRegistry:
    """
    Central store for all active games and pending challenges.
    Safe for use within asyncio's single-threaded event loop.
    """

    def __init__(self):
        self._sessions: Dict[int, GameSession] = {}       # key: channel_id
        self._challenges: Dict[int, PendingChallenge] = {}  # key: channel_id

    # ---- Active games ----

    def get(self, channel_id: int) -> Optional[GameSession]:
        return self._sessions.get(channel_id)

    def add(self, session: GameSession) -> None:
        self._sessions[session.channel_id] = session

    def remove(self, channel_id: int) -> Optional[GameSession]:
        return self._sessions.pop(channel_id, None)

    def cancel_timeout(self, session: GameSession) -> None:
        if session.turn_timeout_task:
            session.turn_timeout_task.cancel()
            session.turn_timeout_task = None
        session.turn_deadline = None

    # ---- Pending challenges ----

    def get_challenge(self, channel_id: int) -> Optional[PendingChallenge]:
        return self._challenges.get(channel_id)

    def add_challenge(self, challenge: PendingChallenge) -> None:
        self._challenges[challenge.channel_id] = challenge

    def remove_challenge(self, channel_id: int) -> Optional[PendingChallenge]:
        return self._challenges.pop(channel_id, None)


# ---------------------------------------------------------------------------
# Global singleton — import this everywhere
# ---------------------------------------------------------------------------
registry = SessionRegistry()
