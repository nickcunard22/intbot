import json

import pytest

from intbot import player as player_module
from intbot.player import Player, load_squad, save_squad, update_players_list


@pytest.fixture
def squad_file(tmp_path, monkeypatch):
    path = tmp_path / "squad.json"
    monkeypatch.setattr(player_module, "SQUAD_PATH", path)
    return path


def entry(name):
    return {
        "puuid": f"puuid-{name}",
        "summoner_name": name,
        "tagline": "NA1",
        "discord_id": 1,
        "discord_username": name,
    }


def test_save_then_load_round_trips(squad_file):
    squad = {"faker": entry("faker")}
    save_squad(squad)

    assert load_squad() == squad


def test_saving_shorter_data_does_not_leave_trailing_json(squad_file):
    """
    The old writer opened the file r+ and dumped over the top, so a shorter
    payload left the tail of the previous one behind and corrupted the file.
    """
    save_squad({name: entry(name) for name in ("faker", "caps", "bjergsen")})
    save_squad({"faker": entry("faker")})

    assert json.loads(squad_file.read_text()) == {"faker": entry("faker")}


async def test_update_players_list_builds_players(squad_file):
    save_squad({"faker": entry("faker"), "caps": entry("caps")})

    players = await update_players_list([])

    assert sorted(p.summoner_name for p in players) == ["caps", "faker"]


async def test_update_players_list_does_not_duplicate(squad_file):
    save_squad({"faker": entry("faker")})

    players = await update_players_list([])
    players = await update_players_list(players)

    assert len(players) == 1


async def test_update_players_list_picks_up_new_entries(squad_file):
    save_squad({"faker": entry("faker")})
    players = await update_players_list([])

    save_squad({"faker": entry("faker"), "caps": entry("caps")})
    players = await update_players_list(players)

    assert sorted(p.summoner_name for p in players) == ["caps", "faker"]


def test_players_compare_by_puuid():
    assert Player(**{**entry("faker"), "summoner_name": "faker"}) == Player(
        **{**entry("faker"), "summoner_name": "renamed"}
    )
