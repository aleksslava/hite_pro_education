from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiohttp


class MaxServiceUnavailable(RuntimeError):
    pass


class MaxDeliveryError(RuntimeError):
    pass


class MaxBroadcastClient:
    def __init__(self, base_url: str, secret: str):
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self._session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def health(self) -> bool:
        await self._request("GET", "/broadcast/health")
        return True

    async def upload_media(self, media_path: str) -> dict[str, str]:
        path = Path(media_path)
        content = await asyncio.to_thread(path.read_bytes)
        payload = await self._request("POST", "/broadcast/media", upload=(path.name, content))
        media_type = str(payload.get("media_type", ""))
        token = str(payload.get("token", ""))
        if media_type not in {"image", "video"} or not token:
            raise MaxDeliveryError("Сервис MAX вернул некорректный ответ при загрузке медиа")
        return {"media_type": media_type, "token": token}

    async def send_message(
        self,
        *,
        max_id: int,
        text: str,
        buttons: list[dict[str, str]],
        media_type: str | None,
        media_token: str | None,
    ) -> None:
        payload: dict[str, Any] = {
            "max_id": max_id,
            "text": text,
            "buttons": buttons,
        }
        if media_type and media_token:
            payload["media"] = {"media_type": media_type, "token": media_token}
        await self._request("POST", "/broadcast/send", json=payload)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-Broadcast-Secret": self.secret},
                timeout=aiohttp.ClientTimeout(total=35, connect=5),
            )
        return self._session

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        upload = kwargs.pop("upload", None)
        last_error: Exception | None = None
        for attempt in range(3):
            if attempt:
                await asyncio.sleep(2 ** (attempt - 1))
            try:
                session = await self._get_session()
                request_kwargs = dict(kwargs)
                if upload is not None:
                    form = aiohttp.FormData()
                    form.add_field(
                        "file",
                        upload[1],
                        filename=upload[0],
                        content_type="application/octet-stream",
                    )
                    request_kwargs["data"] = form
                async with session.request(method, f"{self.base_url}{path}", **request_kwargs) as response:
                    payload = await self._response_payload(response)
                    if response.status < 400:
                        return payload
                    detail = str(payload.get("detail", f"HTTP {response.status}"))[:300]
                    if response.status == 429 or response.status >= 500:
                        if attempt < 2:
                            retry_after = response.headers.get("Retry-After")
                            if retry_after:
                                try:
                                    await asyncio.sleep(max(float(retry_after), 0))
                                except ValueError:
                                    pass
                            continue
                        raise MaxServiceUnavailable(f"Сервис MAX временно недоступен: {detail}")
                    if response.status in {401, 403, 404}:
                        raise MaxServiceUnavailable(f"Интеграция MAX недоступна: {detail}")
                    raise MaxDeliveryError(f"MAX отклонил доставку: {detail}")
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as error:
                last_error = error
                if attempt == 2:
                    raise MaxServiceUnavailable("Сервис MAX недоступен") from error
        raise MaxServiceUnavailable("Сервис MAX недоступен") from last_error

    @staticmethod
    async def _response_payload(response: aiohttp.ClientResponse) -> dict[str, Any]:
        try:
            payload = await response.json()
        except (aiohttp.ContentTypeError, ValueError):
            text = await response.text()
            return {"detail": text[:300] or f"HTTP {response.status}"}
        return payload if isinstance(payload, dict) else {"detail": "Некорректный ответ сервиса MAX"}
