import httpx
import pytest

from intbot import riot_api_requests


def response(status, body=None, headers=None, text=None):
    """Build a canned Riot response. Defaults to their error envelope shape."""
    if text is not None:
        return httpx.Response(status, text=text, headers=headers or {})
    if body is None:
        body = {"status": {"message": "canned error"}}
    return httpx.Response(status, json=body, headers=headers or {})


class FakeAPI:
    """
    Stands in for the Riot API. Queue up responses with returns(), then inspect
    what the request functions actually sent via .requests / .last.
    """

    def __init__(self):
        self.requests = []
        self._responses = [response(200, {})]

    def returns(self, *responses):
        self._responses = list(responses)

    def handle(self, request):
        self.requests.append(request)
        # the final queued response repeats, so retry tests don't have to
        # spell out every attempt
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]

    @property
    def last(self):
        return self.requests[-1]

    @property
    def call_count(self):
        return len(self.requests)


@pytest.fixture
async def api(monkeypatch):
    fake = FakeAPI()
    client = httpx.AsyncClient(
        # dispatch through the instance so tests can swap handle() out
        transport=httpx.MockTransport(lambda request: fake.handle(request)),
        headers={"X-Riot-Token": "TEST_KEY"},
    )
    monkeypatch.setattr(riot_api_requests, "_client", client)
    # collapse the backoff so retry tests run instantly
    monkeypatch.setattr(riot_api_requests, "BACKOFF_BASE", 0)
    monkeypatch.setattr(riot_api_requests, "MAX_WAIT", 0)

    yield fake

    await client.aclose()
