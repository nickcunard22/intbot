import httpx
import pytest

from intbot import riot_api_requests as riot

from conftest import response


# --- routing -----------------------------------------------------------------
# the endpoints are easy to typo and a wrong host fails as a confusing 404,
# so pin the url each function builds


async def test_get_puuid_routing(api):
    api.returns(response(200, {"puuid": "abc"}))
    await riot.get_puuid("Faker", "NA1")

    assert api.last.url.host == "americas.api.riotgames.com"
    assert api.last.url.path == "/riot/account/v1/accounts/by-riot-id/Faker/NA1"


async def test_get_match_routing(api):
    await riot.get_match("NA1_123")

    assert api.last.url.host == "americas.api.riotgames.com"
    assert api.last.url.path == "/lol/match/v5/matches/NA1_123"


async def test_get_active_match_routing(api):
    await riot.get_active_match("puuid-1")

    assert api.last.url.host == "na1.api.riotgames.com"
    assert api.last.url.path == "/lol/spectator/v5/active-games/by-summoner/puuid-1"


async def test_get_match_list_routing(api):
    api.returns(response(200, []))
    await riot.get_match_list("puuid-1")

    assert api.last.url.path == "/lol/match/v5/matches/by-puuid/puuid-1/ids"
    assert api.last.url.params["start"] == "0"
    assert api.last.url.params["count"] == "20"


async def test_api_key_is_sent_as_a_header(api):
    await riot.get_match("NA1_123")

    assert api.last.headers["X-Riot-Token"] == "TEST_KEY"


async def test_api_key_never_appears_in_the_url(api):
    """httpx logs the full url at INFO, so the key must not be in the query."""
    await riot.get_match("NA1_123")

    assert "TEST_KEY" not in str(api.last.url)
    assert "api_key" not in api.last.url.params


# --- response handling -------------------------------------------------------


async def test_specific_key_is_extracted(api):
    api.returns(response(200, {"puuid": "abc", "gameName": "Faker"}))

    assert await riot.get_puuid("Faker", "NA1") == "abc"


async def test_full_payload_returned_without_specific_key(api):
    api.returns(response(200, {"gameId": 42}))

    assert await riot.get_match("NA1_123") == {"gameId": 42}


async def test_active_match_404_returns_none(api):
    """Not being in a game is a normal answer, not an error."""
    api.returns(response(404))

    assert await riot.get_active_match("puuid-1") is None
    assert api.call_count == 1  # and it isn't retried


async def test_match_404_still_raises(api):
    """get_match has no none_on_404, so a missing match is an error."""
    api.returns(response(404))

    with pytest.raises(riot.ResponseError) as excinfo:
        await riot.get_match("NA1_123")
    assert int(excinfo.value) == 404


# --- retry behaviour ---------------------------------------------------------


async def test_500_retries_then_gives_up(api):
    api.returns(response(500))

    with pytest.raises(riot.ResponseError) as excinfo:
        await riot.get_match("NA1_123")

    assert int(excinfo.value) == 500
    assert api.call_count == riot.MAX_ATTEMPTS


async def test_500_recovers_if_the_retry_succeeds(api):
    api.returns(response(500), response(200, {"gameId": 42}))

    assert await riot.get_match("NA1_123") == {"gameId": 42}
    assert api.call_count == 2


async def test_429_is_retried(api):
    api.returns(
        response(429, headers={"Retry-After": "0"}),
        response(200, {"gameId": 42}),
    )

    assert await riot.get_match("NA1_123") == {"gameId": 42}
    assert api.call_count == 2


async def test_403_is_not_retried(api):
    """A bad api key won't fix itself, so don't burn attempts on it."""
    api.returns(response(403))

    with pytest.raises(riot.ResponseError):
        await riot.get_match("NA1_123")

    assert api.call_count == 1


async def test_transport_errors_are_retried(api):
    calls = {"n": 0}

    def flaky(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectTimeout("timed out", request=request)
        return response(200, {"gameId": 42})

    api.handle = flaky
    api._responses = []

    assert await riot.get_match("NA1_123") == {"gameId": 42}
    assert calls["n"] == 2


async def test_retries_are_bounded(api):
    """The old decorator recursed forever here."""

    def always_fails(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    api.handle = always_fails

    with pytest.raises(riot.ResponseError):
        await riot.get_match("NA1_123")


# --- wait calculation --------------------------------------------------------
# pure functions, so they're tested directly rather than through a request


def test_retry_after_header_is_honoured():
    resp = response(429, headers={"Retry-After": "7"})

    assert riot._retry_after(resp, attempt=0) == 7


def test_retry_after_falls_back_to_backoff_when_missing():
    resp = response(429)

    assert riot._retry_after(resp, attempt=2) == riot._backoff(2)


def test_retry_after_falls_back_when_unparseable():
    resp = response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})

    assert riot._retry_after(resp, attempt=1) == riot._backoff(1)


def test_wait_is_capped():
    resp = response(429, headers={"Retry-After": "99999"})

    assert riot._retry_after(resp, attempt=0) == riot.MAX_WAIT
    assert riot._backoff(attempt=50) == riot.MAX_WAIT


def test_backoff_grows():
    waits = [riot._backoff(n) for n in range(4)]

    assert waits == sorted(waits)
    assert waits[0] < waits[-1]


# --- error message extraction ------------------------------------------------


def test_error_message_reads_riot_envelope():
    resp = response(403, {"status": {"message": "Forbidden"}})

    assert riot._error_message(resp) == "Forbidden"


def test_error_message_falls_back_on_non_json_body():
    """Riot's gateway returns html on some 5xx, which used to blow up the handler."""
    resp = response(502, text="<html>Bad Gateway</html>")

    assert "Bad Gateway" in riot._error_message(resp)


def test_error_message_falls_back_on_unexpected_json_shape():
    resp = response(500, {"unexpected": True})

    assert riot._error_message(resp)  # non-empty, and doesn't raise
