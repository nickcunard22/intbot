import asyncio

from intbot.bot import bot

async def test_bot_binds_to_the_running_loop():
    """
    commands.Bot() captures a loop when it's constructed, which happens at
    import. Entering the context manager rebinds it to the loop that's actually
    running. Without that the heartbeat thread posts to a loop nobody drives,
    and the gateway connection silently dies.
    """
    running = asyncio.get_running_loop()

    async with bot:
        assert bot.loop is running
        assert bot.http.loop is running
        assert bot._connection.loop is running
