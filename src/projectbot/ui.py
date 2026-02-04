"""
ProjectBot UI Module
====================
Modern Discord UI with Views, Buttons, Select Menus, and Modals.
Focus: Maximum usability with minimal friction.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Coroutine, Any
from uuid import UUID

import discord
from discord import ui

if TYPE_CHECKING:
    from .models import Task

LOGGER = logging.getLogger("projectbot.ui")

# ============================================================================
# Constants
# ============================================================================

# Task status configuration
STATUS_CONFIG = {
    "todo": {"label": "A faire", "color": 0x99AAB5, "style": discord.ButtonStyle.secondary},
    "in_progress": {"label": "En cours", "color": 0x5865F2, "style": discord.ButtonStyle.primary},
    "blocked": {"label": "Bloque", "color": 0xFEE75C, "style": discord.ButtonStyle.danger},
    "done": {"label": "Termine", "color": 0x57F287, "style": discord.ButtonStyle.success},
}

ITEMS_PER_PAGE = 5


# ============================================================================
# Utility Functions
# ============================================================================

def format_due(due_at: datetime | None) -> str:
    """Format due date as relative time."""
    if not due_at:
        return "Pas de deadline"

    now = datetime.now(timezone.utc)
    delta = due_at - now
    days = delta.days

    if days < -1:
        return f"{abs(days)}j en retard"
    elif days == -1:
        return "Hier"
    elif days == 0:
        return "Aujourd'hui"
    elif days == 1:
        return "Demain"
    elif days < 7:
        return f"Dans {days}j"
    else:
        return due_at.strftime("%d/%m")


def short_id(task_id: UUID | str) -> str:
    """Get short task ID for display."""
    return str(task_id)[:8]


def get_status_label(status: str) -> str:
    """Get human-readable status label."""
    return STATUS_CONFIG.get(status, {}).get("label", status)


def get_status_color(status: str) -> int:
    """Get color for status."""
    return STATUS_CONFIG.get(status, {}).get("color", 0x99AAB5)


# ============================================================================
# Task Creation Modal
# ============================================================================

class TaskCreateModal(ui.Modal, title="Nouvelle tache"):
    """Modal for creating a new task with full details."""

    task_title = ui.TextInput(
        label="Titre",
        placeholder="Ex: Corriger le bug de login",
        min_length=1,
        max_length=200,
        required=True,
    )

    description = ui.TextInput(
        label="Description (optionnel)",
        style=discord.TextStyle.paragraph,
        placeholder="Details supplementaires...",
        required=False,
        max_length=1000,
    )

    due_days = ui.TextInput(
        label="Deadline en jours (optionnel)",
        placeholder="Ex: 3 (pour dans 3 jours)",
        required=False,
        max_length=3,
    )

    def __init__(
        self,
        callback: Callable[[discord.Interaction, str, str | None, int | None], Coroutine[Any, Any, None]],
    ) -> None:
        super().__init__(timeout=300)
        self._callback = callback

    async def on_submit(self, interaction: discord.Interaction) -> None:
        title = self.task_title.value.strip()
        description = self.description.value.strip() or None

        due_in_days: int | None = None
        if self.due_days.value.strip():
            try:
                due_in_days = int(self.due_days.value.strip())
            except ValueError:
                await interaction.response.send_message(
                    "La deadline doit etre un nombre.",
                    ephemeral=True,
                )
                return

        await self._callback(interaction, title, description, due_in_days)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        LOGGER.exception("Modal error: %s", error)
        await interaction.response.send_message(
            "Une erreur est survenue.",
            ephemeral=True,
        )


# ============================================================================
# Task Edit Modal
# ============================================================================

class TaskEditModal(ui.Modal, title="Modifier la tache"):
    """Modal for editing an existing task."""

    task_title = ui.TextInput(
        label="Titre",
        min_length=1,
        max_length=200,
        required=True,
    )

    description = ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
    )

    def __init__(
        self,
        task_id: str,
        current_title: str,
        current_description: str | None,
        callback: Callable[[discord.Interaction, str, str, str | None], Coroutine[Any, Any, None]],
    ) -> None:
        super().__init__(timeout=300)
        self.task_id = task_id
        self.task_title.default = current_title
        self.description.default = current_description or ""
        self._callback = callback

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._callback(
            interaction,
            self.task_id,
            self.task_title.value.strip(),
            self.description.value.strip() or None,
        )


# ============================================================================
# Status Select Menu
# ============================================================================

class StatusSelect(ui.Select):
    """Select menu for changing task status."""

    def __init__(
        self,
        task_id: str,
        current_status: str,
        callback: Callable[[discord.Interaction, str, str], Coroutine[Any, Any, None]],
    ) -> None:
        self.task_id = task_id
        self._callback = callback

        options = []
        for status, config in STATUS_CONFIG.items():
            options.append(
                discord.SelectOption(
                    label=config["label"],
                    value=status,
                    default=(status == current_status),
                )
            )

        super().__init__(
            placeholder="Changer le statut...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        new_status = self.values[0]
        await self._callback(interaction, self.task_id, new_status)


# ============================================================================
# Task Action Buttons
# ============================================================================

class TaskActionView(ui.View):
    """View with action buttons for a single task."""

    def __init__(
        self,
        task: "Task",
        on_done: Callable[[discord.Interaction, str], Coroutine[Any, Any, None]],
        on_edit: Callable[[discord.Interaction, "Task"], Coroutine[Any, Any, None]],
        on_status_change: Callable[[discord.Interaction, str, str], Coroutine[Any, Any, None]],
    ) -> None:
        super().__init__(timeout=300)
        self.task = task
        self._on_done = on_done
        self._on_edit = on_edit

        task_id = str(task.id)

        # Add status select
        self.add_item(StatusSelect(task_id, task.status, on_status_change))

        # Quick done button (only if not already done)
        if task.status != "done":
            done_btn = ui.Button(
                label="Terminer",
                style=discord.ButtonStyle.success,
                custom_id=f"done:{task_id[:8]}",
            )
            done_btn.callback = self._handle_done
            self.add_item(done_btn)

        # Edit button
        edit_btn = ui.Button(
            label="Modifier",
            style=discord.ButtonStyle.secondary,
            custom_id=f"edit:{task_id[:8]}",
        )
        edit_btn.callback = self._handle_edit
        self.add_item(edit_btn)

    async def _handle_done(self, interaction: discord.Interaction) -> None:
        await self._on_done(interaction, str(self.task.id))

    async def _handle_edit(self, interaction: discord.Interaction) -> None:
        await self._on_edit(interaction, self.task)


# ============================================================================
# Task List View with Pagination
# ============================================================================

class TaskListView(ui.View):
    """Paginated task list with filters and quick actions."""

    def __init__(
        self,
        tasks: list["Task"],
        on_task_select: Callable[[discord.Interaction, str], Coroutine[Any, Any, None]],
        on_create: Callable[[discord.Interaction], Coroutine[Any, Any, None]],
        on_refresh: Callable[[discord.Interaction], Coroutine[Any, Any, None]],
        current_filter: str = "all",
    ) -> None:
        super().__init__(timeout=300)
        self.all_tasks = tasks
        self.current_filter = current_filter
        self.page = 0
        self._on_task_select = on_task_select
        self._on_create = on_create
        self._on_refresh = on_refresh

        self._update_components()

    @property
    def filtered_tasks(self) -> list["Task"]:
        """Get tasks filtered by current filter."""
        if self.current_filter == "all":
            return self.all_tasks
        return [t for t in self.all_tasks if t.status == self.current_filter]

    @property
    def total_pages(self) -> int:
        """Get total number of pages."""
        return max(1, (len(self.filtered_tasks) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

    @property
    def current_page_tasks(self) -> list["Task"]:
        """Get tasks for current page."""
        start = self.page * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        return self.filtered_tasks[start:end]

    def _update_components(self) -> None:
        """Update view components based on current state."""
        self.clear_items()

        # Filter select (row 0)
        filter_options = [
            discord.SelectOption(label="Toutes", value="all", default=self.current_filter == "all"),
            discord.SelectOption(label="A faire", value="todo", default=self.current_filter == "todo"),
            discord.SelectOption(label="En cours", value="in_progress", default=self.current_filter == "in_progress"),
            discord.SelectOption(label="Bloquees", value="blocked", default=self.current_filter == "blocked"),
            discord.SelectOption(label="Terminees", value="done", default=self.current_filter == "done"),
        ]

        filter_select = ui.Select(
            placeholder="Filtrer par statut...",
            options=filter_options,
            row=0,
        )
        filter_select.callback = self._handle_filter
        self.add_item(filter_select)

        # Task select (row 1) - only if there are tasks
        if self.current_page_tasks:
            task_options = []
            for task in self.current_page_tasks:
                status_label = get_status_label(task.status)
                due = format_due(task.due_at)

                task_options.append(
                    discord.SelectOption(
                        label=task.title[:50] if len(task.title) > 50 else task.title,
                        value=str(task.id),
                        description=f"{status_label} | {due}",
                    )
                )

            task_select = ui.Select(
                placeholder="Selectionner une tache...",
                options=task_options,
                row=1,
            )
            task_select.callback = self._handle_task_select
            self.add_item(task_select)

        # Navigation buttons (row 2)
        prev_btn = ui.Button(
            label="<",
            style=discord.ButtonStyle.secondary,
            disabled=self.page == 0,
            row=2,
        )
        prev_btn.callback = self._handle_prev
        self.add_item(prev_btn)

        page_btn = ui.Button(
            label=f"{self.page + 1}/{self.total_pages}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            row=2,
        )
        self.add_item(page_btn)

        next_btn = ui.Button(
            label=">",
            style=discord.ButtonStyle.secondary,
            disabled=self.page >= self.total_pages - 1,
            row=2,
        )
        next_btn.callback = self._handle_next
        self.add_item(next_btn)

        # Action buttons (row 3)
        create_btn = ui.Button(
            label="+ Nouvelle tache",
            style=discord.ButtonStyle.success,
            row=3,
        )
        create_btn.callback = self._handle_create
        self.add_item(create_btn)

        refresh_btn = ui.Button(
            label="Actualiser",
            style=discord.ButtonStyle.secondary,
            row=3,
        )
        refresh_btn.callback = self._handle_refresh
        self.add_item(refresh_btn)

    async def _handle_filter(self, interaction: discord.Interaction) -> None:
        self.current_filter = interaction.data["values"][0]  # type: ignore
        self.page = 0
        self._update_components()
        await interaction.response.edit_message(
            embed=self._build_embed(),
            view=self,
        )

    async def _handle_task_select(self, interaction: discord.Interaction) -> None:
        task_id = interaction.data["values"][0]  # type: ignore
        await self._on_task_select(interaction, task_id)

    async def _handle_prev(self, interaction: discord.Interaction) -> None:
        self.page = max(0, self.page - 1)
        self._update_components()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _handle_next(self, interaction: discord.Interaction) -> None:
        self.page = min(self.total_pages - 1, self.page + 1)
        self._update_components()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _handle_create(self, interaction: discord.Interaction) -> None:
        await self._on_create(interaction)

    async def _handle_refresh(self, interaction: discord.Interaction) -> None:
        await self._on_refresh(interaction)

    def _build_embed(self) -> discord.Embed:
        """Build the task list embed."""
        return build_task_list_embed(
            self.filtered_tasks,
            page=self.page,
            total_pages=self.total_pages,
            filter_label=get_status_label(self.current_filter) if self.current_filter != "all" else None,
        )


# ============================================================================
# Quick Actions View (Persistent)
# ============================================================================

class QuickActionsView(ui.View):
    """Persistent view with quick action buttons."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @ui.button(
        label="Mes taches",
        style=discord.ButtonStyle.primary,
        custom_id="projectbot:quick:list",
    )
    async def list_tasks(self, interaction: discord.Interaction, button: ui.Button) -> None:
        # This will be handled by the bot's persistent view handler
        pass

    @ui.button(
        label="+ Nouvelle",
        style=discord.ButtonStyle.success,
        custom_id="projectbot:quick:create",
    )
    async def create_task(self, interaction: discord.Interaction, button: ui.Button) -> None:
        # This will be handled by the bot's persistent view handler
        pass

    @ui.button(
        label="Status",
        style=discord.ButtonStyle.secondary,
        custom_id="projectbot:quick:status",
    )
    async def show_status(self, interaction: discord.Interaction, button: ui.Button) -> None:
        # This will be handled by the bot's persistent view handler
        pass


# ============================================================================
# Embed Builders
# ============================================================================

def build_task_embed(task: "Task") -> discord.Embed:
    """Build embed for a single task."""
    status_config = STATUS_CONFIG.get(task.status, STATUS_CONFIG["todo"])

    embed = discord.Embed(
        title=task.title,
        description=task.description or "_Pas de description_",
        color=status_config["color"],
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(
        name="Statut",
        value=status_config["label"],
        inline=True,
    )

    embed.add_field(
        name="Deadline",
        value=format_due(task.due_at),
        inline=True,
    )

    embed.set_footer(text="ProjectBot")

    return embed


def build_task_list_embed(
    tasks: list["Task"],
    page: int = 0,
    total_pages: int = 1,
    filter_label: str | None = None,
) -> discord.Embed:
    """Build embed for task list."""
    if not tasks:
        embed = discord.Embed(
            title="Taches",
            description="Aucune tache trouvee.\n\nUtilisez le bouton **+ Nouvelle tache** pour commencer.",
            color=0x99AAB5,
        )
        embed.set_footer(text="ProjectBot")
        return embed

    # Count by status
    counts = {"todo": 0, "in_progress": 0, "blocked": 0, "done": 0}
    for task in tasks:
        if task.status in counts:
            counts[task.status] += 1

    # Summary line
    summary_parts = []
    if counts["todo"]:
        summary_parts.append(f"{counts['todo']} a faire")
    if counts["in_progress"]:
        summary_parts.append(f"{counts['in_progress']} en cours")
    if counts["blocked"]:
        summary_parts.append(f"{counts['blocked']} bloquees")
    if counts["done"]:
        summary_parts.append(f"{counts['done']} terminees")

    summary = " | ".join(summary_parts) if summary_parts else "Aucune tache"

    title = "Taches"
    if filter_label:
        title = f"Taches - {filter_label}"

    embed = discord.Embed(
        title=title,
        description=summary,
        color=0x5865F2,
    )

    # Show tasks for current page
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_tasks = tasks[start:end]

    for task in page_tasks:
        status_label = get_status_label(task.status)
        due = format_due(task.due_at)

        value = f"{status_label} | {due}"
        if task.description:
            desc_preview = task.description[:80]
            if len(task.description) > 80:
                desc_preview += "..."
            value = f"{desc_preview}\n_{status_label} | {due}_"

        embed.add_field(
            name=task.title,
            value=value,
            inline=False,
        )

    embed.set_footer(text=f"Page {page + 1}/{total_pages} | ProjectBot")

    return embed


def build_success_embed(title: str, description: str | None = None) -> discord.Embed:
    """Build a success embed."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=0x57F287,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="ProjectBot")
    return embed


def build_error_embed(title: str, description: str | None = None) -> discord.Embed:
    """Build an error embed."""
    embed = discord.Embed(
        title=title,
        description=description,
        color=0xED4245,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="ProjectBot")
    return embed


def build_status_embed(db_ok: bool, redis_ok: bool, latency_ms: float | None = None) -> discord.Embed:
    """Build system status embed."""
    all_ok = db_ok and redis_ok

    embed = discord.Embed(
        title="Status du systeme",
        color=0x57F287 if all_ok else 0xFEE75C,
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(
        name="Base de donnees",
        value="Connectee" if db_ok else "Erreur",
        inline=True,
    )

    embed.add_field(
        name="Redis",
        value="Connecte" if redis_ok else "Erreur",
        inline=True,
    )

    if latency_ms is not None:
        embed.add_field(
            name="Latence",
            value=f"{latency_ms:.0f}ms",
            inline=True,
        )

    embed.set_footer(text="ProjectBot")

    return embed


def build_help_embed() -> discord.Embed:
    """Build help embed."""
    embed = discord.Embed(
        title="ProjectBot - Aide",
        description="Gestionnaire de taches pour Discord",
        color=0x5865F2,
    )

    embed.add_field(
        name="Commandes",
        value=(
            "`/setup` - Initialiser le workspace\n"
            "`/task` - Ouvrir le gestionnaire de taches\n"
            "`/task add` - Creer une tache rapidement\n"
            "`/status` - Voir l'etat du systeme\n"
            "`/help` - Cette aide"
        ),
        inline=False,
    )

    embed.add_field(
        name="Utilisation",
        value=(
            "1. Utilisez `/setup` pour configurer\n"
            "2. Utilisez `/task` pour voir vos taches\n"
            "3. Cliquez sur une tache pour la modifier\n"
            "4. Utilisez les boutons pour naviguer"
        ),
        inline=False,
    )

    embed.set_footer(text="ProjectBot")

    return embed


def build_workspace_setup_embed(guild_name: str, timezone_str: str) -> discord.Embed:
    """Build workspace setup confirmation embed."""
    embed = discord.Embed(
        title="Workspace configure",
        description=f"Le workspace **{guild_name}** est pret.",
        color=0x57F287,
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(name="Timezone", value=timezone_str, inline=True)
    embed.add_field(name="Prochaine etape", value="Utilisez `/task` pour commencer", inline=True)
    embed.set_footer(text="ProjectBot")

    return embed
