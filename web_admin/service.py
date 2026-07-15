from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from db.models import Broadcast, BroadcastDelivery
from web_admin.repository import BroadcastRepository
from web_admin.max_client import MaxBroadcastClient, MaxDeliveryError, MaxServiceUnavailable
from web_admin.validation import adapt_telegram_html_for_max, render_message


logger = logging.getLogger(__name__)


class BroadcastService:
    def __init__(
        self,
        repository: BroadcastRepository,
        bot: Bot,
        data_dir: Path,
        max_client: MaxBroadcastClient | None = None,
    ):
        self.repository = repository
        self.bot = bot
        self.data_dir = data_dir
        self.media_dir = data_dir / "media"
        self.max_client = max_client
        self._worker_task: asyncio.Task | None = None
        self._wake_event = asyncio.Event()

    async def initialize(self) -> None:
        self.media_dir.mkdir(parents=True, exist_ok=True)
        await self.repository.recover_interrupted()

    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop(), name="broadcast-worker")

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        if self.max_client is not None:
            await self.max_client.close()

    def wake(self) -> None:
        self._wake_event.set()

    async def _worker_loop(self) -> None:
        while True:
            processed = await self.process_next_due()
            if processed:
                continue
            self._wake_event.clear()
            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    async def process_next_due(self) -> bool:
        broadcast = await self.repository.claim_next_due()
        if broadcast is None:
            return False
        try:
            deliveries = await self.repository.pending_deliveries(broadcast.id)
            telegram_deliveries = [item for item in deliveries if item.platform == "telegram"]
            max_deliveries = [item for item in deliveries if item.platform == "max"]
            await self._process_telegram(broadcast, telegram_deliveries)
            await self._process_max(broadcast, max_deliveries)
            await self.repository.finish(broadcast.id)
        except Exception as error:
            logger.exception("Broadcast %s failed", broadcast.id)
            await self.repository.fail(broadcast.id, str(error)[:500])
        finally:
            latest = await self.repository.get(broadcast.id)
            if latest is not None and latest.status not in {"scheduled", "running"}:
                try:
                    await self.repository.clear_max_media(latest.id)
                except Exception:
                    logger.exception("Could not clear cached MAX media for broadcast %s", latest.id)
                self.delete_media(latest.media_path)
        return True

    async def _process_telegram(
        self, broadcast: Broadcast, deliveries: list[BroadcastDelivery]
    ) -> None:
        for delivery in deliveries:
            if not await self.repository.mark_sending(delivery.id):
                continue
            try:
                await self._send_telegram(broadcast, delivery)
            except Exception as error:
                logger.exception(
                    "Broadcast %s failed for telegram_id=%s", broadcast.id, delivery.target_id
                )
                await self.repository.mark_result(delivery.id, success=False, error=str(error)[:500])
            else:
                await self.repository.mark_result(delivery.id, success=True)
            await asyncio.sleep(0.05)

    async def _process_max(
        self, broadcast: Broadcast, deliveries: list[BroadcastDelivery]
    ) -> None:
        if not deliveries:
            return
        if self.max_client is None:
            await self.repository.fail_pending_platform(
                broadcast.id, "max", "Интеграция MAX не настроена"
            )
            return
        try:
            await self._ensure_max_media(broadcast)
        except (MaxServiceUnavailable, MaxDeliveryError) as error:
            logger.warning("MAX media preparation failed for broadcast %s: %s", broadcast.id, error)
            await self.repository.fail_pending_platform(broadcast.id, "max", str(error)[:500])
            return

        for delivery in deliveries:
            if not await self.repository.mark_sending(delivery.id):
                continue
            try:
                await self._send_max(broadcast, delivery)
            except MaxServiceUnavailable as error:
                await self.repository.mark_result(delivery.id, success=False, error=str(error)[:500])
                await self.repository.fail_pending_platform(broadcast.id, "max", str(error)[:500])
                break
            except Exception as error:
                logger.exception("Broadcast %s failed for max_id=%s", broadcast.id, delivery.target_id)
                await self.repository.mark_result(delivery.id, success=False, error=str(error)[:500])
            else:
                await self.repository.mark_result(delivery.id, success=True)
            await asyncio.sleep(0.05)

    async def _ensure_max_media(self, broadcast: Broadcast) -> None:
        if not broadcast.media_kind or broadcast.max_media_token:
            return
        if not broadcast.media_path or self.max_client is None:
            raise MaxDeliveryError("Не найден медиафайл для MAX")
        media = await self.max_client.upload_media(broadcast.media_path)
        broadcast.max_media_type = media["media_type"]
        broadcast.max_media_token = media["token"]
        await self.repository.set_max_media(
            broadcast.id, media_type=media["media_type"], token=media["token"]
        )

    async def _send_max(self, broadcast: Broadcast, delivery: BroadcastDelivery) -> None:
        if delivery.target_id is None or self.max_client is None:
            raise MaxDeliveryError("Missing max_id")
        personalized = render_message(broadcast.message, delivery.recipient.name)
        message = adapt_telegram_html_for_max(personalized)
        await self.max_client.send_message(
            max_id=delivery.target_id,
            text=message,
            buttons=[{"text": item.text, "action_key": item.action_key} for item in broadcast.buttons],
            media_type=broadcast.max_media_type,
            media_token=broadcast.max_media_token,
        )

    async def _send_telegram(self, broadcast: Broadcast, delivery: BroadcastDelivery) -> None:
        if delivery.target_id is None:
            raise ValueError("Missing telegram_id")
        message = render_message(broadcast.message, delivery.recipient.name)
        keyboard = self._build_keyboard(broadcast)

        async def send() -> None:
            if broadcast.media_kind == "photo":
                await self.bot.send_photo(
                    chat_id=delivery.target_id,
                    photo=FSInputFile(broadcast.media_path),
                    caption=message,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                )
            elif broadcast.media_kind == "video":
                await self.bot.send_video(
                    chat_id=delivery.target_id,
                    video=FSInputFile(broadcast.media_path),
                    caption=message,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                    supports_streaming=True,
                )
            else:
                await self.bot.send_message(
                    chat_id=delivery.target_id,
                    text=message,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML,
                )

        for attempt in range(3):
            try:
                await send()
                return
            except TelegramRetryAfter as error:
                if attempt == 2:
                    raise
                await asyncio.sleep(float(error.retry_after))
            except (TelegramNetworkError, TelegramServerError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)

    @staticmethod
    def _build_keyboard(broadcast: Broadcast) -> InlineKeyboardMarkup | None:
        if not broadcast.buttons:
            return None
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=button.text, callback_data=f"broadcast:{button.action_key}")]
            for button in broadcast.buttons
        ])

    @staticmethod
    def delete_media(media_path: str | None) -> None:
        if not media_path:
            return
        try:
            Path(media_path).unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not delete broadcast media %s", media_path)
