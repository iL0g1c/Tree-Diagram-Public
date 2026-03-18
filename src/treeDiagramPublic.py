import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import logging
import sys

load_dotenv()

BOT_TOKEN = os.getenv('DISCORD_TOKEN')

class TreeDiagramPublic(commands.Bot):
    def __init__(self):
        # logger setup
        self.logger = logging.getLogger("TreeDiagram")
        self.logger.setLevel(logging.INFO)
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(module)s:%(lineno)d %(message)s",
        ))

        # avoid duplicate handlers if reloaded
        if not any(isinstance(h, logging.StreamHandler) for h in self.logger.handlers):
            self.logger.addHandler(console)

        # bot setup
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="=", intents=intents)

    async def on_ready(self):
        self.logger.log(20, f'{self.user} has connected to Discord!')

    async def on_resumed(self):
        # Correlate Discord RESUMEDs with logs
        self.logger.info("Discord gateway RESUMED")

    async def setup_hook(self) -> None:
        # startup sequence
        self.logger.log(20, "Starting up...")
        self.logger.log(20, "Loading Extensions...")
        await self._load_extensions()
        self.logger.log(20, "Syncing commands...")
        try:
            synced = await self.tree.sync()
            self.logger.log(20, f"Synced {len(synced)} command(s)")
        except Exception as e:
            self.logger.log(40, f"Exception while syncing commands. Error: {e}")
        self.logger.log(20, "Connecting to discord...")

    async def _load_extensions(self) -> None:
        for extension in ("queryDatabase",):
            await self.load_extension(f"cogs.{extension}")

bot = TreeDiagramPublic()

@bot.tree.command(name="ping", description="Check bot connection and latency.")
async def ping(interaction: discord.Interaction):
    # COMMAND - ping
    # Sends bot latency
    delay = round(bot.latency * 1000)
    embed = discord.Embed(title="Pong!", description=f"Latency: {delay}ms", color=discord.Color.green())
    await interaction.response.send_message(embed=embed)

def main():
    bot.run(BOT_TOKEN)
    

if __name__ == "__main__":
    main()
    