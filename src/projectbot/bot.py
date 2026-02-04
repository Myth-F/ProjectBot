"""
ProjectBot Discord Bot
======================
Interactive Discord bot with Views, Buttons, Select Menus, and Modals.
"""

import logging
import time
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from .audit import log_action
from .config import get_settings
from .db import get_sessionmaker, init_db, ping_db
from .logging import configure_logging, log_context, metrics
from .redis_client import ping_redis
from .services import (
    create_task,
    ensure_membership,
    get_or_create_user,
    get_or_create_workspace,
    get_task_by_id,
    get_user_by_id,
    get_users_by_ids,
    list_tasks,
    update_task,
)
from .ui import (
    TaskActionView,
    TaskCreateModal,
    TaskEditModal,
    TaskListView,
    build_error_embed,
    build_help_embed,
    build_status_embed,
    build_success_embed,
    build_task_embed,
    build_task_list_embed,
    build_workspace_setup_embed,
)

LOGGER = logging.getLogger("projectbot.bot")

TIMEZONE_CHOICES = [
    app_commands.Choice(name="UTC", value="UTC"),
    app_commands.Choice(name="Europe/Paris", value="Europe/Paris"),
    app_commands.Choice(name="Europe/London", value="Europe/London"),
    app_commands.Choice(name="Europe/Berlin", value="Europe/Berlin"),
    app_commands.Choice(name="America/New_York", value="America/New_York"),
    app_commands.Choice(name="America/Los_Angeles", value="America/Los_Angeles"),
    app_commands.Choice(name="Asia/Tokyo", value="Asia/Tokyo"),
    app_commands.Choice(name="Asia/Singapore", value="Asia/Singapore"),
]


def create_bot() -> commands.Bot:
    """Create and configure the Discord bot."""
    session_maker = get_sessionmaker()

    intents = discord.Intents.default()
    intents.message_content = False

    bot = commands.Bot(command_prefix="!", intents=intents)

    # ========================================================================
    # Helper Functions for Interactive Callbacks
    # ========================================================================

    async def handle_task_select(interaction: discord.Interaction, task_id: str) -> None:
        """Handle task selection from the list."""
        guild = interaction.guild
        if not guild:
            return

        async with session_maker() as session:
            workspace = await get_or_create_workspace(
                session, guild_id=str(guild.id), name=guild.name
            )
            task = await get_task_by_id(session, workspace_id=workspace.id, task_id=task_id)

            if not task:
                await interaction.response.send_message(
                    embed=build_error_embed("Tache introuvable"),
                    ephemeral=True,
                )
                return

            # Get assignee name if assigned
            assignee_name = None
            if task.assignee_user_id:
                assignee = await get_user_by_id(session, user_id=task.assignee_user_id)
                if assignee:
                    assignee_name = assignee.display_name

            view = TaskActionView(
                task=task,
                assignee_name=assignee_name,
                on_done=handle_task_done,
                on_edit=handle_task_edit,
                on_status_change=handle_status_change,
                on_assign=handle_assign,
            )

            await interaction.response.send_message(
                embed=build_task_embed(task, assignee_name=assignee_name),
                view=view,
                ephemeral=True,
            )

    async def handle_task_done(interaction: discord.Interaction, task_id: str) -> None:
        """Handle marking a task as done."""
        guild = interaction.guild
        if not guild:
            return

        async with session_maker() as session:
            workspace = await get_or_create_workspace(
                session, guild_id=str(guild.id), name=guild.name
            )
            actor = await get_or_create_user(
                session,
                discord_user_id=str(interaction.user.id),
                display_name=interaction.user.display_name,
            )
            task = await get_task_by_id(session, workspace_id=workspace.id, task_id=task_id)

            if not task:
                await interaction.response.send_message(
                    embed=build_error_embed("Tache introuvable"),
                    ephemeral=True,
                )
                return

            task.status = "done"
            await log_action(
                session,
                workspace_id=workspace.id,
                actor_user_id=actor.id,
                action="task.done",
                entity_type="task",
                entity_id=str(task.id),
                payload={"status": "done"},
            )
            await session.commit()

            LOGGER.info("Task marked done id=%s", task.id)

            await interaction.response.edit_message(
                embed=build_success_embed(
                    "Tache terminee",
                    f"**{task.title}** a ete marquee comme terminee.",
                ),
                view=None,
            )

    async def handle_task_edit(interaction: discord.Interaction, task: "Task") -> None:
        """Handle opening the edit modal for a task."""
        modal = TaskEditModal(
            task_id=str(task.id),
            current_title=task.title,
            current_description=task.description,
            callback=handle_task_edit_submit,
        )
        await interaction.response.send_modal(modal)

    async def handle_task_edit_submit(
        interaction: discord.Interaction,
        task_id: str,
        new_title: str,
        new_description: str | None,
    ) -> None:
        """Handle task edit modal submission."""
        guild = interaction.guild
        if not guild:
            return

        async with session_maker() as session:
            workspace = await get_or_create_workspace(
                session, guild_id=str(guild.id), name=guild.name
            )
            actor = await get_or_create_user(
                session,
                discord_user_id=str(interaction.user.id),
                display_name=interaction.user.display_name,
            )
            task = await get_task_by_id(session, workspace_id=workspace.id, task_id=task_id)

            if not task:
                await interaction.response.send_message(
                    embed=build_error_embed("Tache introuvable"),
                    ephemeral=True,
                )
                return

            await update_task(
                session,
                task=task,
                title=new_title,
                description=new_description,
            )
            await log_action(
                session,
                workspace_id=workspace.id,
                actor_user_id=actor.id,
                action="task.update",
                entity_type="task",
                entity_id=str(task.id),
                payload={"title": new_title, "description": new_description},
            )
            await session.commit()

            LOGGER.info("Task updated id=%s", task.id)

            await interaction.response.send_message(
                embed=build_success_embed(
                    "Tache modifiee",
                    f"**{task.title}** a ete mise a jour.",
                ),
                ephemeral=True,
            )

    async def handle_status_change(
        interaction: discord.Interaction,
        task_id: str,
        new_status: str,
    ) -> None:
        """Handle task status change from select menu."""
        guild = interaction.guild
        if not guild:
            return

        async with session_maker() as session:
            workspace = await get_or_create_workspace(
                session, guild_id=str(guild.id), name=guild.name
            )
            actor = await get_or_create_user(
                session,
                discord_user_id=str(interaction.user.id),
                display_name=interaction.user.display_name,
            )
            task = await get_task_by_id(session, workspace_id=workspace.id, task_id=task_id)

            if not task:
                await interaction.response.send_message(
                    embed=build_error_embed("Tache introuvable"),
                    ephemeral=True,
                )
                return

            old_status = task.status
            await update_task(session, task=task, status=new_status)
            await log_action(
                session,
                workspace_id=workspace.id,
                actor_user_id=actor.id,
                action="task.status_change",
                entity_type="task",
                entity_id=str(task.id),
                payload={"old_status": old_status, "new_status": new_status},
            )
            await session.commit()

            LOGGER.info("Task status changed id=%s from=%s to=%s", task.id, old_status, new_status)

            # Get assignee name for refresh
            assignee_name = None
            if task.assignee_user_id:
                assignee = await get_user_by_id(session, user_id=task.assignee_user_id)
                if assignee:
                    assignee_name = assignee.display_name

            # Refresh the task view
            view = TaskActionView(
                task=task,
                assignee_name=assignee_name,
                on_done=handle_task_done,
                on_edit=handle_task_edit,
                on_status_change=handle_status_change,
                on_assign=handle_assign,
            )

            await interaction.response.edit_message(
                embed=build_task_embed(task, assignee_name=assignee_name),
                view=view,
            )

    async def handle_assign(
        interaction: discord.Interaction,
        task_id: str,
        member: discord.Member | discord.User | None,
    ) -> None:
        """Handle assigning a user to a task."""
        guild = interaction.guild
        if not guild:
            return

        async with session_maker() as session:
            workspace = await get_or_create_workspace(
                session, guild_id=str(guild.id), name=guild.name
            )
            actor = await get_or_create_user(
                session,
                discord_user_id=str(interaction.user.id),
                display_name=interaction.user.display_name,
            )
            task = await get_task_by_id(session, workspace_id=workspace.id, task_id=task_id)

            if not task:
                await interaction.response.send_message(
                    embed=build_error_embed("Tache introuvable"),
                    ephemeral=True,
                )
                return

            # Get or create the assignee user if one was selected
            assignee_user_id = None
            assignee_name = None
            if member:
                assignee = await get_or_create_user(
                    session,
                    discord_user_id=str(member.id),
                    display_name=member.display_name,
                )
                assignee_user_id = assignee.id
                assignee_name = assignee.display_name

            await update_task(session, task=task, assignee_user_id=assignee_user_id)
            await log_action(
                session,
                workspace_id=workspace.id,
                actor_user_id=actor.id,
                action="task.assign",
                entity_type="task",
                entity_id=str(task.id),
                payload={"assignee_user_id": str(assignee_user_id) if assignee_user_id else None},
            )
            await session.commit()

            LOGGER.info("Task assigned id=%s assignee=%s", task.id, assignee_name or "None")

            # Refresh the task view
            view = TaskActionView(
                task=task,
                assignee_name=assignee_name,
                on_done=handle_task_done,
                on_edit=handle_task_edit,
                on_status_change=handle_status_change,
                on_assign=handle_assign,
            )

            await interaction.response.edit_message(
                embed=build_task_embed(task, assignee_name=assignee_name),
                view=view,
            )

    async def handle_create_from_list(interaction: discord.Interaction) -> None:
        """Handle create button from task list."""
        modal = TaskCreateModal(callback=handle_create_modal_submit)
        await interaction.response.send_modal(modal)

    async def handle_create_modal_submit(
        interaction: discord.Interaction,
        title: str,
        description: str | None,
        due_in_days: int | None,
    ) -> None:
        """Handle task creation modal submission."""
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(
                embed=build_error_embed("Commande non disponible en DM"),
                ephemeral=True,
            )
            return

        async with session_maker() as session:
            workspace = await get_or_create_workspace(
                session, guild_id=str(guild.id), name=guild.name
            )
            creator = await get_or_create_user(
                session,
                discord_user_id=str(interaction.user.id),
                display_name=interaction.user.display_name,
            )

            task = await create_task(
                session,
                workspace_id=workspace.id,
                title=title,
                description=description,
                assignee_user_id=None,  # No auto-assign - collaborative workspace
                created_by_user_id=creator.id,
                due_in_days=due_in_days,
            )

            await log_action(
                session,
                workspace_id=workspace.id,
                actor_user_id=creator.id,
                action="task.create",
                entity_type="task",
                entity_id=str(task.id),
                payload={"title": title, "due_in_days": due_in_days},
            )
            await session.commit()

            LOGGER.info("Task created id=%s title=%s", task.id, title)

            await interaction.response.send_message(
                embed=build_success_embed(
                    "Tache creee",
                    f"**{title}** a ete ajoutee a vos taches.",
                ),
                ephemeral=True,
            )

    async def handle_refresh_list(interaction: discord.Interaction) -> None:
        """Handle refresh button on task list."""
        guild = interaction.guild
        if not guild:
            return

        async with session_maker() as session:
            workspace = await get_or_create_workspace(
                session, guild_id=str(guild.id), name=guild.name
            )
            tasks = await list_tasks(session, workspace_id=workspace.id, limit=50)

            # Get assignee names
            assignee_ids = [t.assignee_user_id for t in tasks if t.assignee_user_id]
            assignee_names = await get_users_by_ids(session, user_ids=assignee_ids)

        view = TaskListView(
            tasks=tasks,
            on_task_select=handle_task_select,
            on_create=handle_create_from_list,
            on_refresh=handle_refresh_list,
        )

        await interaction.response.edit_message(
            embed=build_task_list_embed(tasks, assignee_names=assignee_names),
            view=view,
        )

    # ========================================================================
    # Bot Events
    # ========================================================================

    async def setup_hook() -> None:
        await init_db()
        LOGGER.info("Database initialized")

    bot.setup_hook = setup_hook

    @bot.event
    async def on_ready() -> None:
        LOGGER.info("Bot connected as %s (id=%s)", bot.user, bot.user.id if bot.user else "?")
        try:
            synced = await bot.tree.sync()
            LOGGER.info("Synced %d slash commands", len(synced))
        except Exception as exc:
            LOGGER.exception("Command sync failed: %s", exc)

    # ========================================================================
    # Main Task Command - Interactive List
    # ========================================================================

    @bot.tree.command(name="task", description="Ouvrir le gestionnaire de taches")
    @app_commands.guild_only()
    async def task_cmd(interaction: discord.Interaction) -> None:
        correlation_id = uuid.uuid4().hex
        start_time = time.perf_counter()
        guild = interaction.guild

        if not guild:
            await interaction.response.send_message(
                embed=build_error_embed("Commande non disponible en DM"),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        with log_context(
            correlation_id=correlation_id,
            guild_id=str(guild.id),
            user_id=str(interaction.user.id),
            operation="cmd.task",
        ):
            async with session_maker() as session:
                workspace = await get_or_create_workspace(
                    session, guild_id=str(guild.id), name=guild.name
                )
                tasks = await list_tasks(session, workspace_id=workspace.id, limit=50)

                # Get assignee names
                assignee_ids = [t.assignee_user_id for t in tasks if t.assignee_user_id]
                assignee_names = await get_users_by_ids(session, user_ids=assignee_ids)

            view = TaskListView(
                tasks=tasks,
                on_task_select=handle_task_select,
                on_create=handle_create_from_list,
                on_refresh=handle_refresh_list,
            )

            duration_ms = (time.perf_counter() - start_time) * 1000
            metrics.record("cmd.task", duration_ms, success=True)
            LOGGER.info("Task list opened tasks=%d duration=%.2fms", len(tasks), duration_ms)

        await interaction.followup.send(
            embed=build_task_list_embed(tasks, assignee_names=assignee_names),
            view=view,
            ephemeral=True,
        )

    # ========================================================================
    # Quick Add Command
    # ========================================================================

    @bot.tree.command(name="add", description="Creer une tache rapidement")
    @app_commands.guild_only()
    @app_commands.describe(
        title="Titre de la tache",
        due="Deadline en jours (optionnel)",
    )
    async def add_cmd(
        interaction: discord.Interaction,
        title: str,
        due: int | None = None,
    ) -> None:
        correlation_id = uuid.uuid4().hex
        start_time = time.perf_counter()
        guild = interaction.guild

        if not guild:
            await interaction.response.send_message(
                embed=build_error_embed("Commande non disponible en DM"),
                ephemeral=True,
            )
            return

        with log_context(
            correlation_id=correlation_id,
            guild_id=str(guild.id),
            user_id=str(interaction.user.id),
            operation="cmd.add",
        ):
            async with session_maker() as session:
                workspace = await get_or_create_workspace(
                    session, guild_id=str(guild.id), name=guild.name
                )
                creator = await get_or_create_user(
                    session,
                    discord_user_id=str(interaction.user.id),
                    display_name=interaction.user.display_name,
                )

                task = await create_task(
                    session,
                    workspace_id=workspace.id,
                    title=title,
                    description=None,
                    assignee_user_id=None,  # No auto-assign - collaborative workspace
                    created_by_user_id=creator.id,
                    due_in_days=due,
                )

                await log_action(
                    session,
                    workspace_id=workspace.id,
                    actor_user_id=creator.id,
                    action="task.create",
                    entity_type="task",
                    entity_id=str(task.id),
                    payload={"title": title, "due_in_days": due},
                )
                await session.commit()

                duration_ms = (time.perf_counter() - start_time) * 1000
                metrics.record("cmd.add", duration_ms, success=True)
                LOGGER.info("Task created id=%s duration=%.2fms", task.id, duration_ms)

        await interaction.response.send_message(
            embed=build_success_embed(
                "Tache creee",
                f"**{title}** a ete ajoutee.\n\nUtilisez `/task` pour la voir.",
            ),
            ephemeral=True,
        )

    # ========================================================================
    # Setup Command
    # ========================================================================

    @bot.tree.command(name="setup", description="Initialiser le workspace")
    @app_commands.guild_only()
    @app_commands.describe(timezone="Fuseau horaire")
    @app_commands.choices(timezone=TIMEZONE_CHOICES)
    async def setup_cmd(interaction: discord.Interaction, timezone: str | None = None) -> None:
        correlation_id = uuid.uuid4().hex
        start_time = time.perf_counter()
        guild = interaction.guild

        if not guild:
            await interaction.response.send_message(
                embed=build_error_embed("Commande non disponible en DM"),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        with log_context(
            correlation_id=correlation_id,
            guild_id=str(guild.id),
            user_id=str(interaction.user.id),
            operation="cmd.setup",
        ):
            async with session_maker() as session:
                workspace = await get_or_create_workspace(
                    session,
                    guild_id=str(guild.id),
                    name=guild.name,
                    timezone_name=timezone or "UTC",
                )
                user = await get_or_create_user(
                    session,
                    discord_user_id=str(interaction.user.id),
                    display_name=interaction.user.display_name,
                )
                await ensure_membership(
                    session,
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role="admin",
                )
                await log_action(
                    session,
                    workspace_id=workspace.id,
                    actor_user_id=user.id,
                    action="workspace.setup",
                    entity_type="workspace",
                    entity_id=str(workspace.id),
                    payload={"timezone": workspace.timezone},
                )
                await session.commit()

            duration_ms = (time.perf_counter() - start_time) * 1000
            metrics.record("cmd.setup", duration_ms, success=True)
            LOGGER.info("Setup completed duration=%.2fms", duration_ms)

        await interaction.followup.send(
            embed=build_workspace_setup_embed(guild.name, timezone or "UTC"),
            ephemeral=True,
        )

    # ========================================================================
    # Status Command
    # ========================================================================

    @bot.tree.command(name="status", description="Voir l'etat du systeme")
    @app_commands.guild_only()
    async def status_cmd(interaction: discord.Interaction) -> None:
        correlation_id = uuid.uuid4().hex
        start_time = time.perf_counter()

        await interaction.response.defer(ephemeral=True)

        with log_context(
            correlation_id=correlation_id,
            guild_id=str(interaction.guild_id),
            user_id=str(interaction.user.id),
            operation="cmd.status",
        ):
            db_ok = await ping_db()
            redis_ok = await ping_redis()
            latency_ms = (time.perf_counter() - start_time) * 1000

            metrics.record("cmd.status", latency_ms, success=True)
            LOGGER.info("Status db=%s redis=%s duration=%.2fms", db_ok, redis_ok, latency_ms)

        await interaction.followup.send(
            embed=build_status_embed(db_ok, redis_ok, latency_ms),
            ephemeral=True,
        )

    # ========================================================================
    # Help Command
    # ========================================================================

    @bot.tree.command(name="help", description="Aide")
    async def help_cmd(interaction: discord.Interaction) -> None:
        with log_context(
            correlation_id=uuid.uuid4().hex,
            user_id=str(interaction.user.id),
            operation="cmd.help",
        ):
            LOGGER.info("Help command")
            metrics.record("cmd.help", 0, success=True)

        await interaction.response.send_message(
            embed=build_help_embed(),
            ephemeral=True,
        )

    # ========================================================================
    # Ping Command
    # ========================================================================

    @bot.tree.command(name="ping", description="Verifier que le bot repond")
    async def ping_cmd(interaction: discord.Interaction) -> None:
        with log_context(
            correlation_id=uuid.uuid4().hex,
            user_id=str(interaction.user.id),
            operation="cmd.ping",
        ):
            latency_ms = bot.latency * 1000
            LOGGER.info("Ping latency=%.2fms", latency_ms)
            metrics.record("cmd.ping", latency_ms, success=True)

        await interaction.response.send_message(
            embed=build_success_embed("Pong", f"Latence: {latency_ms:.0f}ms"),
            ephemeral=True,
        )

    return bot


def main() -> None:
    """Main entry point for the bot."""
    settings = get_settings()
    json_format = settings.environment == "prod"
    configure_logging(settings.log_level, json_format=json_format)

    LOGGER.info(
        "Starting ProjectBot env=%s log_level=%s",
        settings.environment,
        settings.log_level,
    )

    if not settings.discord_token:
        LOGGER.critical("DISCORD_TOKEN is required")
        raise RuntimeError("DISCORD_TOKEN is required")

    bot = create_bot()
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
