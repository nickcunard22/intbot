import asyncio
import json
import logging

# pycord imports
import discord
from discord.ext import commands
from discord import option

# .env import
from dotenv import load_dotenv
from os import getenv

from riot_api_requests import ResponseError, get_puuid, get_match, get_active_match
from performance_tracking import match_performance
from Player import update_players_list

# setup token from .env
load_dotenv()
DISCORD_TOKEN = getenv("DISCORD_TOKEN")


# personal server, evil gang
guild_ids = [1240038741381484544, 1038910618259951757]

bot = commands.Bot(intents=discord.Intents.all())

with open("squad.json", "r+", encoding="utf-8") as file:
    squad = json.load(file)  # dict squad


@bot.event
async def on_ready():
    logger.info("Started")


@bot.slash_command(
    name="add_self",
    description="Add your league account to be tracked",
    guild_ids=guild_ids,
)
@option("summoner_name", description="your in game name")
@option("tagline", description="your tagline (what comes after the #)")
async def add_self(ctx, summoner_name, tagline):
    """Adds a user to the system based on their discord ID and a given summoner name and tagline."""
    try:
        squad[ctx.author.name] = {
            "puuid": get_puuid(summoner_name, tagline),
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
        with open("squad.json", "r+", encoding="utf-8") as file:
            json.dump(squad, file, indent=4)
    except IOError:
        await ctx.respond("Could not update data.")
        return

    await ctx.respond("Successfully added!")


@bot.slash_command(
    name="list_users",
    description="Lists all users the bot is currently tracking",
    guild_ids=guild_ids,
)
async def list_users(ctx):
    with open("squad.json", "r+", encoding="utf-8") as file:
        squad = json.load(file)  # dict squad

    response = ""
    for user in squad:
        response += f"<@{squad[user]["discord_id"]}>: {squad[user]["summoner_name"]}#{squad[user]["tagline"]}\n"

    await ctx.respond(response, allowed_mentions=discord.AllowedMentions.none())


@bot.slash_command(name="test", guild_ids=guild_ids)
async def test(ctx):
    await ctx.respond()


async def in_game_check(player, match_id):  # small loop
    while player.in_game is True:
        try:
            recent_match = get_match(f"NA1_{match_id}")
        except ResponseError as e:
            if int(e) == 404:
                logger.info(
                    f"{player.summoner_name} still in game"
                )
                await asyncio.sleep(12)
            else:
                logger.info(f"Error: {int(e)} {str(e)}")
        except Exception as e:
            logger.info(e)
        else:
            player.in_game = False
            logger.info(
                f"{player.summoner_name} no longer in game"
            )
            # SEND FNUNUY MESSGAE
            channel = await bot.fetch_channel(1166600969426051082)  # tylers-ints
            try:
                await channel.send(match_performance(player, recent_match))
            except UnboundLocalError:
                logger.info(player.summoner_name + ": no performance")


async def player_loop_check():  # big loop
    players = []

    while True:
        players = await update_players_list(players)

        for player in players:
            if player.in_game is False:
                try:
                    active_match = get_active_match(player.puuid)
                except ResponseError as e:
                    if int(e) == 404:
                        logger.info(
                            f"{player.summoner_name} not in game"
                        )
                    else:
                        logger.info(f"Error: {int(e)} {str(e)}")
                else:  # player IS in game
                    game_id = active_match["gameId"]
                    player.in_game = True
                    logger.info(
                        f"{player.summoner_name} in game"
                    )
                    asyncio.ensure_future(in_game_check(player, game_id))

        await asyncio.sleep(5 * 60)

def exception_handler(loop, context):
    exception = context["exception"]
    message = context["message"]
    logger.error(f"Error: {exception}\nMessage: {message}")

#setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger()

loop = asyncio.get_event_loop()
loop.set_exception_handler(exception_handler) #might not work

asyncio.ensure_future(player_loop_check())
asyncio.ensure_future(bot.start(DISCORD_TOKEN))

loop.run_forever()
