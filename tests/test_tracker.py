from types import SimpleNamespace

import pytest

from intbot import tracker as tracker_module
from intbot.player import Player
from intbot.riot_api_requests import ResponseError
from intbot.tracker import GameTracker


def make_player(name, puuid=None):
    return Player(
        summoner_name=name,
        puuid=puuid or f"puuid-{name}",
        tagline="NA1",
        discord_id=1,
        discord_username=name,
    )


@pytest.fixture
def world(monkeypatch):
    """
    Replaces everything the tracker reaches out to: the two riot endpoints,
    the squad file, and sleeping.
    """

    class World:
        def __init__(self):
            self.players = []
            self.in_game = {}  # puuid -> game_id, what spectator reports
            self.spectator_error = {}  # puuid -> ResponseError to raise
            self.matches = {}  # "NA1_<id>" -> match payload
            self.match_errors = {}  # "NA1_<id>" -> list of errors to raise first
            self.announced = []
            self.performance = {}  # puuid -> message, or None
            self.no_stats = set()  # puuids absent from the match payload
            self.get_match_calls = []
            self.slept = []

        async def get_active_match(self, puuid):
            if puuid in self.spectator_error:
                raise self.spectator_error[puuid]
            game_id = self.in_game.get(puuid)
            return None if game_id is None else {"gameId": game_id}

        async def get_match(self, match_id):
            self.get_match_calls.append(match_id)
            pending = self.match_errors.get(match_id)
            if pending:
                raise pending.pop(0)
            if match_id not in self.matches:
                raise ResponseError(404, "not found")
            return self.matches[match_id]

        async def update_players_list(self, players):
            for player in self.players:
                if player not in players:
                    players.append(player)
            return players

        def extract_performance(self, player, match):
            if player.puuid in self.no_stats:
                return None
            return SimpleNamespace(
                puuid=player.puuid,
                summoner_name=player.summoner_name,
                summary=lambda: f"{player.summoner_name} 0/5/0",
            )

        def performance_message(self, performance):
            return self.performance.get(
                performance.puuid, f"{performance.summoner_name} inted"
            )

        async def announce(self, message):
            self.announced.append(message)

        async def sleep(self, seconds):
            self.slept.append(seconds)

    world = World()
    monkeypatch.setattr(tracker_module, "get_active_match", world.get_active_match)
    monkeypatch.setattr(tracker_module, "get_match", world.get_match)
    monkeypatch.setattr(tracker_module, "update_players_list", world.update_players_list)
    monkeypatch.setattr(tracker_module, "extract_performance", world.extract_performance)
    monkeypatch.setattr(tracker_module, "performance_message", world.performance_message)
    return world


@pytest.fixture
def tracker(world):
    return GameTracker(announce=world.announce, sleep=world.sleep)


async def run_sweep(tracker, world):
    await tracker.sweep()
    await tracker.wait_for_reports()


# --- state transitions -------------------------------------------------------


async def test_starting_a_game_announces_nothing(tracker, world):
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100

    await run_sweep(tracker, world)

    assert world.announced == []
    assert world.get_match_calls == []


async def test_finishing_a_game_announces(tracker, world):
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100
    world.matches["NA1_100"] = {"info": {}}

    await run_sweep(tracker, world)  # in game
    del world.in_game[faker.puuid]
    await run_sweep(tracker, world)  # out of game

    assert world.announced == ["faker inted"]


async def test_staying_in_game_does_not_hit_match_endpoint(tracker, world):
    """The old small loop polled match-v5 every 12s for the whole game."""
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100

    for _ in range(5):
        await run_sweep(tracker, world)

    assert world.get_match_calls == []


async def test_finished_game_is_reported_once(tracker, world):
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100
    world.matches["NA1_100"] = {"info": {}}

    await run_sweep(tracker, world)
    del world.in_game[faker.puuid]
    await run_sweep(tracker, world)
    await run_sweep(tracker, world)  # still out of game

    assert world.announced == ["faker inted"]
    assert world.get_match_calls == ["NA1_100"]


async def test_players_in_the_same_game_share_one_match_lookup(tracker, world):
    """A squad queueing together used to spawn one polling task per player."""
    squad = [make_player(name) for name in ("faker", "caps", "bjergsen")]
    world.players = squad
    for player in squad:
        world.in_game[player.puuid] = 100
    world.matches["NA1_100"] = {"info": {}}

    await run_sweep(tracker, world)
    world.in_game.clear()
    await run_sweep(tracker, world)

    assert world.get_match_calls == ["NA1_100"]  # one lookup, not three
    assert sorted(world.announced) == ["bjergsen inted", "caps inted", "faker inted"]


async def test_back_to_back_games_still_report_the_first(tracker, world):
    """Queueing straight into game two between sweeps must not swallow game one."""
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100
    world.matches["NA1_100"] = {"info": {}}

    await run_sweep(tracker, world)
    world.in_game[faker.puuid] = 200  # never observed as out of game
    await run_sweep(tracker, world)

    assert world.get_match_calls == ["NA1_100"]
    assert world.announced == ["faker inted"]


async def test_players_in_separate_games_are_reported_separately(tracker, world):
    faker, caps = make_player("faker"), make_player("caps")
    world.players = [faker, caps]
    world.in_game = {faker.puuid: 100, caps.puuid: 200}
    world.matches["NA1_100"] = {"info": {}}
    world.matches["NA1_200"] = {"info": {}}

    await run_sweep(tracker, world)
    world.in_game.clear()
    await run_sweep(tracker, world)

    assert sorted(world.get_match_calls) == ["NA1_100", "NA1_200"]
    assert sorted(world.announced) == ["caps inted", "faker inted"]


# --- failure handling --------------------------------------------------------


async def test_spectator_error_leaves_state_alone(tracker, world):
    """An api hiccup must not read as 'game over' and fire a bogus message."""
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100
    world.matches["NA1_100"] = {"info": {}}

    await run_sweep(tracker, world)  # in game
    world.spectator_error[faker.puuid] = ResponseError(500, "server error")
    await run_sweep(tracker, world)

    assert world.announced == []

    # and once it recovers, the real end of the game still reports
    del world.spectator_error[faker.puuid]
    del world.in_game[faker.puuid]
    await run_sweep(tracker, world)

    assert world.announced == ["faker inted"]


async def test_match_404_is_retried_until_it_posts(tracker, world):
    """match-v5 lags behind the end of the game."""
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100
    world.match_errors["NA1_100"] = [ResponseError(404, "not found")] * 3
    world.matches["NA1_100"] = {"info": {}}

    await run_sweep(tracker, world)
    del world.in_game[faker.puuid]
    await run_sweep(tracker, world)

    assert len(world.get_match_calls) == 4
    assert world.announced == ["faker inted"]


async def test_match_that_never_posts_gives_up_quietly(tracker, world):
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100
    # no entry in world.matches, so it 404s forever

    await run_sweep(tracker, world)
    del world.in_game[faker.puuid]
    await run_sweep(tracker, world)

    assert len(world.get_match_calls) == tracker_module.MATCH_ATTEMPTS
    assert world.announced == []


async def test_match_403_is_retried(tracker, world):
    """
    Riot uses 404 for a match it has no record of, so a 403 means it knows
    about the match and isn't serving it yet. Worth waiting out.
    """
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100
    world.match_errors["NA1_100"] = [ResponseError(403, "Forbidden")] * 2
    world.matches["NA1_100"] = {"info": {}}

    await run_sweep(tracker, world)
    del world.in_game[faker.puuid]
    await run_sweep(tracker, world)

    assert len(world.get_match_calls) == 3
    assert world.announced == ["faker inted"]


async def test_permanent_403_gives_up_after_the_bound(tracker, world):
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100
    world.match_errors["NA1_100"] = [ResponseError(403, "Forbidden")] * 50

    await run_sweep(tracker, world)
    del world.in_game[faker.puuid]
    await run_sweep(tracker, world)

    assert len(world.get_match_calls) == tracker_module.MATCH_ATTEMPTS
    assert world.announced == []


async def test_unexpected_match_error_is_not_retried(tracker, world):
    """A 500 or a bad key won't resolve itself by asking again."""
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100
    world.match_errors["NA1_100"] = [ResponseError(500, "server error")]

    await run_sweep(tracker, world)
    del world.in_game[faker.puuid]
    await run_sweep(tracker, world)

    assert len(world.get_match_calls) == 1
    assert world.announced == []


async def test_stats_are_logged_even_when_nothing_is_posted(tracker, world, caplog):
    """The stat line should land in the logs for every finished game."""
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100
    world.matches["NA1_100"] = {"info": {}}
    world.performance[faker.puuid] = None  # nothing worth posting

    with caplog.at_level("INFO", logger="intbot.tracker"):
        await run_sweep(tracker, world)
        del world.in_game[faker.puuid]
        await run_sweep(tracker, world)

    assert world.announced == []
    assert "faker 0/5/0" in caplog.text


async def test_debug_logs_every_spectator_result(tracker, world, caplog):
    """The diagnostic for a player blinking out of spectator mid game."""
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100

    with caplog.at_level("DEBUG", logger="intbot.tracker"):
        await run_sweep(tracker, world)  # not tracked yet -> in game 100
        await run_sweep(tracker, world)  # steady state, no transition logged

    assert "faker: spectator says 100, tracked as None" in caplog.text
    assert "faker: spectator says 100, tracked as 100" in caplog.text


async def test_game_start_and_end_are_logged(tracker, world, caplog):
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100
    world.matches["NA1_100"] = {"info": {}}

    with caplog.at_level("INFO", logger="intbot.tracker"):
        await run_sweep(tracker, world)
        assert "faker started game 100" in caplog.text

        del world.in_game[faker.puuid]
        await run_sweep(tracker, world)
        assert "faker finished game 100" in caplog.text


async def test_no_notable_performance_announces_nothing(tracker, world):
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100
    world.matches["NA1_100"] = {"info": {}}
    world.performance[faker.puuid] = None

    await run_sweep(tracker, world)
    del world.in_game[faker.puuid]
    await run_sweep(tracker, world)

    assert world.announced == []


async def test_one_player_failing_does_not_block_the_others(tracker, world):
    faker, caps = make_player("faker"), make_player("caps")
    world.players = [faker, caps]
    world.in_game = {faker.puuid: 100, caps.puuid: 200}
    world.matches["NA1_200"] = {"info": {}}
    world.match_errors["NA1_100"] = [ResponseError(500, "server error")]

    await run_sweep(tracker, world)
    world.in_game.clear()
    await run_sweep(tracker, world)

    assert world.announced == ["caps inted"]


class StopTheLoop(BaseException):
    """Not an Exception, so run()'s catch-all can't swallow it."""


async def test_sweep_failure_does_not_kill_the_run_loop(tracker, world, monkeypatch):
    calls = {"n": 0}

    async def exploding_sweep():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        raise StopTheLoop

    monkeypatch.setattr(tracker, "sweep", exploding_sweep)

    with pytest.raises(StopTheLoop):
        await tracker.run()

    assert calls["n"] == 2  # it kept going after the first failure


# --- task management ---------------------------------------------------------


async def test_report_tasks_are_strongly_referenced(tracker, world):
    faker = make_player("faker")
    world.players = [faker]
    world.in_game[faker.puuid] = 100
    world.matches["NA1_100"] = {"info": {}}

    await tracker.sweep()
    del world.in_game[faker.puuid]
    await tracker.sweep()

    assert tracker._tasks, "report task must be referenced so it can't be collected"

    await tracker.wait_for_reports()
    assert not tracker._tasks  # and cleaned up when done
