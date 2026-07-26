import json
import os
import requests
from time import sleep

#.env import
from dotenv import load_dotenv

load_dotenv()
key = os.getenv("RIOT_KEY")

TIMEOUT = 5

class ResponseError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message

    def __int__(self):
        return self.code

    def __str__(self):
        return self.message


def handle_errors(specific_key=None):
    """
    Decorator for request functions.
    The default return is a .json file.
    If specific_key is set, the decorator will return the value at that key instead.
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                response = func(*args, **kwargs)
            except requests.exceptions.Timeout:
                print("Request timed out. Trying again: ")
                return wrapper(*args, **kwargs)
            except TypeError as e:
                print(e + "\n" + response + "\nTrying again: ")
                return wrapper(*args, **kwargs)
            match response.status_code:
                case 200:
                    if specific_key is None:
                        return response.json()
                    else:
                        return response.json()[specific_key]
                case 429:
                    time_to_wait = response.headers["Retry-After"]
                    print("time_to_wait: " + time_to_wait)
                    sleep(int(time_to_wait))
                    return wrapper(*args, **kwargs)
                case _:
                    raise ResponseError(
                        response.status_code, response.json()["status"]["message"]
                    )
                    

        return wrapper

    return decorator


@handle_errors(specific_key="puuid")
def get_puuid(summoner_name, tagline):
    """Uses https://developer.riotgames.com/apis#account-v1/GET_getByRiotId"""
    response = requests.get(
        f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{summoner_name}/{tagline}?api_key={key}",
        timeout=TIMEOUT,
    )
    return response


@handle_errors()
def get_match_list(puuid):
    """Uses https://developer.riotgames.com/apis#match-v5/GET_getMatchIdsByPUUID"""
    response = requests.get(
        f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count=20&api_key={key}",
        timeout=TIMEOUT,
    )
    return response


@handle_errors()
def get_match(matchID):
    """Uses https://developer.riotgames.com/apis#match-v5/GET_getMatch"""
    response = requests.get(
        f"https://americas.api.riotgames.com/lol/match/v5/matches/{matchID}?api_key={key}",
        timeout=TIMEOUT,
    )
    return response


@handle_errors()
def get_active_match(puuid):
    """Uses https://developer.riotgames.com/apis#spectator-v5/GET_getCurrentGameInfoByPuuid"""
    response = requests.get(
        f"https://na1.api.riotgames.com/lol/spectator/v5/active-games/by-summoner/{puuid}?api_key={key}",
        timeout=TIMEOUT,
    )
    return response


def get_recent_match(puuid):
    match_id = get_match_list(puuid)[0]
    return get_match(match_id)


def add_summoner(summoner_name, tagline):
    with open("squad.json", "r+") as file:
        squad = json.load(file)
        if summoner_name not in squad:
            squad[summoner_name] = get_puuid(summoner_name, tagline)
            file.seek(0)
            json.dump(squad, file, indent=4)
