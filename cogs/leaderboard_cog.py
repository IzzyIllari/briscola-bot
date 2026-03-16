"""
cogs/leaderboard_cog.py
Per-server leaderboard with paginated embeds and a cycle-sort button,
plus /briscola_stats for individual player statistics.
"""
from __future__ import annotations
from typing import Optional
import discord
from discord.ext import commands
from discord import app_commands
from db.database import get_leaderboard, get_player_stats, get_leaderboard_count, get_bot_stats
from config import LEADERBOARD_PAGE_SIZE

_MEDALS = {0: "🥇", 1: "🥈", 2: "🥉"}
_SORT_LABELS = {
    "elo":          "Sort: Elo",
    "wins":         "Sort: Wins",
    "total_points": "Sort: Points",
}
_SORT_CYCLE = ["elo", "wins", "total_points"]


class LeaderboardView(discord.ui.View):
    """Paginated, sortable leaderboard embed."""

    def __init__(
        self,
        guild: discord.Guild,
        sort_by: str = "elo",
        *,
        timeout: float = 120.0,
    ):
        super().__init__(timeout=timeout)
        self.guild = guild
        self.sort_by = sort_by
        self.page = 0
        self.total_pages = 1
        # Set initial sort-button label
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == "toggle_sort":
                child.label = _SORT_LABELS[sort_by]

    async def build_embed(self) -> discord.Embed:
        rows = await get_leaderboard(
            self.guild.id,
            page=self.page,
            page_size=LEADERBOARD_PAGE_SIZE,
            sort_by=self.sort_by,
        )
        total = await get_leaderboard_count(self.guild.id)
        self.total_pages = max(1, (total + LEADERBOARD_PAGE_SIZE - 1) // LEADERBOARD_PAGE_SIZE)
        self._sync_nav_buttons()

        sort_header = {
            "elo": "Elo Rating",
            "wins": "Wins",
            "total_points": "Total Points Scored",
        }.get(self.sort_by, self.sort_by.capitalize())

        embed = discord.Embed(
            title=f"🏆 Briscola Leaderboard — {sort_header}",
            color=0xFFD700,
        )

        if not rows:
            embed.description = "No games recorded yet. Play some Briscola!"
            embed.set_footer(text=f"Page {self.page + 1}/{self.total_pages}")
            return embed

        lines = []
        for offset, (uid, wins, losses, ties, total_pts, elo, streak) in enumerate(rows):
            rank = self.page * LEADERBOARD_PAGE_SIZE + offset
            medal = _MEDALS.get(rank, f"`{rank + 1}.`")
            member = self.guild.get_member(uid)
            display = member.display_name if member else f"User {uid}"

            streak_badge = ""
            if streak >= 3:
                streak_badge = f" 🔥×{streak}"
            elif streak <= -3:
                streak_badge = f" 🥶×{abs(streak)}"

            lines.append(
                f"{medal} **{display}**{streak_badge}\n"
                f"  Elo **{elo:.0f}** · W/L/T {wins}/{losses}/{ties} · {total_pts} pts"
            )

        embed.description = "\n\n".join(lines)
        embed.set_footer(text=f"Page {self.page + 1}/{self.total_pages}")
        return embed

    def _sync_nav_buttons(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == "prev":
                    child.disabled = self.page == 0
                elif child.custom_id == "next":
                    child.disabled = self.page >= self.total_pages - 1

    @discord.ui.button(
        label="◀", style=discord.ButtonStyle.secondary,
        disabled=True, custom_id="prev",
    )
    async def prev_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.page = max(0, self.page - 1)
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(
        label="▶", style=discord.ButtonStyle.secondary, custom_id="next",
    )
    async def next_page(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.page = min(self.total_pages - 1, self.page + 1)
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(
        label="Sort: Elo", style=discord.ButtonStyle.primary, custom_id="toggle_sort",
    )
    async def toggle_sort(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        idx = _SORT_CYCLE.index(self.sort_by)
        self.sort_by = _SORT_CYCLE[(idx + 1) % len(_SORT_CYCLE)]
        button.label = _SORT_LABELS[self.sort_by]
        self.page = 0
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)


class LeaderboardCog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="briscola_lb",
        description="Show the Briscola leaderboard for this server.",
    )
    @app_commands.describe(sort_by="elo / wins / total_points  (default: elo)")
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        sort_by: str = "elo",
    ) -> None:
        if sort_by not in _SORT_CYCLE:
            await interaction.response.send_message(
                f"Invalid sort. Options: {', '.join(_SORT_CYCLE)}", ephemeral=True
            )
            return
        view = LeaderboardView(interaction.guild, sort_by=sort_by)
        embed = await view.build_embed()
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="briscola_stats",
        description="Show Briscola stats for yourself or another player.",
    )
    @app_commands.describe(player="Leave blank to see your own stats.")
    async def stats(
        self,
        interaction: discord.Interaction,
        player: Optional[discord.Member] = None,
    ) -> None:
        target = player or interaction.user
        row = await get_player_stats(interaction.guild_id, target.id)

        if row is None:
            await interaction.response.send_message(
                f"{target.mention} hasn't played any games yet.", ephemeral=True
            )
            return

        _, wins, losses, ties, total_pts, elo, streak = row
        games = wins + losses + ties
        win_rate = (wins / games * 100) if games > 0 else 0.0

        embed = discord.Embed(
            title=f"📊 {target.display_name}'s Briscola Stats",
            color=0x9B59B6,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Elo Rating",   value=f"**{elo:.0f}**")
        embed.add_field(name="Win Rate",     value=f"{win_rate:.1f}%")
        embed.add_field(name="W / L / T",    value=f"{wins} / {losses} / {ties}")
        embed.add_field(name="Games Played", value=str(games))
        embed.add_field(name="Total Points", value=str(total_pts))

        if streak >= 3:
            embed.add_field(name="Hot Streak 🔥", value=f"{streak} wins in a row!")
        elif streak <= -3:
            embed.add_field(name="Cold Streak 🥶", value=f"{abs(streak)} losses in a row")

        await interaction.response.send_message(embed=embed)


    @app_commands.command(
        name="briscola_bot_stats",
        description="How many games has the bot won? Broken down by difficulty.",
    )
    async def the_bot_stats(self, interaction: discord.Interaction) -> None:
        data = await get_bot_stats(interaction.guild_id)
        overall = data["overall"]
        by_diff = data["by_difficulty"]

        games, bot_wins, human_wins, ties = overall if overall else (0, 0, 0, 0)
        games = games or 0
        bot_wins = bot_wins or 0
        human_wins = human_wins or 0
        ties = ties or 0

        if games == 0:
            await interaction.response.send_message(
                "No vs-bot games recorded yet on this server.", ephemeral=True
            )
            return

        bot_rate = 100 * bot_wins / games if games else 0
        human_rate = 100 * human_wins / games if games else 0

        embed = discord.Embed(title="🤖 Bot's Record", color=0x2F3136)
        embed.add_field(name="Games played", value=str(games))
        embed.add_field(name="Bot wins", value=f"{bot_wins} ({bot_rate:.0f}%)")
        embed.add_field(name="Human wins", value=f"{human_wins} ({human_rate:.0f}%)")
        if ties:
            embed.add_field(name="Ties", value=str(ties))

        if by_diff:
            lines = []
            for diff, d_games, d_bot_wins in by_diff:
                d_bot_wins = d_bot_wins or 0
                d_human = d_games - d_bot_wins
                rate = 100 * d_bot_wins / d_games if d_games else 0
                bar = "█" * int(rate / 10) + "░" * (10 - int(rate / 10))
                lines.append(
                    f"`{diff:8s}` {bar} {rate:.0f}%  "
                    f"({d_bot_wins}W / {d_human}L / {d_games} played)"
                )
            embed.add_field(
                name="By difficulty",
                value="\n".join(lines),
                inline=False,
            )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LeaderboardCog(bot))
