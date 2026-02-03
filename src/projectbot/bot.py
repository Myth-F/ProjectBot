import logging

import discord
from discord import app_commands
from discord.ext import commands

from .config import get_settings
from .logging import configure_logging


def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = False

    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        logging.getLogger("projectbot.bot").info("Connected as %s", bot.user)
        try:
            synced = await bot.tree.sync()
            logging.getLogger("projectbot.bot").info("Synced %s commands", len(synced))
        except Exception as exc:
            logging.getLogger("projectbot.bot").exception("Command sync failed: %s", exc)

    @bot.tree.command(name="ping", description="Health check for ProjectBot")
    async def ping(interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Pong!")

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
