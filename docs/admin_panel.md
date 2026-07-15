# Веб-админка рассылок

Админка запускается вместе с ботом и по умолчанию слушает:

```text
http://127.0.0.1:8106/tg_education/admin
```

Для включения добавьте в `.env`:

```env
ADMIN_PANEL_PASSWORD=replace-with-a-strong-password
ADMIN_SESSION_SECRET=replace-with-a-long-random-secret
ADMIN_DATA_DIR=./data/admin
WEB_ADMIN_HOST=127.0.0.1
WEB_ADMIN_PORT=8106
WEB_ADMIN_PREFIX=/tg_education/admin
MAX_BOT_API_URL=http://127.0.0.1:8107
MAX_BOT_API_SECRET=replace-with-the-same-secret-as-max-bot
```

Cookie админки имеет флаг `Secure`, поэтому внешний доступ должен идти через HTTPS reverse proxy.
Перед первым запуском примените миграции:

```powershell
.venv\Scripts\alembic.exe upgrade head
```

## Excel

Файл должен иметь формат `.xlsx` и содержать заголовки:

```text
telegram_id | max_id | Имя
```

`telegram_id` и `max_id` проверяются независимо: ошибка одного канала не мешает второму.
В тексте сообщения `[Имя]` заменяется значением соответствующей строки.

## HTML и кнопки

Поддерживаются обычные Telegram HTML-теги для жирного, курсивного, подчёркнутого и зачёркнутого текста, спойлеров, ссылок, кода и цитат. Разметка проверяется до создания рассылки.

Inline-кнопка может открыть главное меню, статистику, один из уроков или экзамен. Доступность урока повторно проверяется при нажатии пользователем.

## MAX и Nginx

В проекте `max_bot_edu_hp` задайте:

```env
BROADCAST_API_HOST=127.0.0.1
BROADCAST_API_PORT=8107
BROADCAST_API_SECRET=replace-with-the-same-secret-as-admin
```

Порт `8107` не публикуется через Nginx. Для админки путь должен передаваться без удаления префикса:

```nginx
location /tg_education/ {
    client_max_body_size 55m;
    proxy_pass http://127.0.0.1:8106;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Проверка внутреннего API:

```bash
curl -H "X-Broadcast-Secret: $BROADCAST_API_SECRET" http://127.0.0.1:8107/broadcast/health
```
