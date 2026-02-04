import logging
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from .audit import log_action
from .config import get_settings
from .db import get_sessionmaker, init_db, ping_db
from .logging import configure_logging, log_context
from .redis_client import ping_redis
from .services import (
    create_task,
    ensure_membership,
    find_task_by_prefix,
    format_task_list,
    get_or_create_user,
    get_or_create_workspace,
    list_tasks,
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
    # Shared DB session factory for all commands.
    session_maker = get_sessionmaker()

    intents = discord.Intents.default()
    intents.message_content = False

    bot = commands.Bot(command_prefix="!", intents=intents)

    async def setup_hook() -> None:
        # Ensure tables exist before commands run (minimal bootstrap).
        await init_db()

    bot.setup_hook = setup_hook

    @bot.event
    async def on_ready():
        LOGGER.info("Connected as %s", bot.user)
        try:
            # Register slash commands with Discord.
            synced = await bot.tree.sync()
            LOGGER.info("Synced %s commands", len(synced))
        except Exception as exc:
            LOGGER.exception("Command sync failed: %s", exc)

    @bot.tree.command(name="ping", description="Health check for ProjectBot")
    async def ping(interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Pong!")

    # --- Workspace bootstrap ---
    @bot.tree.command(name="setup", description="Initialise le workspace pour ce serveur")
    @app_commands.guild_only()
    @app_commands.describe(timezone="Fuseau horaire (ex: Europe/Paris)")
    @app_commands.choices(timezone=TIMEZONE_CHOICES)
    async def setup(interaction: discord.Interaction, timezone: str | None = None) -> None:
        correlation_id = uuid.uuid4().hex
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Commande disponible uniquement en serveur.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        with log_context(
            correlation_id=correlation_id,
            guild_id=str(guild.id),
            channel_id=str(interaction.channel_id),
            user_id=str(interaction.user.id),
        ):
            async with session_maker() as session:
                # Upsert workspace/user + ensure admin membership.
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

        LOGGER.info("Workspace setup completed for guild=%s", guild.id)

        await interaction.followup.send(
            f"Workspace initialise pour **{guild.name}** (timezone: {timezone or 'UTC'}).",
            ephemeral=True,
        )

    # --- Task commands ---
    task_group = app_commands.Group(name="task", description="Gestion des taches")

    @task_group.command(name="add", description="Ajouter une tache")
    @app_commands.guild_only()
    @app_commands.describe(
        title="Titre de la tache",
        description="Description optionnelle",
        assignee="Assigne a un membre",
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
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Commande disponible uniquement en serveur.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        with log_context(
            correlation_id=correlation_id,
            guild_id=str(guild.id),
            channel_id=str(interaction.channel_id),
            user_id=str(interaction.user.id),
        ):
            async with session_maker() as session:
                # Ensure workspace + users exist, then persist the task.
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

        LOGGER.info("Task created id=%s", task.id)

        await interaction.followup.send(
            f"Tache creee: **{title}** (id: `{str(task.id)[:8]}`)", ephemeral=True
        )

    @task_group.command(name="list", description="Lister les taches")
    @app_commands.guild_only()
    @app_commands.describe(limit="Nombre max de taches (defaut 10)")
    async def task_list(interaction: discord.Interaction, limit: int | None = None) -> None:
        correlation_id = uuid.uuid4().hex
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Commande disponible uniquement en serveur.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        with log_context(
            correlation_id=correlation_id,
            guild_id=str(guild.id),
            channel_id=str(interaction.channel_id),
            user_id=str(interaction.user.id),
        ):
            async with session_maker() as session:
                # Read-only list for current workspace.
                workspace = await get_or_create_workspace(
                    session,
                    guild_id=str(guild.id),
                    name=guild.name,
                )
                tasks = await list_tasks(
                    session, workspace_id=workspace.id, limit=limit or 10
                )

        LOGGER.info("Listed %s tasks", len(tasks))

        if not tasks:
            await interaction.followup.send("Aucune tache pour le moment.", ephemeral=True)
            return

        await interaction.followup.send(
            f"```\n{format_task_list(tasks)}\n```",
            ephemeral=True,
        )

    @task_group.command(name="done", description="Marquer une tache comme terminee")
    @app_commands.guild_only()
    @app_commands.describe(task_id="Prefixe de l'id de tache")
    async def task_done(interaction: discord.Interaction, task_id: str) -> None:
        correlation_id = uuid.uuid4().hex
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Commande disponible uniquement en serveur.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        with log_context(
            correlation_id=correlation_id,
            guild_id=str(guild.id),
            channel_id=str(interaction.channel_id),
            user_id=str(interaction.user.id),
        ):
            async with session_maker() as session:
                # Resolve task by prefix, mark done, and audit.
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
                    session, workspace_id=workspace.id, task_id_prefix=task_id
                )
                if not task:
                    await interaction.followup.send("Tache introuvable.", ephemeral=True)
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

        await interaction.followup.send(
            f"Tache terminee: `{str(task.id)[:8]}`", ephemeral=True
        )

    bot.tree.add_command(task_group)

    # --- Diagnostics ---
    @bot.tree.command(name="status", description="Diagnostic du bot")
    @app_commands.guild_only()
    async def status(interaction: discord.Interaction) -> None:
        correlation_id = uuid.uuid4().hex
        await interaction.response.defer(ephemeral=True)
        with log_context(
            correlation_id=correlation_id,
            guild_id=str(interaction.guild_id),
            channel_id=str(interaction.channel_id),
            user_id=str(interaction.user.id),
        ):
            db_ok = await ping_db()
            redis_ok = await ping_redis()
        await interaction.followup.send(
            f"DB: {'OK' if db_ok else 'KO'} | Redis: {'OK' if redis_ok else 'KO'}",
            ephemeral=True,
        )

    @bot.tree.command(name="help", description="Aide rapide")
    async def help_cmd(interaction: discord.Interaction) -> None:
        # Keep help short and actionable.
        await interaction.response.send_message(
            "Commandes: `/setup`, `/task add`, `/task list`, `/task done`, `/status`",
            ephemeral=True,
        )

    return bot


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    if not settings.discord_token:
        raise RuntimeError("DISCORD_TOKEN is required to run the bot")

    bot = create_bot()
    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
