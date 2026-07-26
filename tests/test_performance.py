import pytest

from intbot.performance import extract_performance, performance_message
from intbot.player import Player


def make_player(puuid="puuid-faker"):
    return Player(
        summoner_name="faker",
        puuid=puuid,
        tagline="NA1",
        discord_id=42,
        discord_username="faker",
    )


def make_match(puuid="puuid-faker", **overrides):
    participant = {
        "puuid": puuid,
        "kills": 5,
        "deaths": 5,
        "assists": 5,
        "championName": "Azir",
        "win": True,
        "neutralMinionsKilled": 20,
        "totalMinionsKilled": 180,
        "challenges": {"killParticipation": 0.5, "gameLength": 1800},
    }
    challenges = overrides.pop("challenges", {})
    participant.update(overrides)
    participant["challenges"].update(challenges)
    return {"info": {"participants": [{"puuid": "someone-else"}, participant]}}


# --- extraction --------------------------------------------------------------


def test_extracts_the_right_participant():
    performance = extract_performance(make_player(), make_match())

    assert performance.champion_name == "Azir"
    assert performance.kda == "5/5/5"
    assert performance.cs == 200


def test_returns_none_when_player_is_not_in_the_match():
    assert extract_performance(make_player("nobody"), make_match()) is None


def test_returns_none_on_incomplete_data():
    match = make_match()
    del match["info"]["participants"][1]["championName"]

    assert extract_performance(make_player(), match) is None


def test_cs_per_minute():
    # 200 cs over a 30 minute game
    performance = extract_performance(make_player(), make_match())

    assert performance.cspm == pytest.approx(6.67, abs=0.01)


def test_a_deathless_game_does_not_divide_by_zero():
    """(kills + assists) / deaths used to blow up on a perfect game."""
    performance = extract_performance(make_player(), make_match(deaths=0))

    assert performance.adjusted_kda > 0


def test_assists_are_devalued_in_longer_games():
    short = extract_performance(
        make_player(), make_match(kills=0, deaths=1, challenges={"gameLength": 600})
    )
    long = extract_performance(
        make_player(), make_match(kills=0, deaths=1, challenges={"gameLength": 2400})
    )

    assert long.adjusted_kda < short.adjusted_kda


def test_summary_includes_the_kda_and_champion():
    summary = extract_performance(make_player(), make_match()).summary()

    assert "faker" in summary
    assert "5/5/5" in summary
    assert "Azir" in summary


# --- messages ----------------------------------------------------------------


def test_high_cs_gets_the_chovy_message():
    # 700 cs over 30 minutes clears 10 cs/min
    performance = extract_performance(
        make_player(), make_match(totalMinionsKilled=680)
    )

    assert "might be chovy" in performance_message(performance)


def test_zero_kill_participation_gets_called_out():
    performance = extract_performance(
        make_player(), make_match(kills=0, assists=0, deaths=7)
    )

    assert "has cancer" in performance_message(performance)


def test_good_kda_gets_a_good_message():
    performance = extract_performance(
        make_player(), make_match(kills=15, deaths=1, assists=5)
    )

    assert performance_message(performance) is not None


def test_an_unremarkable_game_says_nothing():
    performance = extract_performance(
        make_player(), make_match(kills=5, deaths=3, assists=3)
    )

    assert performance_message(performance) is None


def test_message_mentions_the_player_and_the_result():
    performance = extract_performance(
        make_player(), make_match(kills=0, assists=0, deaths=7, win=False)
    )
    message = performance_message(performance)

    assert "<@42>" in message
    assert "**Defeat**" in message
    assert "0/7/0" in message
    assert "30m 0s" in message
