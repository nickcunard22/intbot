import asyncio
import functools
import logging

import httpx

from .config import RIOT_KEY

logger = logging.getLogger(__name__)

TIMEOUT = 5

# retries are bounded, an endpoint that stays broken should surface as an error
# rather than spin forever
MAX_ATTEMPTS = 4
BACKOFF_BASE = 1
MAX_WAIT = 60


class ResponseError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message

    def __int__(self):
        return self.code

    def __str__(self):
        return self.message


_client = None


def client():
    """
    Shared connection pool. The key goes in a header rather than the query
    string so it stays out of logs, which record the full url.
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=TIMEOUT,
            headers={"X-Riot-Token": RIOT_KEY},
        )
    return _client


async def close():
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _error_message(response):
    """Riot puts the useful text in status.message, but not for every failure."""
    try:
        return response.json()["status"]["message"]
    except (ValueError, KeyError, TypeError):
        return response.text[:200] or response.reason_phrase


def _retry_after(response, attempt):
    """Riot tells us how long to wait on a 429, so prefer that over guessing."""
    header = response.headers.get("Retry-After")
    if header is not None:
        try:
            return min(int(header), MAX_WAIT)
        except ValueError:
            pass
    return _backoff(attempt)


def _backoff(attempt):
    return min(BACKOFF_BASE * 2**attempt, MAX_WAIT)


def handle_errors(specific_key=None, none_on_404=False):
    """
    Decorator for request functions.
    The default return is the decoded json.
    If specific_key is set, the decorator will return the value at that key instead.
    If none_on_404 is set, a 404 returns None instead of raising, for endpoints
    where "not found" is a normal answer rather than a failure.
    """

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None

            for attempt in range(MAX_ATTEMPTS):
                try:
                    response = await func(*args, **kwargs)
                except httpx.TransportError as e:
                    # timeouts, connection resets, dns failures
                    last_error = ResponseError(0, f"{type(e).__name__}: {e}")
                    logger.warning(
                        "%s: %s (attempt %d/%d)",
                        func.__name__, last_error, attempt + 1, MAX_ATTEMPTS,
                    )
                    await asyncio.sleep(_backoff(attempt))
                    continue

                if response.status_code == 200:
                    payload = response.json()
                    return payload if specific_key is None else payload[specific_key]

                if response.status_code == 404 and none_on_404:
                    return None

                last_error = ResponseError(
                    response.status_code, _error_message(response)
                )

                if response.status_code == 429:
                    wait = _retry_after(response, attempt)
                    logger.warning(
                        "%s: rate limited (%s), waiting %ss",
                        func.__name__,
                        response.headers.get("X-Rate-Limit-Type", "unknown"),
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue

                if response.status_code >= 500:
                    logger.warning(
                        "%s: %s (attempt %d/%d)",
                        func.__name__, last_error, attempt + 1, MAX_ATTEMPTS,
                    )
                    await asyncio.sleep(_backoff(attempt))
                    continue

                # 4xx that isn't worth retrying, bad key, malformed name, etc
                raise last_error

            raise last_error

        return wrapper

    return decorator


@handle_errors(specific_key="puuid")
async def get_puuid(summoner_name, tagline):
    """Uses https://developer.riotgames.com/apis#account-v1/GET_getByRiotId"""
    return await client().get(
        f"https://americas.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{summoner_name}/{tagline}"
    )


@handle_errors()
async def get_match_list(puuid):
    """Uses https://developer.riotgames.com/apis#match-v5/GET_getMatchIdsByPUUID"""
    return await client().get(
        f"https://americas.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids",
        params={"start": 0, "count": 20},
    )


@handle_errors()
async def get_match(matchID):
    """Uses https://developer.riotgames.com/apis#match-v5/GET_getMatch"""
    return await client().get(
        f"https://americas.api.riotgames.com/lol/match/v5/matches/{matchID}"
    )


@handle_errors(none_on_404=True)
async def get_active_match(puuid):
    """
    Uses https://developer.riotgames.com/apis#spectator-v5/GET_getCurrentGameInfoByPuuid
    Returns None when the player isn't currently in a game.
    """
    return await client().get(
        f"https://na1.api.riotgames.com/lol/spectator/v5/active-games/by-summoner/{puuid}"
    )


async def get_recent_match(puuid):
    match_id = (await get_match_list(puuid))[0]
    return await get_match(match_id)
