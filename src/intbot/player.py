import json

from .config import SQUAD_PATH


class Player:
    """Player object. Stores the name info needed to identify a player."""

    def __init__(self, summoner_name, puuid, tagline, discord_id, discord_username):
        self.summoner_name = summoner_name
        self.puuid = puuid
        self.tagline = tagline
        self.discord_id = discord_id
        self.discord_username = discord_username

    def __eq__(self, other):
        return self.puuid == other.puuid


def load_squad():
    with open(SQUAD_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def save_squad(squad):
    with open(SQUAD_PATH, "w", encoding="utf-8") as file:
        json.dump(squad, file, indent=4)


async def update_players_list(players):
    """
    Updates a players list if that player is not already in the list.
    """
    squad = load_squad()

    for user in squad:
        player = Player(
            squad[user]["summoner_name"],
            squad[user]["puuid"],
            squad[user]["tagline"],
            squad[user]["discord_id"],
            squad[user]["discord_username"]
        )

        if player not in players:
            players.append(player)

    return players
