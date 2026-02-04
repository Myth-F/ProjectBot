"""
ProjectBot Discord Bot
======================
Main Discord bot with slash commands and observability.
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
    find_task_by_prefix,
    get_or_create_user,
    get_or_create_workspace,
    list_tasks,
)
from .ui import (
    embed_guild_only,
    embed_help,
    embed_ping,
    embed_status,
    embed_task_created,
    embed_task_done,
    embed_task_list,
    embed_task_not_found,
    embed_workspace_setup,
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

    async def setup_hook() -> None:
        await init_db()
        LOGGER.info("Database initialized")

    bot.setup_hook = setup_hook

    # ========================================================================
    # Bot Events
    # ========================================================================

    @bot.event
    async def on_ready() -> None:
        LOGGER.info("Bot connected as %s (id=%s)", bot.user, bot.user.id if bot.user else "?")
        try:
            synced = await bot.tree.sync()
            LOGGER.info("Synced %d slash commands", len(synced))
        except Exception as exc:
            LOGGER.exception("Command sync failed: %s", exc)

    # ========================================================================
    # Health Check
    # ========================================================================

    @bot.tree.command(name="ping", description="Health check - verifie que le bot repond")
    async def ping(interaction: discord.Interaction) -> None:
        correlation_id = uuid.uuid4().hex
        start_time = time.perf_counter()

        with log_context(
            correlation_id=correlation_id,
            user_id=str(interaction.user.id),
            operation="cmd.ping",
        ):
            LOGGER.info("Ping command received")
            latency_ms = (time.perf_counter() - start_time) * 1000 + (bot.latency * 1000)

            embed = embed_ping(latency_ms)
            await interaction.response.send_message(embed=embed, ephemeral=True)

            metrics.record("cmd.ping", latency_ms, success=True)
            LOGGER.info("Ping response sent latency=%.2fms", latency_ms)

    # ========================================================================
    # Workspace Setup
    # ========================================================================

    @bot.tree.command(name="setup", description="Initialise le workspace pour ce serveur")
    @app_commands.guild_only()
    @app_commands.describe(timezone="Fuseau horaire (ex: Europe/Paris)")
    @app_commands.choices(timezone=TIMEZONE_CHOICES)
    async def setup(interaction: discord.Interaction, timezone: str | None = None) -> None:
        correlation_id = uuid.uuid4().hex
        start_time = time.perf_counter()
        guild = interaction.guild

        if not guild:
            await interaction.response.send_message(embed=embed_guild_only(), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        with log_context(
            correlation_id=correlation_id,
            guild_id=str(guild.id),
            channel_id=str(interaction.channel_id),
            user_id=str(interaction.user.id),
            operation="cmd.setup",
        ):
            LOGGER.info("Setup command for guild=%s timezone=%s", guild.name, timezone or "UTC")

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
            LOGGER.info("Workspace setup completed duration=%.2fms", duration_ms)

        embed = embed_workspace_setup(guild.name, timezone or "UTC")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ========================================================================
    # Task Commands
    # ========================================================================

    task_group = app_commands.Group(name="task", description="Gestion des taches")

    @task_group.command(name="add", description="Ajouter une nouvelle tache")
    @app_commands.guild_only()
    @app_commands.describe(
        title="Titre de la tache",
        description="Description optionnelle",
        assignee="Assigner a un membre",
        due_in_days="Deadline en jours (ex: 3)",
    )
    async def task_add(
        interaction: discord.Interaction,
        title: str,
        description: str | None = None,
        assignee: discord.Member | None = None,
        due_in_days: int | None = None,
    ) -> None:
        correlation_id = uuid.uuid4().hex
        start_time = time.perf_counter()
        guild = interaction.guild

        if not guild:
            await interaction.response.send_message(embed=embed_guild_only(), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        with log_context(
            correlation_id=correlation_id,
            guild_id=str(guild.id),
            channel_id=str(interaction.channel_id),
            user_id=str(interaction.user.id),
            operation="cmd.task.add",
        ):
            LOGGER.info("Task add command title=%s assignee=%s due=%s", title, assignee, due_in_days)

            async with session_maker() as session:
                workspace = await get_or_create_workspace(
                    session,
                    guild_id=str(guild.id),
                    name=guild.name,
                )
                creator = await get_or_create_user(
                    session,
                    discord_user_id=str(interaction.user.id),
                    display_name=interaction.user.display_name,
                )

                assignee_user_id = None
                if assignee:
                    assignee_user = await get_or_create_user(
                        session,
                        discord_user_id=str(assignee.id),
                        display_name=assignee.display_name,
                    )
                    assignee_user_id = assignee_user.id

                task = await create_task(
                    session,
                    workspace_id=workspace.id,
                    title=title,
                    description=description,
                    assignee_user_id=assignee_user_id,
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
                    payload={
                        "title": title,
                        "assignee": str(assignee.id) if assignee else None,
                        "due_in_days": due_in_days,
                    },
                )
                await session.commit()

                duration_ms = (time.perf_counter() - start_time) * 1000
                metrics.record("cmd.task.add", duration_ms, success=True)
                LOGGER.info("Task created id=%s duration=%.2fms", task.id, duration_ms)

                embed = embed_task_created(task)
                await interaction.followup.send(embed=embed, ephemeral=True)

    @task_group.command(name="list", description="Lister les taches du workspace")
    @app_commands.guild_only()
    @app_commands.describe(limit="Nombre max de taches (defaut: 10)")
    async def task_list_cmd(interaction: discord.Interaction, limit: int | None = None) -> None:
        correlation_id = uuid.uuid4().hex
        start_time = time.perf_counter()
        guild = interaction.guild

        if not guild:
            await interaction.response.send_message(embed=embed_guild_only(), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        with log_context(
            correlation_id=correlation_id,
            guild_id=str(guild.id),
            channel_id=str(interaction.channel_id),
            user_id=str(interaction.user.id),
            operation="cmd.task.list",
        ):
            LOGGER.info("Task list command limit=%s", limit or 10)

            async with session_maker() as session:
                workspace = await get_or_create_workspace(
                    session,
                    guild_id=str(guild.id),
                    name=guild.name,
                )
                tasks = await list_tasks(
                    session,
                    workspace_id=workspace.id,
                    limit=limit or 10,
                )

            duration_ms = (time.perf_counter() - start_time) * 1000
            metrics.record("cmd.task.list", duration_ms, success=True)
            LOGGER.info("Listed %d tasks duration=%.2fms", len(tasks), duration_ms)

        embed = embed_task_list(tasks, workspace_name=guild.name)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @task_group.command(name="done", description="Marquer une tache comme terminee")
    @app_commands.guild_only()
    @app_commands.describe(task_id="Prefixe de l'ID de la tache")
    async def task_done_cmd(interaction: discord.Interaction, task_id: str) -> None:
        correlation_id = uuid.uuid4().hex
        start_time = time.perf_counter()
        guild = interaction.guild

        if not guild:
            await interaction.response.send_message(embed=embed_guild_only(), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        with log_context(
            correlation_id=correlation_id,
            guild_id=str(guild.id),
            channel_id=str(interaction.channel_id),
            user_id=str(interaction.user.id),
            operation="cmd.task.done",
        ):
            LOGGER.info("Task done command task_id_prefix=%s", task_id)

            async with session_maker() as session:
                workspace = await get_or_create_workspace(
                    session,
                    guild_id=str(guild.id),
                    name=guild.name,
                )
                actor = await get_or_create_user(
                    session,
                    discord_user_id=str(interaction.user.id),
                    display_name=interaction.user.display_name,
                )

                task = await find_task_by_prefix(
                    session,
                    workspace_id=workspace.id,
                    task_id_prefix=task_id,
                )

                if not task:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    metrics.record("cmd.task.done", duration_ms, success=False)
                    LOGGER.warning("Task not found prefix=%s", task_id)

                    embed = embed_task_not_found(task_id)
                    await interaction.followup.send(embed=embed, ephemeral=True)
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

                duration_ms = (time.perf_counter() - start_time) * 1000
                metrics.record("cmd.task.done", duration_ms, success=True)
                LOGGER.info("Task marked done id=%s duration=%.2fms", task.id, duration_ms)

                embed = embed_task_done(task)
                await interaction.followup.send(embed=embed, ephemeral=True)

    bot.tree.add_command(task_group)

    # ========================================================================
    # Diagnostics
    # ========================================================================

    @bot.tree.command(name="status", description="Diagnostic du bot et des services")
    @app_commands.guild_only()
    async def status_cmd(interaction: discord.Interaction) -> None:
        correlation_id = uuid.uuid4().hex
        start_time = time.perf_counter()

        await interaction.response.defer(ephemeral=True)

        with log_context(
            correlation_id=correlation_id,
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            user_id=str(interaction.user.id),
            operation="cmd.status",
        ):
            LOGGER.info("Status command")

            db_ok = await ping_db()
            redis_ok = await ping_redis()

            duration_ms = (time.perf_counter() - start_time) * 1000
            metrics.record("cmd.status", duration_ms, success=True)
            LOGGER.info("Status check db=%s redis=%s duration=%.2fms", db_ok, redis_ok, duration_ms)

        embed = embed_status(db_ok, redis_ok)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ========================================================================
    # Help
    # ========================================================================

    @bot.tree.command(name="help", description="Aide et liste des commandes")
    async def help_cmd(interaction: discord.Interaction) -> None:
        correlation_id = uuid.uuid4().hex

        with log_context(
            correlation_id=correlation_id,
            user_id=str(interaction.user.id),
            operation="cmd.help",
        ):
            LOGGER.info("Help command")
            metrics.record("cmd.help", 0, success=True)

        embed = embed_help()
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ========================================================================
    # Metrics Command (internal/debug)
    # ========================================================================

    @bot.tree.command(name="metrics", description="Affiche les metriques internes du bot")
    @app_commands.guild_only()
    async def metrics_cmd(interaction: discord.Interaction) -> None:
        correlation_id = uuid.uuid4().hex

        with log_context(
            correlation_id=correlation_id,
            user_id=str(interaction.user.id),
            operation="cmd.metrics",
        ):
            LOGGER.info("Metrics command")

            all_stats = metrics.get_all_stats()

            if not all_stats:
                await interaction.response.send_message(
                    "```\nAucune metrique disponible.\n```",
                    ephemeral=True,
                )
                return

            lines = [
                "+--[ Metriques ]-------------------------+",
                "| Operation          | Cnt | Avg    | SR  |",
                "+----------------------------------------+",
            ]

            for stat in all_stats:
                op = stat["operation"][:18].ljust(18)
                cnt = str(stat["count"]).rjust(3)
                avg = f"{stat['avg_duration_ms']:.0f}ms".rjust(6)
                sr = f"{stat['success_rate']*100:.0f}%".rjust(3)
                lines.append(f"| {op} | {cnt} | {avg} | {sr} |")

            lines.append("+----------------------------------------+")

            await interaction.response.send_message(
                f"```\n{chr(10).join(lines)}\n```",
                ephemeral=True,
            )

    return bot


def main() -> None:
    """Main entry point for the bot."""
    settings = get_settings()
    json_format = settings.environment == "prod"
    configure_logging(settings.log_level, json_format=json_format)

    LOGGER.info(
        "Starting ProjectBot env=%s log_level=%s format=%s",
        settings.environment,
        settings.log_level,
        "json" if json_format else "text",
    )

    if not settings.discord_token:
        LOGGER.critical("DISCORD_TOKEN is required to run the bot")
        raise RuntimeError("DISCORD_TOKEN is required to run the bot")

    bot = create_bot()
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
