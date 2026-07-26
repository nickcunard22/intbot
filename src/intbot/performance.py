import logging
from dataclasses import dataclass
from random import choice

logger = logging.getLogger(__name__)

generic_good_messages = (
    "balled out",
    "is him",
)

generic_bad_messages = (
    "sprinted it",
    "ran it down",
    "inted",
    "is trolling",
)


@dataclass
class Performance:
    """One player's stat line from one match."""

    summoner_name: str
    discord_id: int
    champion_name: str
    kills: int
    deaths: int
    assists: int
    kp: float
    cs: int
    cspm: float
    game_length: int
    win: bool
    adjusted_kda: float

    @property
    def kda(self):
        return f"{self.kills}/{self.deaths}/{self.assists}"

    @property
    def duration(self):
        return f"{int(self.game_length / 60)}m {int(self.game_length % 60)}s"

    def summary(self):
        """One-line form for the logs."""
        return (
            f"{self.summoner_name} {self.kda} on {self.champion_name} "
            f"({'W' if self.win else 'L'}), "
            f"{int(self.kp * 100)}% KP, {self.cs} CS ({self.cspm}/min), "
            f"{self.duration}, adjusted kda {self.adjusted_kda:.2f}"
        )


def extract_performance(player, match):
    """
    Pulls one player's stats out of a match payload,
    or None if they aren't in it or the data is incomplete.
    """
    for participant in match["info"]["participants"]:
        if player.puuid != participant["puuid"]:
            continue

        try:
            kills = participant["kills"]
            deaths = participant["deaths"]
            assists = participant["assists"]
            kp = participant["challenges"]["killParticipation"]
            champion_name = participant["championName"]
            win = participant["win"]  # bool win
            game_length = participant["challenges"]["gameLength"]
            cs = (
                participant["neutralMinionsKilled"]
                + participant["totalMinionsKilled"]
            )
        except KeyError as e:
            logger.info("%s: match data missing %s", player.summoner_name, e)
            return None

        cspm = round((cs / (game_length / 60)), 2)

        # arbitrarily lowers the value of assists as the game length goes on
        # according the function https://www.desmos.com/calculator/pzdgm6dkil
        adjusted_assists = (
            assists
            if game_length < 15 * 60
            else assists * (20 / (game_length / 60 + 5))
        )
        # a deathless game is scored as if it had one, the usual kda convention
        adjusted_kda = (kills + adjusted_assists) / max(deaths, 1)

        return Performance(
            summoner_name=player.summoner_name,
            discord_id=player.discord_id,
            champion_name=champion_name,
            kills=kills,
            deaths=deaths,
            assists=assists,
            kp=kp,
            cs=cs,
            cspm=cspm,
            game_length=game_length,
            win=win,
            adjusted_kda=adjusted_kda,
        )

    return None


def performance_message(performance):
    """
    The message to post for a stat line,
    or None if nothing about it was worth saying.
    """
    # precedence:
    # good > bad
    # unique > non-unique
    if performance.cspm >= 10:
        message = "might be chovy"
    elif performance.adjusted_kda > 6:
        message = choice(generic_good_messages)
    elif (
        performance.kills == 0
        and performance.assists == 0
        and performance.deaths >= 5
    ):
        message = "has cancer"
    elif performance.adjusted_kda < 1:
        message = choice(generic_bad_messages)
    else:
        return None

    return (
        f"<@{performance.discord_id}> {message}"
        f"\n{'**Victory**' if performance.win else '**Defeat**'}"
        f"\n{performance.champion_name}"
        f"\n{performance.kda} ({int(performance.kp * 100)}% KP)"
        f"\n{performance.cs} CS ({performance.cspm}/min)"
        f"\n{performance.duration}"
    )
