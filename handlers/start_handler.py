from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram_dialog import DialogManager, StartMode
from fsm_forms.fsm_models import MainDialog

main_menu_router = Router()

@main_menu_router.message(Command("start"))
async def start(message: Message, dialog_manager: DialogManager):
    # Important: always set `mode=StartMode.RESET_STACK` you don't want to stack dialogs
    await dialog_manager.start(MainDialog.main, mode=StartMode.RESET_STACK)