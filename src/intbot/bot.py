import logging

# pycord imports
import discord
from discord.ext import commands
from discord import option

from .config import GUILD_IDS, INTS_CHANNEL_ID
from .riot_api_requests import ResponseError, get_puuid
from .player import load_squad, save_squad
from .tracker import GameTracker

logger = logging.getLogger(__name__)

bot = commands.Bot(intents=discord.Intents.all())


async def announce(message):
    # get_channel hits the cache, fetch_channel is the fallback for a cold start
    channel = bot.get_channel(INTS_CHANNEL_ID)
    if channel is None:
        channel = await bot.fetch_channel(INTS_CHANNEL_ID)
    await channel.send(message)


tracker = GameTracker(announce=announce)


@bot.event
async def on_ready():
    logger.info("Started")


@bot.slash_command(
    name="add_self",
    description="Add your league account to be tracked",
    guild_ids=GUILD_IDS,
)
@option("summoner_name", description="your in game name")
@option("tagline", description="your tagline (what comes after the #)")
async def add_self(ctx, summoner_name, tagline):
    """Adds a user to the system based on their discord ID and a given summoner name and tagline."""
    squad = load_squad()

    try:
        squad[ctx.author.name] = {
            "puuid": await get_puuid(summoner_name, tagline),
            "summoner_name": summoner_name,
            "tagline": tagline,
            "discord_id": ctx.author.id,
            "discord_username": ctx.author.name,
        }
    except ResponseError as e:
        if int(e) == 404:
            await ctx.respond("Invalid Summoner Name or Tagline")
            return
        else:
            await ctx.respond(f"Error: {int(e)} {str(e)}")
            return

    try:
        save_squad(squad)
    except IOError:
        await ctx.respond("Could not update data.")
        return

    await ctx.respond("Successfully added!")


@bot.slash_command(
    name="list_users",
    description="Lists all users the bot is currently tracking",
    guild_ids=GUILD_IDS,
)
async def list_users(ctx):
    squad = load_squad()

    response = ""
    for user in squad:
        response += f"<@{squad[user]['discord_id']}>: {squad[user]['summoner_name']}#{squad[user]['tagline']}\n"

    await ctx.respond(response, allowed_mentions=discord.AllowedMentions.none())


@bot.slash_command(name="test", guild_ids=GUILD_IDS)
async def test(ctx):
    await ctx.respond()


