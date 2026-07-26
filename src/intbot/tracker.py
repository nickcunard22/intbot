import asyncio
import logging
from collections import defaultdict

from .performance import extract_performance, performance_message
from .player import update_players_list
from .riot_api_requests import ResponseError, get_active_match, get_match

logger = logging.getLogger(__name__)

# how often to ask the spectator endpoint about every tracked player
POLL_INTERVAL = 60

# match-v5 lags a minute or two behind the end of a game, so the result isn't
# there the moment spectator drops the player
MATCH_ATTEMPTS = 10
MATCH_RETRY_DELAY = 15

PLATFORM = "NA1"

# riot answers 404 for a match it has no record of at all, and 403 for one it
# knows about but won't serve yet. neither is a final answer on the first ask,
# so both are worth waiting out.
PENDING_STATUSES = (403, 404)


class GameTracker:
    """
    Watches every tracked player's spectator status and reports finished games.

    Riot has no push notification for this, so polling is unavoidable, but it
    only needs one endpoint. Each sweep asks spectator-v5 about every player;
    a player going from in-a-game to not-in-a-game is the trigger. That means
    the expensive match lookup happens once per game rather than once per poll,
    and players queued together share a single lookup between them.
    """

    def __init__(self, announce, poll_interval=POLL_INTERVAL, sleep=asyncio.sleep):
        self._announce = announce
        self._poll_interval = poll_interval
        self._sleep = sleep
        self._players = []
        self._active = {}  # puuid -> game_id they're currently in
        self._tasks = set()

    async def run(self):
        while True:
            try:
                await self.sweep()
            except Exception:
                # a bad sweep shouldn't take the tracker down with it
                logger.exception("sweep failed")
            await self._sleep(self._poll_interval)

    async def sweep(self):
        """One pass over every tracked player. Returns the games that just ended."""
        self._players = await update_players_list(self._players)
        finished = defaultdict(list)

        for player in self._players:
            try:
                active = await get_active_match(player.puuid)
            except ResponseError as e:
                # we don't know their state, so leave it alone rather than
                # guess and fire a bogus "game over" message
                logger.info(
                    "%s: spectator lookup failed, %d %s",
                    player.summoner_name, int(e), e,
                )
                continue

            current = active["gameId"] if active is not None else None
            previous = self._active.get(player.puuid)

            # every sweep, so a player blinking out of spectator and back is
            # visible rather than showing up as a phantom finished game
            logger.debug(
                "%s: spectator says %s, tracked as %s",
                player.summoner_name, current, previous,
            )

            if current == previous:
                continue

            # handled before the start below, so a player who queues straight
            # into another game between sweeps still gets the first one reported
            if previous is not None:
                del self._active[player.puuid]
                finished[previous].append(player)
                logger.info("%s finished game %s", player.summoner_name, previous)

            if current is not None:
                self._active[player.puuid] = current
                logger.info("%s started game %s", player.summoner_name, current)

        for game_id, players in finished.items():
            self._spawn(self.report(game_id, players))

        return finished

    async def report(self, game_id, players):
        match = await self._fetch_finished_match(game_id)
        if match is None:
            logger.warning("no match data for %s, nothing to report", game_id)
            return

        for player in players:
            performance = extract_performance(player, match)
            if performance is None:
                logger.info(
                    "%s: no stats in match %s", player.summoner_name, game_id
                )
                continue

            # logged for every finished game, not just the ones worth posting
            logger.info("game %s | %s", game_id, performance.summary())

            message = performance_message(performance)
            if message is None:
                logger.info("%s: nothing notable to post", player.summoner_name)
                continue

            await self._announce(message)

    async def _fetch_finished_match(self, game_id):
        """Polls for the match record, which shows up shortly after the game ends."""
        for attempt in range(MATCH_ATTEMPTS):
            try:
                return await get_match(f"{PLATFORM}_{game_id}")
            except ResponseError as e:
                if int(e) not in PENDING_STATUSES:
                    logger.warning("match %s: %d %s", game_id, int(e), e)
                    return None
                logger.debug(
                    "match %s not available yet, %d (attempt %d/%d)",
                    game_id, int(e), attempt + 1, MATCH_ATTEMPTS,
                )
            await self._sleep(MATCH_RETRY_DELAY)
        return None

    def _spawn(self, coro):
        # keep a strong reference, a task referenced only by the event loop can
        # be garbage collected mid-flight
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task):
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("report task failed", exc_info=task.exception())

    async def wait_for_reports(self):
        """Waits out any in-flight reports. Used on shutdown and in tests."""
        while self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
