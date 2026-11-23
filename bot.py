"""GOD X FILES bot — entry point: polling + aiohttp health server."""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import web

import admin
import config
import core
import db
import handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("bot")

dp = Dispatcher()


async def make_health_app(bot: Bot) -> web.Application:
    async def health(_req: web.Request) -> web.Response:
        try:
            me = await bot.get_me()
            info = {"ok": True, "bot": f"@{me.username}", "mode": "polling"}
        except Exception:
            info = {"ok": True, "bot": None, "note": "telegram unreachable"}
        return web.json_response(info)
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", health)  # any path (incl /bot/health via proxy prefix)
    return app


async def start_health(bot: Bot) -> None:
    app = await make_health_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    log.info("health server on :%s", config.PORT)


async def main() -> None:
    problems = config.validate()
    if problems:
        for p in problems:
            log.error("CONFIG ERROR: %s", p)
        sys.exit(1)

    db.init()
    config.log_summary()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    me = await core.resolve_username(bot)
    log.info("bot identity: @%s (id=%s)", me, bot.id)

    dp.include_routers(admin.router, handlers.router)

    await start_health(bot)
    log.info("polling started — @%s live 🚀", me)
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("stopped")
