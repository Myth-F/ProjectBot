"""
ProjectBot UI Module
====================
Centralized UI components with ASCII art and Discord embeds.
No emojis - pure ASCII aesthetics.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable

import discord

if TYPE_CHECKING:
    from .models import Task

# ============================================================================
# ASCII Art Constants
# ============================================================================

BRAND_HEADER = """
```
 ____            _           _   ____        _
|  _ \\ _ __ ___ (_) ___  ___| |_| __ )  ___ | |_
| |_) | '__/ _ \\| |/ _ \\/ __| __|  _ \\ / _ \\| __|
|  __/| | | (_) | |  __/ (__| |_| |_) | (_) | |_
|_|   |_|  \\___// |\\___|\\___|\\__|____/ \\___/ \\__|
              |__/
```"""

MINI_LOGO = "[ProjectBot]"

# Box drawing characters for tables
BOX_TL = "+"  # Top-left
BOX_TR = "+"  # Top-right
BOX_BL = "+"  # Bottom-left
BOX_BR = "+"  # Bottom-right
BOX_H = "-"   # Horizontal
BOX_V = "|"   # Vertical
BOX_CROSS = "+"

# Status indicators (ASCII only)
STATUS_ICONS = {
    "todo": "[ ]",
    "in_progress": "[~]",
    "blocked": "[!]",
    "done": "[x]",
}

# Section dividers
DIVIDER_LIGHT = "-" * 40
DIVIDER_HEAVY = "=" * 40
DIVIDER_DOTS = "." * 40


# ============================================================================
# Color Palette (Discord embed colors)
# ============================================================================

class Colors:
    """Discord embed color palette."""
    PRIMARY = 0x5865F2      # Discord Blurple
    SUCCESS = 0x57F287      # Green
    WARNING = 0xFEE75C      # Yellow
    ERROR = 0xED4245        # Red
    INFO = 0x5865F2         # Blue
    NEUTRAL = 0x99AAB5      # Gray

    # Status-specific colors
    STATUS_TODO = 0x99AAB5
    STATUS_IN_PROGRESS = 0x5865F2
    STATUS_BLOCKED = 0xFEE75C
    STATUS_DONE = 0x57F287


def get_status_color(status: str) -> int:
    """Get color for task status."""
    return {
        "todo": Colors.STATUS_TODO,
        "in_progress": Colors.STATUS_IN_PROGRESS,
        "blocked": Colors.STATUS_BLOCKED,
        "done": Colors.STATUS_DONE,
    }.get(status, Colors.NEUTRAL)


# ============================================================================
# Text Formatting Utilities
# ============================================================================

def ascii_box(content: str, title: str | None = None, width: int = 50) -> str:
    """
    Create an ASCII box around content.

    +--[ Title ]---------------------------+
    | Content line 1                       |
    | Content line 2                       |
    +--------------------------------------+
    """
    lines = content.split("\n")
    inner_width = width - 4  # Account for "| " and " |"

    # Build top border
    if title:
        title_part = f"[ {title} ]"
        remaining = width - 2 - len(title_part)
        top = BOX_TL + BOX_H + title_part + BOX_H * remaining + BOX_TR
    else:
        top = BOX_TL + BOX_H * (width - 2) + BOX_TR

    # Build content lines
    content_lines = []
    for line in lines:
        # Truncate or pad line
        if len(line) > inner_width:
            line = line[:inner_width - 3] + "..."
        padded = line.ljust(inner_width)
        content_lines.append(f"{BOX_V} {padded} {BOX_V}")

    # Build bottom border
    bottom = BOX_BL + BOX_H * (width - 2) + BOX_BR

    return "\n".join([top] + content_lines + [bottom])


def format_timestamp(dt: datetime | None) -> str:
    """Format datetime for display."""
    if dt is None:
        return "---"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def format_relative_time(dt: datetime | None) -> str:
    """Format datetime as relative time."""
    if dt is None:
        return "---"

    now = datetime.now(timezone.utc)
    delta = dt - now
    days = delta.days

    if days < 0:
        return f"{abs(days)}j en retard"
    elif days == 0:
        return "Aujourd'hui"
    elif days == 1:
        return "Demain"
    else:
        return f"Dans {days}j"


def truncate(text: str, max_length: int = 50) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


# ============================================================================
# Task Formatting
# ============================================================================

def format_task_row(task: "Task", show_description: bool = False) -> str:
    """
    Format a single task as a table row.

    [ ] abc123 | Fix the bug       | 2024-01-15
    """
    task_id = str(task.id)[:8]
    icon = STATUS_ICONS.get(task.status, "[ ]")
    title = truncate(task.title, 30)
    due = format_timestamp(task.due_at)

    row = f"{icon} {task_id} | {title:<30} | {due}"

    if show_description and task.description:
        desc = truncate(task.description, 45)
        row += f"\n    > {desc}"

    return row


def format_task_table(tasks: Iterable["Task"]) -> str:
    """
    Format tasks as an ASCII table.

    +--[ TACHES ]-------------------------------------------+
    | ST  ID       | Titre                          | Deadline   |
    |-----------------------------------------------------+
    | [ ] abc123   | Fix the bug                    | 2024-01-15 |
    | [x] def456   | Add feature                    | 2024-01-10 |
    +-----------------------------------------------------+
    """
    task_list = list(tasks)
    if not task_list:
        return ascii_box("Aucune tache.", title="TACHES", width=56)

    header = "ST   ID       | Titre                          | Deadline"
    separator = BOX_H * 54

    rows = [header, separator]
    for task in task_list:
        rows.append(format_task_row(task))

    content = "\n".join(rows)
    return ascii_box(content, title="TACHES", width=56)


# ============================================================================
# Discord Embeds
# ============================================================================

def create_base_embed(
    title: str,
    description: str | None = None,
    color: int = Colors.PRIMARY,
) -> discord.Embed:
    """Create a base embed with consistent styling."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=MINI_LOGO)
    return embed


def embed_success(title: str, description: str | None = None) -> discord.Embed:
    """Create a success embed."""
    return create_base_embed(f"[OK] {title}", description, Colors.SUCCESS)


def embed_error(title: str, description: str | None = None) -> discord.Embed:
    """Create an error embed."""
    return create_base_embed(f"[ERR] {title}", description, Colors.ERROR)


def embed_warning(title: str, description: str | None = None) -> discord.Embed:
    """Create a warning embed."""
    return create_base_embed(f"[!] {title}", description, Colors.WARNING)


def embed_info(title: str, description: str | None = None) -> discord.Embed:
    """Create an info embed."""
    return create_base_embed(f"[i] {title}", description, Colors.INFO)


# ============================================================================
# Specific Embeds
# ============================================================================

def embed_workspace_setup(guild_name: str, timezone_str: str) -> discord.Embed:
    """Create workspace setup confirmation embed."""
    embed = embed_success("Workspace initialise")

    config_block = f"""```
+--[ Configuration ]---------------------+
| Serveur  : {truncate(guild_name, 28):<28} |
| Timezone : {timezone_str:<28} |
| Status   : Actif                       |
+-----------------------------------------+
```"""

    embed.description = config_block
    embed.add_field(
        name="Prochaines etapes",
        value="```\n> /task add   - Creer une tache\n> /task list  - Voir les taches\n> /help       - Aide complete\n```",
        inline=False,
    )
    return embed


def embed_task_created(task: "Task") -> discord.Embed:
    """Create task creation confirmation embed."""
    task_id = str(task.id)[:8]
    embed = embed_success("Tache creee")

    task_block = f"""```
+--[ Nouvelle tache ]--------------------+
| ID    : {task_id:<31} |
| Titre : {truncate(task.title, 31):<31} |
| Status: {task.status:<31} |
| Due   : {format_timestamp(task.due_at):<31} |
+-----------------------------------------+
```"""

    embed.description = task_block

    if task.description:
        embed.add_field(
            name="Description",
            value=f"```\n{truncate(task.description, 200)}\n```",
            inline=False,
        )

    return embed


def embed_task_list(tasks: Iterable["Task"], workspace_name: str | None = None) -> discord.Embed:
    """Create task list embed."""
    task_list = list(tasks)

    if not task_list:
        embed = embed_info("Liste des taches")
        embed.description = "```\nAucune tache pour le moment.\n\n> Utilisez /task add pour creer une tache\n```"
        return embed

    # Count by status
    counts = {"todo": 0, "in_progress": 0, "blocked": 0, "done": 0}
    for task in task_list:
        if task.status in counts:
            counts[task.status] += 1

    embed = embed_info(f"Liste des taches ({len(task_list)})")

    # Summary bar
    summary = f"[ ] {counts['todo']}  [~] {counts['in_progress']}  [!] {counts['blocked']}  [x] {counts['done']}"

    # Build task table
    lines = [DIVIDER_LIGHT, summary, DIVIDER_LIGHT, ""]

    for task in task_list:
        task_id = str(task.id)[:8]
        icon = STATUS_ICONS.get(task.status, "[ ]")
        due = format_relative_time(task.due_at)
        lines.append(f"{icon} {task_id} {truncate(task.title, 25):<25} {due}")

    lines.append("")
    lines.append(DIVIDER_LIGHT)

    embed.description = f"```\n{chr(10).join(lines)}\n```"

    return embed


def embed_task_done(task: "Task") -> discord.Embed:
    """Create task completion embed."""
    task_id = str(task.id)[:8]
    embed = embed_success("Tache terminee")

    embed.description = f"""```
+--[ Termine ]---------------------------+
| ID    : {task_id:<31} |
| Titre : {truncate(task.title, 31):<31} |
| Status: done                           |
+-----------------------------------------+
```"""

    return embed


def embed_task_not_found(task_id_prefix: str) -> discord.Embed:
    """Create task not found error embed."""
    embed = embed_error("Tache introuvable")
    embed.description = f"""```
Aucune tache trouvee avec l'ID: {task_id_prefix}

> Verifiez l'ID avec /task list
> L'ID doit correspondre au debut de l'identifiant
```"""
    return embed


def embed_status(db_ok: bool, redis_ok: bool) -> discord.Embed:
    """Create system status embed."""
    all_ok = db_ok and redis_ok
    embed = embed_success("Status systeme") if all_ok else embed_warning("Status systeme")

    db_status = "[OK]" if db_ok else "[KO]"
    redis_status = "[OK]" if redis_ok else "[KO]"

    status_block = f"""```
+--[ Diagnostics ]-----------------------+
|                                        |
|   Database    : {db_status:<22} |
|   Redis       : {redis_status:<22} |
|                                        |
|   Global      : {'[OK] Operationnel' if all_ok else '[!!] Degraded':<22} |
|                                        |
+-----------------------------------------+
```"""

    embed.description = status_block
    return embed


def embed_help() -> discord.Embed:
    """Create help embed."""
    embed = embed_info("Aide - ProjectBot")

    embed.description = f"""```
{BRAND_HEADER}
```"""

    embed.add_field(
        name="Configuration",
        value="```\n/setup [timezone]  Initialiser le workspace\n/status            Diagnostics systeme\n```",
        inline=False,
    )

    embed.add_field(
        name="Gestion des taches",
        value="```\n/task add          Creer une nouvelle tache\n/task list         Lister les taches\n/task done <id>    Marquer comme termine\n```",
        inline=False,
    )

    embed.add_field(
        name="Legende des statuts",
        value="```\n[ ] todo        - A faire\n[~] in_progress - En cours\n[!] blocked     - Bloque\n[x] done        - Termine\n```",
        inline=False,
    )

    return embed


def embed_ping(latency_ms: float | None = None) -> discord.Embed:
    """Create ping response embed."""
    embed = embed_success("Pong")

    latency_str = f"{latency_ms:.0f}ms" if latency_ms else "---"

    embed.description = f"""```
+--[ Health Check ]----------------------+
|                                        |
|   Status   : Online                    |
|   Latency  : {latency_str:<26} |
|                                        |
+-----------------------------------------+
```"""

    return embed


def embed_guild_only() -> discord.Embed:
    """Create guild-only error embed."""
    embed = embed_error("Commande non disponible")
    embed.description = "```\nCette commande est uniquement\ndisponible dans un serveur Discord.\n```"
    return embed
