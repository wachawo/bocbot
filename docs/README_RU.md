# bocbot

[English](../README.md) ([Quick setup](../README.md#quick-setup)) | **[Русский](README_RU.md)** ([краткая установка](#краткая-установка))

Шаблон игрока для **Battle of Code** — многопользовательской игры на захват территории, где каждый запускает своего бота (или играет вручную из терминала).

**Что даёт этот шаблон**

- Рабочий терминальный клиент с Rich UI (`client/`), в который можно играть по WSAD.
- Стартового бота (`bot.py`), которого можно править — это и есть весь бот, один файл.
- Три небольших скрипта в `tools/`, которые регистрируют вас на сервере.
- Документацию, где буквально расписан wire-протокол и авторизация.

У каждого шага установки есть однокомандная форма (рекомендуется) и ручной вариант — он описан в [`docs/AUTH_RU.md`](AUTH_RU.md) §3. В первый раз запускайте скрипт; ручной блок читайте, когда хотите увидеть, что именно скрипт делает.

---

## Регистрация в три шага

1. **Сгенерировать ключи.** `tools/keygen.py` создаёт `keys/<login>.key` (приватный, только у вас) и `keys/<login>.pub` (публичный, можно коммитить).
2. **Запушить публичный ключ в свой форк.** Положите `keys/<login>.pub` на ветку с именем `<login>` в вашем GitHub-форке — сервер прочитает его оттуда.
3. **Подтвердить на сервере.** `tools/signup.py` отправляет ваш логин; сервер скачивает публичный ключ с вашей ветки, выдаёт nonce, вы подписываете его приватным ключом.

Это вся модель доверия — никаких паролей, токенов, cookie. Подробности и ручной вариант: [`docs/AUTH_RU.md`](AUTH_RU.md).

---

## Краткая установка

Минимум действий от нуля до игры. Везде `<login>` — ваш GitHub-логин.


| #   | Действие                                                                                        |
| --- | ----------------------------------------------------------------------------------------------- |
| 1   | Форк и клон ([§1](#1-форкните-и-склонируйте))                                                   |
| 2   | `pip install -r requirements.txt` ([§2](#2-установите-зависимости-python))                      |
| 3   | `cp .env.example .env` и `USERNAME=<login>` ([§3](#3-настройте-env))                            |
| 4   | `python3 tools/signup.py` — ключи, `git push`, REST signup ([§6.1](#61-скриптом-рекомендуется)) |
| 5   | `./play.sh` или `python3 bot.py` ([§7](#7-проверьте-и-играйте))                                 |


**Только ключи** (без регистрации на сервере): после шага 3 — `python3 tools/keygen.py` ([§4](#4-сгенерируйте-ed25519-keypair)). Берёт `USERNAME` из `.env`, а не `$USERNAME` ОС (на Windows это разные значения).

**Руками / проверить себе:** [`docs/AUTH_RU.md`](AUTH_RU.md) §3 — генерация ключей без `tools/keygen.py` и signup через `curl`. Там же — коды ошибок и заметки по безопасности.

**Подробно:** [Quickstart §1–7](#quickstart) ниже · [English — Quick setup](../README.md#quick-setup) · [English — full Quickstart](../README.md#quickstart)

---

## Quickstart

Замените `<login>` на ваш GitHub-логин везде ниже. Сначала смотрите [краткую установку](#краткая-установка); здесь — те же шаги с пояснениями. Ручные альтернативы — в [`docs/AUTH_RU.md`](AUTH_RU.md) §3.

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

### 4. Сгенерируйте Ed25519 keypair

Вам нужны два файла в `keys/`: приватный `.key` (32 raw-байта, режим `0600`, **никогда не коммитьте**) и публичный `.pub` (hex, 64 символа, **безопасно коммитить**).

```bash
python3 tools/keygen.py
# или явно: python3 tools/keygen.py <login>
```

Без аргумента читает `USERNAME` из `.env` (не `$USERNAME` Windows). Создаёт `keys/<login>.key` и `keys/<login>.pub`. Идемпотентно — если приватный ключ уже есть, переиспользуется; публичный пересобирается из него. Отклоняет placeholder вроде `default`.

Хочется сделать то же руками, без скрипта? См. [`docs/AUTH_RU.md`](AUTH_RU.md) §3.1 — эквивалентный Python-однострочник.

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

### 6. Регистрация на сервере

Всего два REST-вызова: сервер выдаёт вам 60-секундный nonce, вы подписываете его, отправляете подпись обратно. После этого сервер хранит `(username, pubkey)` в SQLite и больше никогда не обращается к GitHub за вами.

#### 6.1. Скриптом (рекомендуется)

```bash
python3 tools/signup.py
```

Скрипт:

1. Подтверждает `USERNAME` из `.env`.
2. Генерирует keypair, если шаг 4 ещё не запускался (идемпотентно).
3. **Делает паузу** и снова печатает четыре `git`-команды из шага 5 — нажмите Enter после push.
4. Вызывает `/api/auth/signup`, подписывает nonce, вызывает `/api/auth/signup/verify`.

Исходник ~200 строк в `[tools/signup.py](../tools/signup.py)`. Никакой скрытой логики.

#### 6.2. ИЛИ руками

Два `curl`-вызова; подпишите nonce приватным ключом с диска:

```bash
# Вызов 1 — запросить challenge. Сервер скачивает ваш key.pub с GitHub,
# сохраняет (pubkey, nonce) в Redis (TTL 60 s), возвращает nonce.
curl -s -X POST "http://${BOC_AUTH_HOST:-127.0.0.1}:${BOC_AUTH_PORT:-8000}/api/auth/signup" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"$USERNAME\"}"
# -> {"status":"challenge","nonce":"<HEX>","ttl":60}

# Вызов 2 — подписать nonce (raw-байты, не hex-строку) и подтвердить.
NONCE=<вставить из ответа выше>
SIG=$(python3 - <<PY
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
key = Ed25519PrivateKey.from_private_bytes(open(f"keys/$USERNAME.key","rb").read())
print(key.sign(bytes.fromhex("$NONCE")).hex())
PY
)
curl -s -X POST "http://${BOC_AUTH_HOST:-127.0.0.1}:${BOC_AUTH_PORT:-8000}/api/auth/signup/verify" \
     -H 'Content-Type: application/json' \
     -d "{\"username\":\"$USERNAME\",\"sig\":\"$SIG\"}"
# -> {"status":"ok","username":"<login>"}
```

Коды ошибок, таблица failure-режимов и безопасность: `[docs/AUTH_RU.md](AUTH_RU.md)` · [English](AUTH_EN.md). Назад к [краткой установке](#краткая-установка).

### 7. Проверьте и играйте

Смоук-тест игрового WebSocket:

```bash
python3 tools/login.py
```

Открывает `ws://<host>:5555/`, шлёт подписанный `hello`-фрейм, ждёт `auth_ok` + `welcome`, шлёт один `ping`, печатает `pong`, закрывается. Две зелёные строки — значит всё работает.

Теперь играйте по-настоящему:

```bash
./play.sh                          # Rich UI терминальный клиент, WSAD
# или
python3 bot.py                     # стартовый бот — он проиграет, это нормально
```

Если хотите вернуться на `main` чтобы работать над ботом:

```bash
git checkout main
```

---

## Игра вручную

`./play.sh` открывает Rich UI в терминале. Адрес и логин берутся из `.env` (`BOC_GAME_HOST`, `BOC_GAME_PORT`, `USERNAME`); CLI-флаги `client/client.py` имеют приоритет.

Работает на Linux, macOS и Windows (для Windows предпочтителен Windows Terminal, а не старый `conhost`; Git Bash / MINGW64 тоже подходит). На любой ОС клиент можно запустить напрямую: `python3 client/client.py`.


| Клавиша              | Действие |
| -------------------- | -------- |
| `W`                  | вверх    |
| `A`                  | влево    |
| `S`                  | вниз     |
| `D`                  | вправо   |
| `Esc` / `Ctrl+C` × 2 | выход    |


Клиент авто-реконнектится при обрыве WebSocket; сервер восстанавливает paused-игрока (тот же `id`, позиция, зона), пока не истёк `PAUSE_TIMEOUT`.

Запуск в режиме наблюдателя через `-f N` следит за живым игроком на месте N (1..128):

```bash
python3 client/client.py -f 1
```

---

## Что лежит в коробке


| Путь               | Что это                                                                   |
| ------------------ | ------------------------------------------------------------------------- |
| `bot.py`           | стартовый бот, Python — **редактируйте `decide()`**                       |
| `bot.go`           | стартовый бот, Go — заглушка, ещё не реализован                           |
| `bot.js`           | стартовый бот, Node.js — заглушка, ещё не реализован                      |
| `client/`          | терминальный CLI-плеер (Rich UI, WSAD) — для игры человеком               |
| `play.sh`          | запуск CLI-клиента в сторону `battleofcode.com`                           |
| `tools/keygen.py`  | генерация Ed25519 keypair в `keys/<u>.key` + `keys/<u>.pub`               |
| `tools/signup.py`  | сквозная регистрация через REST API                                       |
| `tools/login.py`   | WebSocket-смоук-тест (hello → ping → pong)                                |
| `docs/AUTH_RU.md`  | подробно про авторизацию (REST signup, правила подписи, коды ошибок)      |
| `docs/API_RU.md`   | wire-протокол (фреймы, state-сообщения, события, примеры работы со state) |
| `docs/RULES_RU.md` | правила игры (зоны, trail, capture, смерть, анти-паттерны)                |
| `keys/<u>.pub`     | ваш **публичный** ключ (закоммичен на ветку `<u>` вашего форка)           |
| `keys/<u>.key`     | ваш **приватный** ключ (git-игнорируется, режим 0600)                     |


---

## Как работает регистрация (вкратце)

1. Вы генерируете Ed25519 keypair (шаг 4 выше).
2. Приватный ключ остаётся в `keys/<your-login>.key` (git-игнорируется, режим `0600`).
3. Публичный ключ коммитится как `keys/<your-login>.pub` на ветку с именем вашего GitHub-логина.
4. `tools/signup.py` (или два `curl`-вызова) сообщает серверу ваш username; сервер скачивает публичный ключ из `keys/<login>.pub` на вашей ветке `<login>` и выдаёт короткоживущий nonce.
5. Скрипт подписывает nonce приватным ключом; сервер проверяет и сохраняет `(username, pubkey)` в SQLite. После этого нет обращений к GitHub.
6. Каждый коннект WebSocket несёт свежий подписанный `hello` (`{username, ts, sig}`). Сервер проверяет его против сохранённого публичного ключа. Никаких токенов, cookie, сессий.

`main` остаётся чистой: апстрим-PR не трогают ваш `.pub`. Ваша ветка — ваша регистрация.

Глубокие ссылки (английские зеркала в скобках):

- `[docs/AUTH_RU.md](AUTH_RU.md)` ([EN](AUTH_EN.md)) — авторизация; дополняет [§6](#6-регистрация-на-сервере) и [краткую установку](#краткая-установка)
- `[docs/API_RU.md](API_RU.md)` ([EN](API_EN.md)) — wire-формат и примеры `state`
- `[docs/RULES_RU.md](RULES_RU.md)` ([EN](RULES_EN.md)) — механика и анти-паттерны
- `[README.md](../README.md#quick-setup)` — английская краткая установка · [полный Quickstart](../README.md#quickstart)

---

## Улучшайте бота

Откройте `bot.py`. Весь бот — один файл. Единственная функция которую вы трогаете — `decide(state)` сверху.

- Прочитайте `[docs/RULES_RU.md](RULES_RU.md)` — что считается победой и какие ходы убивают.
- Прочитайте `[docs/API_RU.md](API_RU.md)` — какая форма у `state` (это просто JSON-словарь) и короткие сниппеты как его потреблять.

`bot.go` и `bot.js` — заглушки, которые печатают "not implemented yet". Если хотите играть на Go или Node — портируйте `bot.py`. Протокол ~80 строк реальной логики; всё остальное — `decide()` и обвязка реконнекта.

---

## Ссылки

- Сервер и live-лидерборд: [https://battleofcode.com](https://battleofcode.com)
- Issue tracker: заводите баги в апстрим `battleofcode/bocbot`

## Лицензия

MIT — см. [LICENSE](../LICENSE).