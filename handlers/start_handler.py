from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram_dialog import DialogManager, StartMode
from fsm_forms.fsm_models import MainDialog

main_menu_router = Router()

@main_menu_router.message(Command("start"))
async def start(message: Message, dialog_manager: DialogManager):
    await message.answer("Клавиатура очищена.", reply_markup=ReplyKeyboardRemove())
    # Important: always set `mode=StartMode.RESET_STACK` you don't want to stack dialogs
    await dialog_manager.start(MainDialog.main, mode=StartMode.RESET_STACK)
