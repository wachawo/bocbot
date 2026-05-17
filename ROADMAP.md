# ROADMAP — bocbot (player repository template)

Публичный template-репозиторий (`bocbot`), который форкает каждый игрок. После форка он живёт по адресу `github.com/<user>/bocbot` — «твой bocbot». Одна команда `./scripts/setup.sh` даёт работающего бота с GitHub-auth. Конкуренция за форки и звёзды — часть мотивации.

## Структура репозитория

```
bocbot/
├── README.md              # quickstart, screenshots, link to battleofcode.com
├── CLAUDE.md              # instructions for Claude Code (AI agent)
├── AGENTS.md              # instructions for other AI assistants (Cursor, Aider, etc.)
├── LICENSE                # MIT
├── .gitignore             # keys/*, !.bocbot/key.pub
├── .bocbot/
│   └── key.pub            # PUBLIC key, committed
├── keys/                  # gitignored: <nick>.key (private)
├── scripts/
│   ├── setup.sh           # Linux/Mac: generate key, write .bocbot/key.pub
│   ├── setup.ps1          # Windows PowerShell
│   ├── validate.sh        # ping server, verify github fork + pubkey ok
│   └── play.sh            # convenience wrapper
├── client/                # CLI player (Python)
│   ├── client.py          # WS-connect, WSAD input, render
│   ├── render.py          # terminal Rich UI
│   ├── input.py           # cbreak stdin
│   ├── requirements.txt
│   └── README.md
├── bot/
│   ├── example/           # reference implementation — copy this
│   │   ├── bot.py
│   │   ├── ai.py
│   │   ├── README.md
│   │   └── requirements.txt
│   ├── mybot/             # YOUR bot lives here — empty stub initially
│   │   ├── bot.py         # `def decide(state) -> str:` stub returning "D"
│   │   └── README.md
│   └── sdk/
│       ├── python/        # официальный SDK (auth, ws, protocol types)
│       ├── nodejs/
│       └── go/
└── docs/
    ├── PROTOCOL.md        # full WS message schema
    ├── GAME-RULES.md      # capture / death / kill rules (copy of server RULES.md)
    └── EXAMPLES.md        # cookbook patterns
```

## Phase A — minimal stub (1 PR)

**Цель**: можно сделать `git clone bocbot && ./scripts/setup.sh && ./scripts/play.sh` и подключиться к серверу под своим github-ником.

- `scripts/setup.sh`:
  1. Определить GitHub-логин: `gh api user --jq .login` (если установлен gh) или интерактивно.
  2. Сгенерировать Ed25519 через python+cryptography (без openssl dependency).
  3. Записать `keys/<login>.key` (private, mode 0600).
  4. **Переключиться на ветку `<login>`**: `git checkout -B "$LOGIN"`. Эта ветка хранит только ключ — `main` остаётся чистым upstream'ом, PR-ы туда не задевают `.bocbot/`.
  5. Записать `.bocbot/key.pub`, `git add .bocbot/key.pub`, `git commit -m "register key"`, `git push -u origin "$LOGIN"`.
  6. **Вернуться в `main`**: `git checkout main` — далее игрок работает над ботом в main без риска уронить ключ в PR.
- `scripts/validate.sh`:
  1. Прочитать `.bocbot/key.pub` (либо в текущей ветке, либо явно из `git show "$LOGIN:.bocbot/key.pub"`).
  2. POST к `https://battleofcode.com/api/validate` с `{nickname, pubkey}`.
  3. Сервер последовательно проверяет: ветка `<nickname>` → fallback `default-branch`. Возвращает `ok / not-found / mismatch / fallback-on-main`. Если игрок попал на fallback-путь — выводим warning «ваш ключ в main, не в ветке `<nickname>` — это работает, но мешает чистым PR».
- `client/client.py`: WS-connect, отвечает на challenge через подпись `keys/<nick>.key`, играет в terminal Rich UI.

**Критерий приёмки**: новый юзер форкает → запускает 2 команды → играет.

## Phase B — example bot

**Цель**: дать референсного бота, чтобы понять, как писать своего.

- `bot/example/bot.py` — копия текущего `bot/bot.py` (deterministic state machine + safety) **минус** зависимости от текущего CLAUDE.md / docker-compose. Один-в-один работоспособная реализация.
- `bot/example/README.md`: построчное объяснение что делает каждый блок, ссылки на `docs/PROTOCOL.md` и `docs/GAME-RULES.md`.
- `bot/mybot/bot.py`: голый stub, `decide(state)` всегда возвращает `"D"` — заведомо плохая стратегия, чтобы игрок захотел улучшить.

**Критерий приёмки**: `cd bot/mybot && python bot.py` подключается и играет (плохо). Скопировать example → mybot даёт уже играющего бота.

## Phase C — AI-agent friendly docs

**Цель**: AI-ассистент (Claude / Cursor / Aider) одной командой пишет рабочего бота.

- `CLAUDE.md`:
  - Что такое Battle of Code в 3 предложениях.
  - Где живёт код бота (`bot/mybot/bot.py`), где живут rules (`docs/GAME-RULES.md`), где живёт протокол (`docs/PROTOCOL.md`).
  - Жирный bullet-list "если пользователь говорит 'улучши моего бота', делай X / читай Y / не трогай Z".
  - Запрет: никогда не комитить `keys/*` (с примером `.gitignore`).
- `AGENTS.md`: вариант для general-purpose агентов (Cursor, Aider, Roo Code) — менее Claude-specific формулировки.
- `docs/PROTOCOL.md`: JSON-schema всех WS messages с примерами в реальном времени.
- `docs/EXAMPLES.md`: книжка рецептов — "как добавить охоту на врагов", "как избегать стен", "как считать дистанцию".

**Критерий приёмки**: Claude Code, открытый в форке, на промпт "научи бота охотиться" пишет работающий PR.

## Phase D — multi-language SDKs

**Цель**: бота можно писать на любом языке. Только Python SDK обязателен; node/go/rust — community-contributable.

- `bot/sdk/python/bocbot/`:
  - `auth.py` — Ed25519 sign helper.
  - `ws.py` — WebSocket connect, challenge handshake, send_dir, recv_state generator.
  - `types.py` — TypedDict для всех server messages.
  - Один импорт: `from bocbot import Bot; class MyBot(Bot): def decide(self, state): ...`.
- `bot/sdk/nodejs/`: тот же интерфейс на TypeScript/Node 20+.
- `bot/sdk/go/`: для скоростных RL ботов.
- В `docs/PROTOCOL.md` — language-agnostic spec, SDK — конкретные реализации.

**Критерий приёмки**: `bot/example-nodejs/`, `bot/example-go/` — рабочие референсы, подключаются и играют.

## Phase E — distribution polish

**Цель**: повысить number of forks (звёздочка-фактор).

- `README.md` с GIF гифкой геймплея, скриншот leaderboard'а, кнопкой "fork to play".
- Тег `topic:BocServer` для GitHub discovery.
- Action `Validate registration`: GitHub Actions проверяют что `.bocbot/key.pub` валидный Ed25519 при push'е в ветку `<login>` → зелёный/красный бейдж в README.
- Upstream-only Action `no-keys-in-pr`: при PR в апстрим проверяем что diff не содержит `.bocbot/` — защита от случайного коммита ключа в main. Бот пишет: «rebase from main and drop your `.bocbot/` changes».
- `make-mybot` template script: `python -m bocbot create mybot --from example` — копирует example в новую директорию и переименовывает имена.

**Критерий приёмки**: новый игрок без чтения мануала за < 5 минут получает играющего бота.

## Что НЕ делаем

- Не делаем CLI bot management (start/stop/restart) — это работа docker / nohup.
- Не делаем серверный hosted-bot — каждый запускает у себя. Это намеренно — учит инфраструктуре.
- Не закрываем форк private — он должен быть public, чтобы public key читался.

## Открытые вопросы

- Поддерживать ли GitHub Enterprise (custom host)? Скорее нет на старте.
- Что делать с **тестовыми** ботами для CI/CD команды? Они могут жить в private `BocMobs` (Phase 0 server).
- Лицензия SDK — отдельная (Apache 2.0?) или общий MIT?
- Версионирование SDK — semver, breaking changes — отдельный PR в server и SDK синхронно.

## Связь с server roadmap

| server phase | требует от client repo |
|---|---|
| Phase 1 (WS gateway) | Phase A scripts/setup.sh + client/client.py использует WS |
| Phase 2 (GitHub auth) | Phase A `.bocbot/key.pub` + Ed25519 подпись в client |
| Phase 3 (web public) | — (client не зависит) |
| Phase 4 (leaderboards) | README показывает badge "your rank: #N" из `/api/profile/<nick>` |

Старт `bocbot` repo делается **после** server Phase 2 (auth готов) — раньше нет смысла, ничего не работает.
