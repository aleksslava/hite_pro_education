from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from db.models import Broadcast, BroadcastButton, BroadcastDelivery, BroadcastRecipient, User


class BroadcastRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def resolve_amo_users(
        self,
        amo_deal_ids: set[int],
    ) -> dict[int, list[dict[str, int | None]]]:
        if not amo_deal_ids:
            return {}
        async with self.session_factory() as session:
            result = await session.execute(
                select(User.amo_deal_id, User.tg_user_id, User.max_user_id)
                .where(User.amo_deal_id.in_(amo_deal_ids))
            )
            users: dict[int, list[dict[str, int | None]]] = {}
            for amo_deal_id, telegram_id, max_id in result.all():
                users.setdefault(amo_deal_id, []).append({
                    "telegram_id": telegram_id,
                    "max_id": max_id,
                })
            return users

    async def create_draft(
        self,
        *,
        message: str,
        source_filename: str,
        media_path: str | None,
        media_kind: str | None,
        media_original_name: str | None,
        scheduled_at: datetime,
        recipients: list[dict[str, Any]],
        buttons: list[dict[str, str]],
        stats: dict[str, Any],
        targets: set[str],
    ) -> int:
        async with self.session_factory() as session:
            broadcast = Broadcast(
                message=message,
                source_filename=source_filename,
                media_path=media_path,
                media_kind=media_kind,
                media_original_name=media_original_name,
                status="draft",
                scheduled_at=scheduled_at,
                created_at=datetime.now(timezone.utc),
                total_count=len(recipients),
                valid_count=stats["ready"],
                skipped_count=stats["skipped"],
                duplicate_count=stats["duplicates"],
                invalid_count=stats["invalid"],
                send_telegram="telegram" in targets,
                send_max="max" in targets,
            )
            session.add(broadcast)
            await session.flush()
            for position, item in enumerate(buttons):
                session.add(BroadcastButton(
                    broadcast_id=broadcast.id,
                    position=position,
                    text=item["text"],
                    action_key=item["action_key"],
                ))
            for item in recipients:
                recipient = BroadcastRecipient(
                    broadcast_id=broadcast.id,
                    row_number=item["row_number"],
                    telegram_id=item["telegram_id"],
                    raw_telegram_id=item["raw_telegram_id"],
                    max_id=item["max_id"],
                    raw_max_id=item["raw_max_id"],
                    amo_deal_id=item["amo_deal_id"],
                    raw_amo_deal_id=item["raw_amo_deal_id"],
                    name=item["name"],
                )
                session.add(recipient)
                await session.flush()
                for platform, delivery in item["deliveries"].items():
                    session.add(BroadcastDelivery(
                        broadcast_id=broadcast.id,
                        recipient_id=recipient.id,
                        platform=platform,
                        target_id=delivery["target_id"],
                        raw_target_id=delivery["raw_target_id"],
                        status=delivery["status"],
                        error=delivery["error"],
                    ))
            await session.commit()
            return broadcast.id

    async def get(self, broadcast_id: int) -> Broadcast | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Broadcast)
                .where(Broadcast.id == broadcast_id)
                .options(selectinload(Broadcast.buttons))
            )
            broadcast = result.scalar_one_or_none()
            if broadcast is not None:
                session.expunge(broadcast)
            return broadcast

    async def list(self, *, include_drafts: bool = False) -> list[Broadcast]:
        async with self.session_factory() as session:
            query = select(Broadcast).order_by(Broadcast.created_at.desc())
            if not include_drafts:
                query = query.where(Broadcast.status != "draft")
            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_recipients(
        self,
        broadcast_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BroadcastRecipient]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(BroadcastRecipient)
                .where(BroadcastRecipient.broadcast_id == broadcast_id)
                .options(selectinload(BroadcastRecipient.deliveries))
                .order_by(BroadcastRecipient.row_number)
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all())

    async def confirm(self, broadcast_id: int) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(Broadcast)
                .where(Broadcast.id == broadcast_id, Broadcast.status == "draft")
                .values(status="scheduled")
            )
            await session.commit()
            return bool(result.rowcount)

    async def delete_draft(self, broadcast_id: int) -> str | None:
        async with self.session_factory() as session:
            broadcast = await session.get(Broadcast, broadcast_id)
            if broadcast is None or broadcast.status != "draft":
                return None
            media_path = broadcast.media_path
            await session.delete(broadcast)
            await session.commit()
            return media_path

    async def cancel(self, broadcast_id: int) -> tuple[bool, str | None]:
        async with self.session_factory() as session:
            broadcast = await session.get(Broadcast, broadcast_id)
            if broadcast is None or broadcast.status != "scheduled":
                return False, None
            broadcast.status = "cancelled"
            broadcast.finished_at = datetime.now(timezone.utc)
            media_path = broadcast.media_path
            await session.commit()
            return True, media_path

    async def recover_interrupted(self) -> None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(BroadcastDelivery).where(BroadcastDelivery.status == "sending")
            )
            interrupted = list(result.scalars())
            affected: dict[int, int] = {}
            for delivery in interrupted:
                delivery.status = "unknown"
                delivery.error = "Отправка была прервана; результат неизвестен"
                delivery.finished_at = datetime.now(timezone.utc)
                affected[delivery.broadcast_id] = affected.get(delivery.broadcast_id, 0) + 1
            for broadcast_id, count in affected.items():
                broadcast = await session.get(Broadcast, broadcast_id)
                if broadcast is not None:
                    broadcast.error_count += count
            await session.execute(
                update(Broadcast).where(Broadcast.status == "running").values(status="scheduled")
            )
            await session.commit()

    async def claim_next_due(self) -> Broadcast | None:
        async with self.session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    select(Broadcast)
                    .where(
                        Broadcast.status == "scheduled",
                        Broadcast.scheduled_at <= datetime.now(timezone.utc),
                    )
                    .order_by(Broadcast.scheduled_at, Broadcast.id)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                broadcast = result.scalar_one_or_none()
                if broadcast is None:
                    return None
                broadcast.status = "running"
                broadcast.started_at = broadcast.started_at or datetime.now(timezone.utc)
                broadcast_id = broadcast.id
        return await self.get(broadcast_id)

    async def pending_deliveries(self, broadcast_id: int) -> list[BroadcastDelivery]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(BroadcastDelivery)
                .where(
                    BroadcastDelivery.broadcast_id == broadcast_id,
                    BroadcastDelivery.status == "pending",
                )
                .options(selectinload(BroadcastDelivery.recipient))
                .order_by(BroadcastDelivery.id)
            )
            return list(result.scalars().all())

    async def platform_stats(self, broadcast_id: int) -> dict[str, dict[str, int]]:
        result_stats = {
            platform: {
                "valid_count": 0,
                "processed_count": 0,
                "success_count": 0,
                "error_count": 0,
                "skipped_count": 0,
            }
            for platform in ("telegram", "max")
        }
        async with self.session_factory() as session:
            result = await session.execute(
                select(
                    BroadcastDelivery.platform,
                    BroadcastDelivery.status,
                    func.count(BroadcastDelivery.id),
                )
                .where(BroadcastDelivery.broadcast_id == broadcast_id)
                .group_by(BroadcastDelivery.platform, BroadcastDelivery.status)
            )
            for platform, status, count in result.all():
                if platform not in result_stats:
                    continue
                count = int(count)
                if status != "skipped":
                    result_stats[platform]["valid_count"] += count
                if status == "success":
                    result_stats[platform]["success_count"] += count
                    result_stats[platform]["processed_count"] += count
                elif status in {"error", "unknown"}:
                    result_stats[platform]["error_count"] += count
                    result_stats[platform]["processed_count"] += count
                elif status == "skipped":
                    result_stats[platform]["skipped_count"] += count
        return result_stats

    async def set_max_media(self, broadcast_id: int, *, media_type: str, token: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(Broadcast)
                .where(Broadcast.id == broadcast_id)
                .values(max_media_type=media_type, max_media_token=token)
            )
            await session.commit()

    async def clear_max_media(self, broadcast_id: int) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(Broadcast)
                .where(Broadcast.id == broadcast_id)
                .values(max_media_type=None, max_media_token=None)
            )
            await session.commit()

    async def fail_pending_platform(self, broadcast_id: int, platform: str, error: str) -> int:
        async with self.session_factory() as session:
            result = await session.execute(
                update(BroadcastDelivery)
                .where(
                    BroadcastDelivery.broadcast_id == broadcast_id,
                    BroadcastDelivery.platform == platform,
                    BroadcastDelivery.status == "pending",
                )
                .values(status="error", error=error, finished_at=datetime.now(timezone.utc))
            )
            count = int(result.rowcount or 0)
            broadcast = await session.get(Broadcast, broadcast_id)
            if broadcast is not None and count:
                broadcast.error_count += count
                broadcast.last_error = error
            await session.commit()
            return count

    async def mark_sending(self, delivery_id: int) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(BroadcastDelivery)
                .where(BroadcastDelivery.id == delivery_id, BroadcastDelivery.status == "pending")
                .values(status="sending", started_at=datetime.now(timezone.utc))
            )
            await session.commit()
            return bool(result.rowcount)

    async def mark_result(self, delivery_id: int, *, success: bool, error: str | None = None) -> None:
        async with self.session_factory() as session:
            delivery = await session.get(BroadcastDelivery, delivery_id)
            if delivery is None or delivery.status != "sending":
                return
            delivery.status = "success" if success else "error"
            delivery.error = error
            delivery.finished_at = datetime.now(timezone.utc)
            broadcast = await session.get(Broadcast, delivery.broadcast_id)
            if broadcast is not None:
                if success:
                    broadcast.success_count += 1
                else:
                    broadcast.error_count += 1
                    broadcast.last_error = error
            await session.commit()

    async def finish(self, broadcast_id: int) -> None:
        async with self.session_factory() as session:
            broadcast = await session.get(Broadcast, broadcast_id)
            if broadcast is None:
                return
            pending = await session.scalar(
                select(func.count(BroadcastDelivery.id)).where(
                    BroadcastDelivery.broadcast_id == broadcast_id,
                    BroadcastDelivery.status.in_(("pending", "sending")),
                )
            )
            if pending:
                broadcast.status = "scheduled"
            else:
                broadcast.status = "completed_with_errors" if broadcast.error_count else "completed"
                broadcast.finished_at = datetime.now(timezone.utc)
            await session.commit()

    async def fail(self, broadcast_id: int, error: str) -> None:
        async with self.session_factory() as session:
            broadcast = await session.get(Broadcast, broadcast_id)
            if broadcast is None:
                return
            result = await session.execute(
                update(BroadcastDelivery)
                .where(
                    BroadcastDelivery.broadcast_id == broadcast_id,
                    BroadcastDelivery.status == "pending",
                )
                .values(status="error", error=error, finished_at=datetime.now(timezone.utc))
            )
            broadcast.error_count += int(result.rowcount or 0)
            broadcast.status = "failed"
            broadcast.last_error = error
            broadcast.finished_at = datetime.now(timezone.utc)
            await session.commit()
