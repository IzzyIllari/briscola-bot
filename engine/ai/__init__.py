from engine.ai.heuristic import choose_easy, choose_medium, choose_hard
from engine.ai.extreme import choose_extreme
from engine.game import BriscolaGame

VALID_DIFFICULTIES = ("easy", "medium", "hard", "extreme")


def choose_card(game: BriscolaGame, bot_index: int, difficulty: str = "medium") -> int:
    d = difficulty.lower()
    if d in ("easy", "e"):
        return choose_easy(game, bot_index)
    if d in ("medium", "m", "normal"):
        return choose_medium(game, bot_index)
    if d in ("hard", "h"):
        return choose_hard(game, bot_index)
    if d in ("extreme", "x", "insane"):
        return choose_extreme(game, bot_index)
    raise ValueError(
        f"Unknown difficulty {difficulty!r}. Valid options: {VALID_DIFFICULTIES}"
    )
