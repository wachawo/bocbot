# API.md — wire-протокол Battle of Code

[English](https://github.com/battleofcode/bocbot/blob/main/docs/API_EN.md) | **[Русский](https://github.com/battleofcode/bocbot/blob/main/docs/API_RU.md)**

> См. также: [AUTH.md](AUTH_RU.md) — REST signup, [RULES.md](RULES_RU.md) — правила игры.

Этот документ описывает **realtime gameplay-протокол** — WebSocket-транспорт, сообщения, которые шлёт сервер, и команды, которые шлёт клиент.

Все payload'ы — JSON / UTF-8, один JSON-объект на текстовый WebSocket-фрейм. Имена полей стабильны; сервер терпит лишние поля, а клиент должен терпеть неизвестные типы сообщений.

---

## 1. Транспорт

- **URL:** `ws://<host>:<port>/` (сервер игнорирует path).
- **Default host:port:** `127.0.0.1:5555` для локальной разработки, `battleofcode.com:5555` для live-сервера.
- **Framing:** каждый WebSocket-фрейм текста — один JSON-объект.
- **Binary:** не используется.
- **Subprotocol negotiation отсутствует.**

---

## 2. Handshake — фрейм `hello`

Самый первый фрейм, который шлёт клиент, должен быть подписанным `hello`:

```json
{
  "type":        "hello",
  "username":    "alice",
  "ts":          1715900000,
  "sig":         "abcd1234...",
  "is_bot":      false,
  "is_view":     false,
  "follow_rank": 0
}
```

| Поле          | Тип       | Замечания                                                              |
|---------------|-----------|------------------------------------------------------------------------|
| `username`    | string    | GitHub-логин (заранее зарегистрирован через REST signup — см. [AUTH.md](AUTH_RU.md)) |
| `ts`          | int       | Unix-секунды. Сервер отбрасывает skew > 30 s в любую сторону           |
| `sig`         | string    | hex Ed25519 подпись над UTF-8 байтами `bocbot:hello:<username>:<ts>`   |
| `is_bot`      | bool      | боты получают суженный view для AI-tractability                        |
| `is_view`     | bool      | view-only спектатор; WSAD игнорируется, kill/death не засчитываются    |
| `follow_rank` | int 0-128 | только с `is_view=true`; центрирует view на живом игроке на месте N    |

### Подписываемая строка

Ровно `bocbot:hello:<username>:<ts>` — без padding'а, без newline, без JSON. UTF-8.

Пример подписи:

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import time
key = Ed25519PrivateKey.from_private_bytes(open("keys/alice.key", "rb").read())
ts  = int(time.time())
sig = key.sign(f"bocbot:hello:alice:{ts}".encode()).hex()
```

### Исходы

При успехе сервер шлёт `auth_ok`, затем `welcome`. При неуспехе — `auth_error` и закрывает WebSocket с close code `4401`:

```json
{"type": "auth_error", "reason": "bad_signature", "message": "...", "detail": "..."}
```

`reason` — одно из:
- `bad_request` — кривой `hello`
- `unknown_user` — username не зарегистрирован (никогда не проходил REST signup)
- `ts_out_of_window` — skew `ts` > 30 s
- `bad_signature` — подпись не верифицируется

---

## 3. Сообщения server → client

### `auth_ok`

```json
{"type": "auth_ok", "username": "alice"}
```

Шлётся сразу после успешного `hello`. State ещё нет.

### `welcome`

Шлётся один раз после `auth_ok`. Сообщает клиенту (и боту) геометрию мира и шлёт полный список владений игрока, чтобы свежий / восстановленный клиент мог раскрасить fog-of-war память до первого `state`.

```json
{
  "type":            "welcome",
  "id":              42,
  "map_w":           1024,
  "map_h":           768,
  "tick_rate":       20,
  "speed":           5.0,
  "view_w":          41,
  "view_h":          41,
  "handicap":        3,
  "is_bot_handicap": 0,
  "vision_radius":   20,
  "your_zone":       [[110, 80], [111, 80], ...],
  "your_trail":      [[123, 81], [123, 82]]
}
```

- `your_zone` — каждая клетка, в данный момент принадлежащая игроку, как пары `[x, y]`. Для свежего спавна это стартовый квадрат 3×3; для восстановленного paused-игрока — может быть сотни или тысячи клеток.
- `your_trail` — клетки, где живёт его незакрытый trail.
- Spectator'ы (`is_view=true`) получают пустые массивы.

### `state`

Периодический снимок с частотой `STATE_RATE` (по умолчанию 10 Hz). Массив dashboard `scores` rate-limited (~раз в 5 s); между ними поле опускается, и клиент должен сохранять предыдущий закэшированный список.

```json
{
  "type":       "state",
  "tick":       12345,
  "uptime_sec": 320,
  "me":         {"id": 42, "x": 314, "y": 159, "dir": "D", "alive": true, "area": 27, "trail_len": 0},
  "view":       {"x0": 290, "y0": 140, "w": 41, "h": 41, "zone": [[...]], "trail": [[...]]},
  "fog":        {"x0": 250, "y0": 100, "w": 123, "h": 123, "zone": [[...]], "trail": [[...]]},
  "players":    [{"id": 7, "x": 320, "y": 162, "name": "bob", "dir": "A"}],
  "scores":     [{"pid": 7, "name": "bob", "area": 412, "kills": 3, "deaths": 1}]
}
```

- `view.zone[y][x]` / `view.trail[y][x]` — id владельца клетки (0 = пусто). `(x0 + x_idx, y0 + y_idx)` — мировая координата.
- `fog.trail[y][x]` **отфильтрован до pid получателя только** — вы видите свой собственный trail вне view-окна, но никогда чужой.
- `players` — игроки, видимые в view-окне.
- `scores` — полный лидерборд для dashboard (rate-limited).

### Per-player события

Шлются только затронутому игроку.

#### `captured`

```json
{
  "type":        "captured",
  "area_gained": 18,
  "trail_len":   0,
  "total_area":  45,
  "cells":       [[120, 80], [121, 80], ...]
}
```

`cells` — список `[x, y]` пар клеток, только что ставших зоной игрока (и trail-клетки, и flood-filled-интерьер). Клиенты держат off-view fog-of-war память; применение этого delta — единственный способ перерисовать клетки вне live view, не дожидаясь пока игрок вернётся туда сам.

#### `died`

```json
{"type": "died", "reason": "trail_cut", "killer": 7, "area_lost": 27}
```

`reason ∈ {trail_cut, out_of_bounds, trapped_in_zone}`.

#### `kill`

```json
{"type": "kill", "victim": 42, "victim_name": "alice", "via": "trail_cut"}
```

Шлётся killer'у.

#### `respawn`

```json
{"type": "respawn", "x": 811, "y": 226}
```

Шлётся через `RESPAWN_DELAY` (по умолчанию 3 s) когда сервер выбрал новый свободный 3×3-спавн.

#### `pong`

```json
{"type": "pong", "t": 1715900000123, "server_t": 1715900000.456}
```

Ответ на client `ping`. `t` — это эхо того что клиент послал. Клиент использует `time.monotonic()` дельты для измерения round-trip latency.

---

## 4. Команды client → server

```json
{"cmd": "dir",  "d": "W"}
{"cmd": "ping", "t": 1715900000123}
{"cmd": "quit"}
```

### `dir`

Запрос смены направления. `d ∈ {"W", "A", "S", "D", "N"}`:

- `W` = вверх  (y − 1)
- `A` = влево  (x − 1)
- `S` = вниз   (y + 1)
- `D` = вправо (x + 1)
- `N` = без направления (default спавна / стоянка)

Сервер отбрасывает 180°-повороты и enforce'ит 1-tick cooldown после каждого поворота.

### `ping`

Проверка round-trip latency. Сервер отвечает `pong` немедленно.

### `quit`

Graceful disconnect. Сервер ставит игрока на паузу (зона + trail сохраняются) и закрывает WebSocket. Реконнект с тем же username и свежим подписанным `hello` (другой `ts`) восстанавливает игрока — см. Раздел 5.

---

## 5. Reconnect и pause / resume

При обрыве WebSocket сервер **не удаляет игрока** — ставит на паузу:

- зона и trail остаются на карте
- движение останавливается
- paused-игрок с пустым trail полностью неуязвим
- paused-игрок с непустым trail всё ещё может быть убит trail-cut (иначе брошенные trail становились бы непробиваемыми барьерами)

Реконнект с тем же `username` и свежим подписанным `hello` (`ts` меняется, `sig` подписывает новый `ts`) восстанавливает `id`, позицию и area игрока.

**Pause timeout:** `PAUSE_TIMEOUT` секунд (по умолчанию `300`). После этого игрок удаляется, pid освобождается, а реконнект создаёт совершенно нового игрока с новым pid и новым спавном.

### Takeover

Если уже открыто соединение под `username=alice` и приходит второе с валидным подписанным `hello` для того же `alice`, новое побеждает: старое закрывается с `4408 takeover`. Так выбивают забытую сессию.

---

## 6. Bot vs human

| Свойство         | Human (`is_bot=false`) | Bot (`is_bot=true`) |
|------------------|------------------------|---------------------|
| View dims        | `view_w × view_h`      | `(view_w − 2·BOT_HANDICAP) × (view_h − 2·BOT_HANDICAP)` |
| State rate       | `STATE_RATE` (10 Hz)   | то же |
| Spectator-режим  | доступен               | редко полезен |
| Score засчитан   | да                     | да |

Handicap существует, чтобы рефлекторно-идеальные боты не превращали людей в outright outclassed; боты видят чуть меньшее окно мира.

---

## 7. View-only спектатор

Установка `is_view=true` во фрейме `hello` открывает spectator-сессию. Отличия:

- WSAD `dir`-команды игнорируются.
- Spectator получает pid в диапазоне `1024..` (отдельно от реальных игроков `1..1023`).
- `follow_rank=N` (1..128) центрирует view на живом игроке, занимающем сейчас N-ое место в лидерборде. View переанкорируется каждый tick, если цель движется.
- `welcome.your_zone` / `welcome.your_trail` — всегда пустые.
- Kills и deaths не учитываются.

---

## 8. Версионирование

Изменения схемы — аддитивные. Ломающие изменения переедут на `/v2` под другим WebSocket-путём. Текущая черновая — неявный `/v1`.

Если сервер добавляет новые поля, клиенты должны игнорировать неизвестные. Если сервер отправляет неизвестные клиенту типы сообщений, клиент должен молча их дропать.

---

## 9. Ссылки

- [`tools/login.py`](../tools/login.py) — минимальный жизнеспособный клиент (hello → ping → pong → close).
- [`client/client.py`](../client/client.py) — полноценный Rich-UI плеер.
- [`bot.py`](../bot.py) — шаблон бота; `decide(state)` напрямую потребляет `state`-сообщения.
- [`AUTH.md`](AUTH_RU.md) — REST signup поток, производящий зарегистрированный pubkey, против которого этот протокол верифицируется.
- [`RULES.md`](RULES_RU.md) — игровая механика (зоны, trail'ы, capture, смерть).
