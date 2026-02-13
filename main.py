import logging

from aiogram import Bot, Dispatcher, types
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram_dialog import DialogManager, StartMode, setup_dialogs

from amo_api.amo_api import AmoCRMWrapper
from dialogs.admin_dialog import admin_getter, admin_dialog
from dialogs.error_dialog import errors_router
from dialogs.hp_fifth_lesson_dialog import hp_fifth_lesson_dialog
from dialogs.hp_fourth_lesson_dialog import hp_fourth_lesson_dialog
from dialogs.hp_seventh_lesson_dialog import hp_seventh_lesson_dialog
from dialogs.hp_sixth_lesson_dialog import hp_sixth_lesson_dialog
from dialogs.hp_exam_dialog import hp_exam_lesson_dialog
from dialogs.main_dialog import main_menu_dialog
from dialogs.hp_first_lesson_dialog import hp_first_lesson_dialog
from dialogs.hp_second_lesson_dialog import hp_second_lesson_dialog
from dialogs.hp_third_lesson_dialog import hp_third_lesson_dialog
from handlers.start_handler import main_menu_router
from config.config import load_config
from aiogram.enums.parse_mode import ParseMode
from aiogram.client.default import DefaultBotProperties
from db import init_db, shutdown_db
from middlewares.db import DbSessionMiddleware
from middlewares.amo_api import AmoApiMiddleware

logger = logging.getLogger(__name__)

logging.basicConfig(
        level=logging.INFO,
        format='%(filename)s:%(lineno)d #%(levelname)-8s '
               '[%(asctime)s] - %(name)s - %(message)s')
logger.info("Starting hitepro_edu_bot")

config = load_config()
storage = MemoryStorage()

api = TelegramAPIServer.from_base(
        "http://127.0.0.1:8081",
        is_local=True,  # поставьте True, если ваш telegram-bot-api запущен с --local
    )
session = AiohttpSession(api=api)

bot = Bot(token=config.tg_bot.token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


# bot = Bot(token=config.tg_bot.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=storage)
amo_api = AmoCRMWrapper(
    path=config.amo_config.path_to_env,
    amocrm_subdomain=config.amo_config.amocrm_subdomain,
    amocrm_client_id=config.amo_config.amocrm_client_id,
    amocrm_redirect_url=config.amo_config.amocrm_redirect_url,
    amocrm_client_secret=config.amo_config.amocrm_client_secret,
    amocrm_secret_code=config.amo_config.amocrm_secret_code,
    amocrm_access_token=config.amo_config.amocrm_access_token,
    amocrm_refresh_token=config.amo_config.amocrm_refresh_token,
)
dp.update.middleware(DbSessionMiddleware())
dp.update.middleware(AmoApiMiddleware(amo_api, amo_fields=config.amo_fields, admin_id=config.admin))
dp.errors.middleware(DbSessionMiddleware())
dp.errors.middleware(AmoApiMiddleware(amo_api, amo_fields=config.amo_fields, admin_id=config.admin))

dp.include_router(main_menu_router)
dp.include_routers(main_menu_dialog, hp_first_lesson_dialog, hp_second_lesson_dialog,
                   hp_third_lesson_dialog, hp_fourth_lesson_dialog, hp_fifth_lesson_dialog, hp_sixth_lesson_dialog,
                   hp_seventh_lesson_dialog, hp_exam_lesson_dialog, admin_dialog, errors_router)

setup_dialogs(dp)


async def on_startup(bot: Bot, **_: object) -> None:
    try:
        await init_db()
    except Exception as exc:
        # Don't crash bot startup if DB is temporarily unavailable.
        print(f"DB init failed: {exc}")


async def on_shutdown(bot: Bot, **_: object) -> None:
    await shutdown_db()


dp.startup.register(on_startup)
dp.shutdown.register(on_shutdown)



if __name__ == '__main__':
    dp.run_polling(bot)
