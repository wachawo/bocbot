# AUTH.md — авторизация в Battle of Code

[English](https://github.com/battleofcode/bocbot/blob/main/docs/AUTH_EN.md) | **[Русский](https://github.com/battleofcode/bocbot/blob/main/docs/AUTH_RU.md)**

> См. также: [API.md](API_RU.md) — realtime игровой протокол, [RULES.md](RULES_RU.md) — правила игры.

Battle of Code использует подписанный-hello на Ed25519: ни паролей, ни JWT, ни cookie, ни общих секретов. Якорь доверия — публичный ключ, который игрок публикует в своём GitHub-форке. Сервер скачивает его один раз при signup, сохраняет, и сверяет каждое последующее соединение с ним.

Этот документ описывает **REST signup поток**. **WebSocket hello**, который шлёт каждая игровая сессия, описан в [API.md](API_RU.md).

---

## 1. Модель идентичности

Игрок идентифицируется по **GitHub-логину**. Якорь доверия — Ed25519 keypair:

| Половина    | Где живёт                                                                                              | Кто видит   |
|-------------|---------------------------------------------------------------------------------------------------------|-------------|
| Приватный ключ | `keys/<username>.key` — 32 raw-байта, режим `0600`                                                   | только локально |
| Публичный ключ | `keys/<username>.pub` — hex 32 байта, закоммичен на ветку `<username>` вашего `bocbot`-форка          | весь мир    |

Сервер скачивает публичный ключ один раз во время signup по адресу:

```
https://raw.githubusercontent.com/<username>/bocbot/<username>/keys/<username>.pub
```

После signup сервер кэширует `(username, pubkey)` в SQLite auth-store и больше не обращается к GitHub для этого пользователя. Нет bearer-токенов, паролей, сертификатов, ротирующихся сессий.

### Почему GitHub?

- У каждого играющего уже есть GitHub-аккаунт.
- Имя ветки = GitHub-логин = display-имя. Один источник identity.
- Ротация ключа — `git push` на той же ветке, без вмешательства админа.
- Публичный ключ аудируется: любой может `curl`-нуть его.

### Почему Ed25519?

- 32-байтные ключи, 64-байтные подписи, ~70 µs на подпись на commodity-железе.
- Стандартная библиотечная поддержка в Python (`cryptography`), Go, Node.
- Детерминированно — не нужен RNG в момент подписи.

---

## 2. Signup-поток — два REST-вызова

Оба POST-эндпойнта rate-limited per source IP: **10 / час**, **50 / день**.

Поток двухшаговый, потому что сервер должен убедиться, что вызывающий действительно контролирует приватный ключ, соответствующий публичному ключу с GitHub. Nonce — это доказательство.

```
┌────────┐                            ┌────────┐                  ┌──────────┐
│ client │                            │ server │                  │  GitHub  │
└───┬────┘                            └────┬───┘                  └─────┬────┘
    │ POST /api/auth/signup               │                            │
    │ {"username":"alice"}                │                            │
    │ ─────────────────────────────────►  │                            │
    │                                     │ GET raw.../alice.pub       │
    │                                     │ ─────────────────────────► │
    │                                     │ ◄───── pubkey hex ──────── │
    │                                     │ сохранить (pubkey, nonce) в Redis (TTL 60s)
    │ ◄────── {nonce, ttl} ──────────────│                            │
    │                                     │                            │
    │ sign(nonce_bytes, priv_key)         │                            │
    │                                     │                            │
    │ POST /api/auth/signup/verify        │                            │
    │ {"username":"alice","sig":"..."}    │                            │
    │ ─────────────────────────────────►  │                            │
    │                                     │ Ed25519_verify(pubkey, nonce_bytes, sig)
    │                                     │ INSERT INTO auth(username, pubkey)
    │ ◄──────── {status:"ok"} ────────────│                            │
```

### Шаг 1 — `POST /api/auth/signup`

Request:

```json
{"username": "alice"}
```

Response **200**:

```json
{"status": "challenge", "nonce": "0f1e2d3c4b5a69788796a5b4c3d2e1f0", "ttl": 60}
```

`nonce` — hex-кодированные 16 байт. Подписывать нужно **raw-байты** (`bytes.fromhex(nonce)`), не hex-строку.

Ошибки:

| Status | `error`               | Когда                                                                  |
|-------:|-----------------------|------------------------------------------------------------------------|
| 400    | `bad_username`        | пусто, зарезервировано (`default`, `admin`, `root`, …), или не проходит GitHub-regex |
| 404    | `pubkey_fetch_failed` | ветка или файл не найдены по ожидаемому URL                            |
| 400    | `pubkey_fetch_failed` | тело `key.pub` не содержит 64-символьного hex-токена                   |
| 429    | `rate_limited`        | превышен per-IP лимит                                                  |
| 502    | `pubkey_fetch_failed` | GitHub недоступен                                                      |

### Шаг 2 — `POST /api/auth/signup/verify`

Подпишите **raw-байты** nonce приватным Ed25519-ключом. Отправьте hex-кодированную подпись.

Request:

```json
{"username": "alice", "sig": "abcd1234..."}
```

Response **200**:

```json
{"status": "ok", "username": "alice"}
```

Ошибки:

| Status | `error`         | Когда                                                       |
|-------:|-----------------|-------------------------------------------------------------|
| 400    | `nonce_missing` | нет активного signup-nonce (истёк через 60 s или не выдавался) |
| 401    | `bad_signature` | подпись не верифицируется относительно сохранённого pubkey  |
| 500    | `db_error`      | сбой server-side persistence                                |

---

## 3. Попробуйте руками

Python-однострочник ниже — минимум для подписания nonce приватным ключом с диска. Полная последовательность также в корневом [`README.md`](README_RU.md).

```bash
# Шаг 1: запросить challenge
curl -s -X POST "http://127.0.0.1:8000/api/auth/signup" \
     -H 'Content-Type: application/json' \
     -d '{"username":"alice"}'
# -> {"status":"challenge","nonce":"<HEX>","ttl":60}

# Шаг 2: подписать nonce
NONCE=<из ответа выше>
SIG=$(python3 - <<PY
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
key = Ed25519PrivateKey.from_private_bytes(open("keys/alice.key","rb").read())
print(key.sign(bytes.fromhex("$NONCE")).hex())
PY
)

# Шаг 3: verify
curl -s -X POST "http://127.0.0.1:8000/api/auth/signup/verify" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"alice\",\"sig\":\"$SIG\"}"
# -> {"status":"ok","username":"alice"}
```

Поставляемый `tools/signup.py` делает ровно те же три вызова плюс генерацию ключей и предохранитель от `USERNAME=default`. Прочитайте исходник целиком (~200 LOC) — там нет скрытой логики.

---

## 4. Потеря приватного ключа

Нет пути восстановления. Приватный ключ — это credential. Если он утерян:

1. Сгенерируйте новый keypair (`python3 tools/keygen.py`).
2. Force-push нового `keys/<login>.pub` на ветку `<login>` вашего форка.
3. Перезапустите `python3 tools/signup.py`. Сервер скачает новый публичный ключ с GitHub и перезапишет сохранённую запись.

Шаг 2 — force-push, потому что сервер **не доверяет git-истории** — он перечитывает `keys/<login>.pub` из текущей точки HEAD ветки `<login>`. Так что `git push --force-with-lease origin <login>` — достаточно.

---

## 5. Заметки по безопасности

- **Приватный ключ — это credential.** Всё, что может прочитать `keys/<login>.key`, может играть как вы. Режим `0600` enforce'ится `tools/keygen.py`; `.gitignore` исключает `keys/*.key`.
- **Nonce TTL — 60 секунд.** Если signup занимает больше (медленный GitHub fetch, ручная подпись) — получите `nonce_missing` и придётся начать с Шага 1.
- **Skew по timestamp в hello-фрейме — ±30 s.** Часы вашей машины должны быть примерно правильные. NTP обычно справляется.
- **Нет logout.** Каждый WebSocket-коннект подписывает свежий `hello`. Чтобы «разлогиниться» с украденного ключа — сгенерируйте новый keypair (раздел 4): старый публичный ключ на GitHub перезаписывается, новый заменяет его в auth DB на следующем signup.
- **Нет сброса пароля, восстановления по email.** В системе нет email и нет пароля. Если вы контролируете ветку `<login>` вашего `bocbot`-форка — вы контролируете identity `<login>`.

---

## 6. Почему такой дизайн

| Ограничение                          | Почему оно следует из этого дизайна                                          |
|--------------------------------------|------------------------------------------------------------------------------|
| Любой может зарегистрироваться без контакта с нами | Сервер тянет публичный ключ из публичной инфраструктуры (GitHub). |
| Identity верифицируется со стороны   | `curl https://raw.githubusercontent.com/<u>/bocbot/<u>/keys/<u>.pub` — этого достаточно. |
| Нет сброса пароля, нет email         | Якорь доверия — на GitHub. Кто контролирует ту ветку, тот и игрок.           |
| Дёшево верифицировать                | Ed25519-verify — ~30 µs. Никакого DB-lookup'а на пакет помимо закэшированного pubkey. |
| Нет session state                    | Каждый коннект подписывает свежий nonce-эквивалент (`username:ts`). Stateless-сервер. |

---

## 7. Ссылки

- [`tools/keygen.py`](../tools/keygen.py) — генератор keypair (идемпотентный).
- [`tools/signup.py`](../tools/signup.py) — end-to-end signup с промптами.
- [`tools/login.py`](../tools/login.py) — WebSocket-смоук-тест.
- [`API.md`](API_RU.md) — wire-формат gameplay (использует тот же приватный ключ для подписи каждого hello).
- RFC 8032 — спецификация Ed25519.
