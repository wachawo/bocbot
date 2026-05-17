# bocbot

[English](https://github.com/battleofcode/bocbot/blob/main/README.md) | [中文](https://github.com/battleofcode/bocbot/blob/main/docs/README_ZH.md) | [हिन्दी](https://github.com/battleofcode/bocbot/blob/main/docs/README_HI.md) | [Español](https://github.com/battleofcode/bocbot/blob/main/docs/README_ES.md) | [Français](https://github.com/battleofcode/bocbot/blob/main/docs/README_FR.md) | [العربية](https://github.com/battleofcode/bocbot/blob/main/docs/README_AR.md) | **[Русский](https://github.com/battleofcode/bocbot/blob/main/docs/README_RU.md)**

Шаблон игрока для **Battle of Code** — многопользовательской игры на захват территории, где каждый запускает своего бота (или играет вручную из терминала).

**Что даёт этот шаблон**

- Рабочий терминальный клиент с Rich UI (`client/`), в который можно играть по WSAD.
- Стартового бота (`bot.py`), которого можно править — это и есть весь бот, один файл.
- Три небольших скрипта в `tools/`, которые регистрируют вас на сервере.
- Документацию, где буквально расписан wire-протокол и авторизация.

Здесь ничего не звонит домой и ничего не запутано. Полная регистрация — это 30 строк REST-запросов, которые можно выполнить руками. Скрипт делает всё это за вас, но в первый раз — и нужно — пройти процедуру шаг за шагом, чтобы видеть что происходит.

---

## Что такое регистрация на самом деле

Три вещи, не больше:

1. **Ed25519 keypair** у вас на диске. Приватный (`.key`) остаётся локально. Публичный (`.pub`) — это hex, 64 символа, одна строка.
2. **Ветка в вашем GitHub-форке**, названная вашим логином. На этой ветке лежит `keys/<login>.pub`. Сервер читает его один раз.
3. **Подписанный challenge.** Сервер выдаёт случайный nonce, вы подписываете его приватным ключом, сервер сверяет с публичным, который только что скачал с GitHub.

Это вся модель доверия. Никакого пароля, никакого JWT, никакого cookie. Каждая игровая сессия повторяет шаг 3 со свежим подписанным `hello`-фреймом.

---

## Quickstart — вручную, шаг за шагом

Сделайте это один раз руками. После этого скрипт делает те же вызовы.

Замените `<login>` на ваш GitHub-логин везде ниже.

### 1. Форкните и склонируйте

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
```

Или через веб-интерфейс GitHub, затем `git clone git@github.com:<login>/bocbot.git`.

### 2. Установите зависимости Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Вы получите:
- `cryptography` — генерация Ed25519-ключей и подписи
- `websockets` — игровой транспорт
- `rich` — интерактивный CLI-рендер
- `requests` — REST signup

### 3. Настройте `.env`

```bash
cp .env.example .env
$EDITOR .env
```

Установите `USERNAME=<login>`. Подправьте `BOC_AUTH_HOST` / `BOC_GAME_HOST`, если сервер не на `localhost`.

### 4. Сгенерируйте Ed25519 keypair — руками

Можно сделать одной командой Python (без дополнительных инструментов):

```bash
python3 - <<'PY'
import os, pathlib
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
login = os.environ.get("USERNAME")
key = Ed25519PrivateKey.generate()
priv = key.private_bytes(
    serialization.Encoding.Raw,
    serialization.PrivateFormat.Raw,
    serialization.NoEncryption(),
)
pub = key.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw,
)
pathlib.Path("keys").mkdir(exist_ok=True)
pathlib.Path(f"keys/{login}.key").write_bytes(priv)
os.chmod(f"keys/{login}.key", 0o600)
pathlib.Path(f"keys/{login}.pub").write_text(f"# bocbot key for {login}\n{pub.hex()}\n")
print("private:", f"keys/{login}.key", "(mode 0600)")
print("public :", f"keys/{login}.pub", pub.hex())
PY
```

Что получилось:

- `keys/<login>.key` — 32 raw-байта, режим `0600`. **Git-игнорируется.** Никогда не коммитьте это.
- `keys/<login>.pub` — hex публичный ключ, одна строка + комментарий. Безопасно коммитить.

> То же самое в виде скрипта: `python3 tools/keygen.py`. Это буквально команда выше с CLI-обёрткой.

### 5. Запушьте публичный ключ на свою ветку

```bash
git checkout -b <login>
git add keys/<login>.pub
git commit -m "register key"
git push -u origin <login>
```

`main` остаётся чистой. Ваша ветка `<login>` хранит вашу регистрацию. Сервер прочитает её по адресу:

```
https://raw.githubusercontent.com/<login>/bocbot/<login>/keys/<login>.pub
```

Можете сами `curl`-нуть этот URL чтобы убедиться что он доступен.

### 6. Регистрация — вручную

Два REST-вызова.

**Вызов 1: запросите challenge.** Сервер скачает ваш `key.pub` с GitHub, сохранит `(pubkey, nonce)` в Redis с TTL 60 секунд и вернёт nonce.

```bash
curl -s -X POST "http://${BOC_AUTH_HOST:-127.0.0.1}:${BOC_AUTH_PORT:-8000}/api/auth/signup" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"$USERNAME\"}"
```

Ответ:

```json
{"status":"challenge","nonce":"0f1e2d3c4b5a69788796a5b4c3d2e1f0","ttl":60}
```

**Вызов 2: подпишите nonce и подтвердите.** Nonce — это hex. Декодируете в байты, подписываете, hex-кодируете подпись, отправляете обратно.

```bash
NONCE=0f1e2d3c4b5a69788796a5b4c3d2e1f0   # из ответа выше
SIG=$(python3 - <<PY
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
key = Ed25519PrivateKey.from_private_bytes(open(f"keys/$USERNAME.key","rb").read())
print(key.sign(bytes.fromhex("$NONCE")).hex())
PY
)
curl -s -X POST "http://${BOC_AUTH_HOST:-127.0.0.1}:${BOC_AUTH_PORT:-8000}/api/auth/signup/verify" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"$USERNAME\",\"sig\":\"$SIG\"}"
```

Ответ:

```json
{"status":"ok","username":"<login>"}
```

Сервер теперь хранит `(username, pubkey)` в SQLite. Больше он на GitHub за вами не пойдёт.

> То же самое скриптом: `python3 tools/signup.py`. Он печатает каждый шаг с указанием какой именно вызов делает. См. [`docs/AUTH.md`](AUTH.md) для полной ссылочной документации.

### 7. Проверьте что можете играть

Смоук-тест игрового WebSocket:

```bash
python3 tools/login.py
```

Это открывает `ws://<host>:5555/`, шлёт подписанный `hello`-фрейм, ждёт `auth_ok` + `welcome`, шлёт один `ping`, печатает `pong`, закрывается. Если увидели две зелёные строки — всё работает.

Теперь поиграйте по-настоящему:

```bash
./play.sh                          # Rich UI терминальный клиент, WSAD
# или
python3 bot.py                     # стартовый бот — он проиграет, это нормально
```

Если хотите вернуться на `main` чтобы работать над ботом:

```bash
git checkout main
```

Вот и весь процесс. Один раз сделали руками. В следующий раз скрипт делает это за вас.

---

## Quickstart — скриптом

Если просто хотите играть и уже понимаете что происходит:

```bash
gh repo fork battleofcode/bocbot --clone --remote
cd bocbot
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env && $EDITOR .env       # установите USERNAME=<login>
python3 tools/signup.py                    # keygen + REST signup, попросит подтверждения перед push
./play.sh
```

`tools/signup.py`:

1. Копирует `.env.example` → `.env` если его нет, подтверждает `USERNAME`.
2. Генерирует keypair (идемпотентно — если `keys/<login>.key` существует, переиспользует).
3. **Делает паузу** и печатает четыре `git`-команды для push публичного ключа. Нажмёте Enter когда запушили.
4. Вызывает `/api/auth/signup`, подписывает nonce, вызывает `/api/auth/signup/verify`.

Прочитайте исходник — 200 строк.

---

## Игра вручную

`./play.sh` открывает Rich UI в терминале. Адрес и логин берутся из `.env` (`BOC_GAME_HOST`, `BOC_GAME_PORT`, `USERNAME`); CLI-флаги `client/client.py` имеют приоритет.

| Клавиша        | Действие |
|----------------|----------|
| `W`            | вверх    |
| `A`            | влево    |
| `S`            | вниз     |
| `D`            | вправо   |
| `Esc` / `Ctrl+C` × 2 | выход |

Клиент авто-реконнектится при обрыве WebSocket; сервер восстанавливает paused-игрока (тот же `id`, позиция, зона), пока не истёк `PAUSE_TIMEOUT`.

Запуск в режиме наблюдателя через `-f N` следит за живым игроком на месте N (1..128):

```bash
python3 client/client.py -f 1
```

---

## Что лежит в коробке

| Путь                   | Что это                                                                    |
|------------------------|----------------------------------------------------------------------------|
| `bot.py`               | стартовый бот, Python — **редактируйте `decide()`**                        |
| `bot.go`               | стартовый бот, Go — заглушка, ещё не реализован                            |
| `bot.js`               | стартовый бот, Node.js — заглушка, ещё не реализован                       |
| `client/`              | терминальный CLI-плеер (Rich UI, WSAD) — для игры человеком                |
| `play.sh`              | запуск CLI-клиента в сторону `battleofcode.com`                            |
| `tools/keygen.py`      | генерация Ed25519 keypair в `keys/<u>.key` + `keys/<u>.pub`                |
| `tools/signup.py`      | сквозная регистрация через REST API                                        |
| `tools/login.py`       | WebSocket-смоук-тест (hello → ping → pong)                                 |
| `docs/AUTH.md`         | подробно про авторизацию (REST signup, правила подписи, коды ошибок)       |
| `docs/API.md`          | wire-протокол (WebSocket-фреймы, state-сообщения, события)                 |
| `docs/RULES.md`        | правила игры (зоны, trail, capture, условия смерти)                        |
| `docs/EXAMPLES.md`     | сборник рецептов для бота                                                  |
| `keys/<u>.pub`         | ваш **публичный** ключ (закоммичен на ветку `<u>` вашего форка)            |
| `keys/<u>.key`         | ваш **приватный** ключ (git-игнорируется, режим 0600)                      |

---

## Как работает регистрация (вкратце)

1. Вы генерируете Ed25519 keypair (`tools/keygen.py` или Python-однострочник выше).
2. Приватный ключ остаётся в `keys/<your-login>.key` (git-игнорируется, режим `0600`).
3. Публичный ключ коммитится как `keys/<your-login>.pub` на ветку с именем вашего GitHub-логина.
4. `tools/signup.py` (или два `curl`-вызова) сообщает серверу ваш username; сервер скачивает публичный ключ из `keys/<login>.pub` на вашей ветке `<login>` и выдаёт короткоживущий nonce.
5. Скрипт подписывает nonce приватным ключом; сервер проверяет и сохраняет `(username, pubkey)` в SQLite. После этого нет обращений к GitHub.
6. Каждый коннект WebSocket несёт свежий подписанный `hello` (`{username, ts, sig}`). Сервер проверяет его против сохранённого публичного ключа. Никаких токенов, cookie, сессий.

`main` остаётся чистой: апстрим-PR не трогают ваш `.pub`. Ваша ветка — ваша регистрация.

Глубокие ссылки:
- [`docs/AUTH.md`](AUTH.md) — поток авторизации, коды ошибок, заметки по безопасности
- [`docs/API.md`](API.md) — wire-формат (REST + WebSocket)
- [`docs/RULES.md`](RULES.md) — игровая механика

---

## Улучшайте бота

Откройте `bot.py`. Весь бот — один файл. Единственная функция которую вы трогаете — `decide(state)` сверху.

- Прочитайте [`docs/RULES.md`](RULES.md) — что считается победой.
- Прочитайте [`docs/API.md`](API.md) — какая форма у `state` (это просто JSON-словарь).
- Прочитайте [`docs/EXAMPLES.md`](EXAMPLES.md) — рецепты (избегание стен, охота, метрики расстояния).

`bot.go` и `bot.js` — заглушки, которые печатают "not implemented yet". Если хотите играть на Go или Node — портируйте `bot.py`. Протокол ~80 строк реальной логики; всё остальное — `decide()` и обвязка реконнекта.

---

## Ссылки

- Сервер и live-лидерборд: <https://battleofcode.com>
- Issue tracker: заводите баги в апстрим `battleofcode/bocbot`

## Лицензия

MIT — см. [LICENSE](../LICENSE).
