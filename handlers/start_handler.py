import asyncio

import aiohttp
from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from aiogram_dialog import DialogManager, StartMode

from fsm_forms.fsm_models import MainDialog

main_menu_router = Router()

@main_menu_router.message(Command("start"))
async def start(message: Message, dialog_manager: DialogManager, command: CommandObject):
    webhook_url = dialog_manager.middleware_data['webhook_url']
    utm_token = dialog_manager.middleware_data['utm_token']
    webhook_id = command.args.strip() if command and command.args else ""

    utm_data = {
        "utm_source": "",
        "utm_medium": "",
        "utm_campaign": "",
        "utm_content": "",
        "utm_term": "",
        "yclid": "",
    }

    if webhook_id:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{webhook_url}{webhook_id}",
                    params={"utm_token": utm_token},
                    timeout=10,
                ) as response:
                    response.raise_for_status()
                    payload = await response.json()
                    if isinstance(payload, dict):
                        utm_data.update(payload)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            pass

    # Important: always set `mode=StartMode.RESET_STACK` you don't want to stack dialogs
    await dialog_manager.start(MainDialog.main, mode=StartMode.RESET_STACK, data={"utm_data": utm_data})




# @main_menu_router.message(Command("start"))
# async def start(message: Message, dialog_manager: DialogManager):
#     webhook_url = dialog_manager.middleware_data['webhook_url']
#     utm_token = dialog_manager.middleware_data['utm_token']
#
#     # Important: always set `mode=StartMode.RESET_STACK` you don't want to stack dialogs
#     await dialog_manager.start(MainDialog.main, mode=StartMode.RESET_STACK)
