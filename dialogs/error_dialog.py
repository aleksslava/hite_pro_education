from aiogram import Router
from aiogram.filters.exception import ExceptionTypeFilter
from aiogram.types import ErrorEvent, ReplyKeyboardRemove

from aiogram_dialog import DialogManager, StartMode, ShowMode
from aiogram_dialog.api.exceptions import OutdatedIntent, UnknownIntent, UnknownState
from fsm_forms.fsm_models import MainDialog

errors_router = Router()


@errors_router.error(ExceptionTypeFilter(OutdatedIntent, UnknownIntent, UnknownState))
async def on_dialog_stale(event: ErrorEvent, dialog_manager: DialogManager):
    callback = event.update.callback_query
    if callback:
        await callback.answer("Меню устарело — открываю главное меню бота ✅", show_alert=True,
                              reply_markup=ReplyKeyboardRemove())
        try:
            if callback.message:

                # await callback.message.edit_reply_markup(reply_markup=None)
                await callback.message.delete()
        except Exception:
            pass

    await dialog_manager.start(MainDialog.main, mode=StartMode.RESET_STACK, show_mode=ShowMode.SEND)
    return True
