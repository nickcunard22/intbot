import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
RIOT_KEY = os.getenv("RIOT_KEY")

# set LOG_LEVEL=DEBUG for per-player spectator results on every sweep
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# logs also go here so they survive the terminal, set LOG_FILE= to disable
LOG_FILE = os.getenv("LOG_FILE", "intbot.log")

# relative to the working directory by default, set SQUAD_PATH to pin it
SQUAD_PATH = Path(os.getenv("SQUAD_PATH", "squad.json"))

# personal server, evil gang
GUILD_IDS = [1240038741381484544, 1038910618259951757]

INTS_CHANNEL_ID = 1166600969426051082  # tylers-ints
