from __future__ import annotations

import asyncio
import math
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from starlette.datastructures import UploadFile

from web_admin.auth import client_key, get_csrf_token, is_authenticated, valid_csrf
from web_admin.validation import (
    ALLOWED_ACTIONS,
    MAX_XLSX_SIZE,
    TELEGRAM_CAPTION_LIMIT,
    TELEGRAM_TEXT_LIMIT,
    MAX_TEXT_LIMIT,
    UploadValidationError,
    parse_recipients,
    adapt_telegram_html_for_max,
    render_message,
    validate_buttons,
    validate_telegram_html,
)


MOSCOW_TZ = ZoneInfo("Europe/Moscow")
PHOTO_LIMIT = 10 * 1024 * 1024
VIDEO_LIMIT = 50 * 1024 * 1024
ALLOWED_MEDIA = {".jpg": "photo", ".jpeg": "photo", ".png": "photo", ".mp4": "video"}
STATUS_LABELS = {
    "draft": "Черновик",
    "scheduled": "Запланирована",
    "running": "Выполняется",
    "completed": "Завершена",
    "completed_with_errors": "Завершена с ошибками",
    "cancelled": "Отменена",
    "failed": "Ошибка",
    "pending": "Ожидает",
    "sending": "Отправляется",
    "success": "Доставлено",
    "error": "Ошибка",
    "skipped": "Пропущено",
    "unknown": "Результат неизвестен",
}


def _format_moscow(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M")


def _parse_schedule(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        local = datetime.fromisoformat(value).replace(tzinfo=MOSCOW_TZ)
    except ValueError as error:
        raise UploadValidationError("Некорректные дата и время запуска.") from error
    scheduled = local.astimezone(timezone.utc)
    return max(scheduled, datetime.now(timezone.utc))


def create_admin_router(prefix: str) -> APIRouter:
    router = APIRouter(prefix=prefix)
    templates_dir = Path(__file__).resolve().parent / "templates"
    templates = Jinja2Templates(directory=templates_dir)
    templates.env.filters["moscow"] = _format_moscow
    templates.env.globals.update(
        admin_prefix=prefix,
        status_labels=STATUS_LABELS,
        allowed_actions=ALLOWED_ACTIONS,
    )

    def redirect_login() -> RedirectResponse:
        return RedirectResponse(f"{prefix}/login", status_code=status.HTTP_303_SEE_OTHER)

    def require_admin(request: Request) -> RedirectResponse | None:
        return None if is_authenticated(request) else redirect_login()

    def require_csrf(request: Request, token: str) -> None:
        if not valid_csrf(request, token):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid_csrf")

    def context(request: Request, **values: Any) -> dict[str, Any]:
        return {"request": request, "csrf_token": get_csrf_token(request), **values}

    @router.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        if is_authenticated(request):
            return RedirectResponse(prefix, status_code=status.HTTP_303_SEE_OTHER)
        return templates.TemplateResponse(request=request, name="login.html", context={"error": None})

    @router.post("/login", response_class=HTMLResponse)
    async def login(request: Request):
        form = await request.form()
        password = str(form.get("password", ""))
        key = client_key(request)
        limiter = request.app.state.admin_rate_limiter
        if limiter.is_blocked(key):
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={"error": "Слишком много попыток. Повторите вход через 15 минут."},
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if not secrets.compare_digest(password, request.app.state.admin_config.password):
            limiter.record_failure(key)
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={"error": "Неверный пароль."},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        limiter.clear(key)
        request.session.clear()
        request.session["admin_authenticated"] = True
        get_csrf_token(request)
        return RedirectResponse(prefix, status_code=status.HTTP_303_SEE_OTHER)

    @router.post("/logout")
    async def logout(request: Request):
        if (redirect := require_admin(request)):
            return redirect
        form = await request.form()
        require_csrf(request, str(form.get("csrf_token", "")))
        request.session.clear()
        return redirect_login()

    @router.get("", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if (redirect := require_admin(request)):
            return redirect
        broadcasts = await request.app.state.admin_service.repository.list()
        summary = {
            "scheduled": sum(item.status == "scheduled" for item in broadcasts),
            "running": sum(item.status == "running" for item in broadcasts),
            "success": sum(item.success_count for item in broadcasts),
            "errors": sum(item.error_count for item in broadcasts),
        }
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context=context(request, broadcasts=broadcasts, summary=summary),
        )

    @router.get("/new", response_class=HTMLResponse)
    async def new_broadcast(request: Request):
        if (redirect := require_admin(request)):
            return redirect
        return templates.TemplateResponse(
            request=request,
            name="new.html",
            context=context(
                request,
                error=None,
                values={"send_telegram": True, "send_max": request.app.state.admin_config.max_enabled},
                max_enabled=request.app.state.admin_config.max_enabled,
            ),
        )

    @router.post("/preview", response_class=HTMLResponse)
    async def preview_broadcast(request: Request):
        if (redirect := require_admin(request)):
            return redirect
        form = await request.form()
        require_csrf(request, str(form.get("csrf_token", "")))
        message = str(form.get("message", "")).strip()
        scheduled_at = str(form.get("scheduled_at", ""))
        button_texts = [str(value) for value in form.getlist("button_text")]
        button_actions = [str(value) for value in form.getlist("button_action")]
        values = {"message": message, "scheduled_at": scheduled_at}
        media_path: Path | None = None
        try:
            targets: set[str] = set()
            if form.get("send_telegram"):
                targets.add("telegram")
            if form.get("send_max"):
                if not request.app.state.admin_config.max_enabled:
                    raise UploadValidationError("Интеграция MAX не настроена.")
                targets.add("max")
            if not targets:
                raise UploadValidationError("Выберите хотя бы один канал отправки.")
            values.update(
                send_telegram="telegram" in targets,
                send_max="max" in targets,
            )
            buttons = validate_buttons([
                {"text": button_texts[index] if index < len(button_texts) else "", "action_key": action}
                for index, action in enumerate(button_actions)
            ])
            recipients_file = form.get("recipients_file")
            if not isinstance(recipients_file, UploadFile) or not recipients_file.filename:
                raise UploadValidationError("Загрузите Excel-файл с получателями.")
            source_filename = Path(recipients_file.filename).name
            if Path(source_filename).suffix.casefold() != ".xlsx":
                raise UploadValidationError("Список получателей должен быть в формате .xlsx.")

            media_file = form.get("media_file")
            media_kind = None
            media_original_name = None
            media_content = b""
            if isinstance(media_file, UploadFile) and media_file.filename:
                media_original_name = Path(media_file.filename).name
                suffix = Path(media_original_name).suffix.casefold()
                media_kind = ALLOWED_MEDIA.get(suffix)
                if media_kind is None:
                    raise UploadValidationError("Допустимы JPG, JPEG, PNG и MP4.")
                limit = PHOTO_LIMIT if media_kind == "photo" else VIDEO_LIMIT
                media_content = await media_file.read(limit + 1)
                if not media_content:
                    raise UploadValidationError("Медиафайл пуст.")
                if len(media_content) > limit:
                    label = "10 МБ" if media_kind == "photo" else "50 МБ"
                    raise UploadValidationError(f"Медиафайл должен быть не больше {label}.")

            telegram_limit = TELEGRAM_CAPTION_LIMIT if media_kind else TELEGRAM_TEXT_LIMIT
            validate_telegram_html(
                message,
                limit=telegram_limit if "telegram" in targets else None,
            )
            if "max" in targets:
                adapt_telegram_html_for_max(message, limit=MAX_TEXT_LIMIT)
            excel_content = await recipients_file.read(MAX_XLSX_SIZE + 1)
            recipients, stats = await asyncio.to_thread(
                parse_recipients,
                excel_content,
                message,
                message_limit=telegram_limit,
                targets=targets,
            )
            service = request.app.state.admin_service
            if media_kind and media_original_name:
                media_path = service.media_dir / f"{uuid.uuid4().hex}{Path(media_original_name).suffix.casefold()}"
                await asyncio.to_thread(media_path.write_bytes, media_content)
            broadcast_id = await service.repository.create_draft(
                message=message,
                source_filename=source_filename,
                media_path=str(media_path) if media_path else None,
                media_kind=media_kind,
                media_original_name=media_original_name,
                scheduled_at=_parse_schedule(scheduled_at),
                recipients=recipients,
                buttons=buttons,
                stats=stats,
                targets=targets,
            )
            broadcast = await service.repository.get(broadcast_id)
            sample = [
                item for item in recipients
                if any(delivery["status"] == "pending" for delivery in item["deliveries"].values())
            ][:5]
            preview_html = render_message(message, sample[0]["name"] if sample else "")
            preview_max_html = (
                adapt_telegram_html_for_max(preview_html)
                if "max" in targets
                else preview_html
            )
            return templates.TemplateResponse(
                request=request,
                name="preview.html",
                context=context(
                    request,
                    broadcast=broadcast,
                    recipients=sample,
                    stats=stats,
                    preview_html=Markup(preview_html),
                    preview_max_html=Markup(preview_max_html),
                ),
            )
        except UploadValidationError as error:
            if media_path:
                media_path.unlink(missing_ok=True)
            return templates.TemplateResponse(
                request=request,
                name="new.html",
                context=context(
                    request,
                    error=str(error),
                    values=values,
                    max_enabled=request.app.state.admin_config.max_enabled,
                ),
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

    @router.post("/broadcasts/{broadcast_id}/confirm")
    async def confirm(request: Request, broadcast_id: int):
        if (redirect := require_admin(request)):
            return redirect
        form = await request.form()
        require_csrf(request, str(form.get("csrf_token", "")))
        service = request.app.state.admin_service
        if not await service.repository.confirm(broadcast_id):
            raise HTTPException(status_code=409, detail="broadcast_not_draft")
        service.wake()
        return RedirectResponse(f"{prefix}/broadcasts/{broadcast_id}", status_code=303)

    @router.post("/broadcasts/{broadcast_id}/discard")
    async def discard(request: Request, broadcast_id: int):
        if (redirect := require_admin(request)):
            return redirect
        form = await request.form()
        require_csrf(request, str(form.get("csrf_token", "")))
        service = request.app.state.admin_service
        service.delete_media(await service.repository.delete_draft(broadcast_id))
        return RedirectResponse(f"{prefix}/new", status_code=303)

    @router.post("/broadcasts/{broadcast_id}/cancel")
    async def cancel(request: Request, broadcast_id: int):
        if (redirect := require_admin(request)):
            return redirect
        form = await request.form()
        require_csrf(request, str(form.get("csrf_token", "")))
        service = request.app.state.admin_service
        cancelled, media_path = await service.repository.cancel(broadcast_id)
        if not cancelled:
            raise HTTPException(status_code=409, detail="broadcast_not_cancellable")
        service.delete_media(media_path)
        return RedirectResponse(f"{prefix}/broadcasts/{broadcast_id}", status_code=303)

    @router.get("/broadcasts/{broadcast_id}", response_class=HTMLResponse)
    async def detail(request: Request, broadcast_id: int, page: int = 1):
        if (redirect := require_admin(request)):
            return redirect
        broadcast = await request.app.state.admin_service.repository.get(broadcast_id)
        if broadcast is None or broadcast.status == "draft":
            raise HTTPException(status_code=404)
        page = max(page, 1)
        pages = max(1, math.ceil(broadcast.total_count / 100))
        page = min(page, pages)
        recipients = await request.app.state.admin_service.repository.get_recipients(
            broadcast_id, limit=100, offset=(page - 1) * 100
        )
        recipient_rows = [
            {
                "recipient": item,
                "deliveries": {delivery.platform: delivery for delivery in item.deliveries},
            }
            for item in recipients
        ]
        platform_stats = await request.app.state.admin_service.repository.platform_stats(broadcast_id)
        return templates.TemplateResponse(
            request=request,
            name="detail.html",
            context=context(
                request,
                broadcast=broadcast,
                recipient_rows=recipient_rows,
                platform_stats=platform_stats,
                page=page,
                pages=pages,
                message_html=Markup(broadcast.message),
            ),
        )

    @router.get("/broadcasts/{broadcast_id}/status")
    async def broadcast_status(request: Request, broadcast_id: int):
        if not is_authenticated(request):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        broadcast = await request.app.state.admin_service.repository.get(broadcast_id)
        if broadcast is None:
            raise HTTPException(status_code=404)
        platform_stats = await request.app.state.admin_service.repository.platform_stats(broadcast_id)
        processed = broadcast.success_count + broadcast.error_count
        progress = round(processed / broadcast.valid_count * 100) if broadcast.valid_count else 100
        return {
            "status": broadcast.status,
            "status_label": STATUS_LABELS.get(broadcast.status, broadcast.status),
            "success_count": broadcast.success_count,
            "error_count": broadcast.error_count,
            "skipped_count": broadcast.skipped_count,
            "processed_count": processed,
            "progress": progress,
            "platforms": platform_stats,
        }

    return router
