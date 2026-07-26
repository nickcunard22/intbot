import asyncio
import logging
from logging.handlers import RotatingFileHandler

from .bot import bot, tracker
from .config import DISCORD_TOKEN, LOG_FILE, LOG_LEVEL

logger = logging.getLogger(__name__)


def exception_handler(loop, context):
    exception = context.get("exception")
    message = context.get("message")
    logger.error(f"Error: {exception}\nMessage: {message}")


async def run():
    # commands.Bot() grabs an event loop when it's constructed, which happens at
    # import time, long before this one exists. `async with bot` rebinds the
    # client to the running loop. Skip it and the heartbeat thread posts to the
    # loop captured at import, which never runs, so the gateway connection dies
    # while this loop sits idle.
    async with bot:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(exception_handler)

        sweep = loop.create_task(tracker.run())
        try:
            await bot.start(DISCORD_TOKEN)
        finally:
            sweep.cancel()


def main():
    handlers = [logging.StreamHandler()]
    if LOG_FILE:
        # debug level runs a few thousand lines a day, so keep it bounded
        handlers.append(
            RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3)
        )

    logging.basicConfig(
        level=LOG_LEVEL,
        format="[%(asctime)s] [%(levelname)s] %(name)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )

    # pinned regardless of LOG_LEVEL, these bury our own logging at debug.
    # httpcore is the transport under httpx and logs ~6 lines per request.
    for noisy in ("httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("discord").setLevel(logging.INFO)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Shutting down")


if __name__ == "__main__":
    main()
