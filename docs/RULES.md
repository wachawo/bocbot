# Правила, протокол и архитектура — единый канон

Этот файл объединяет игровые правила и техническую спецификацию протокола / архитектуры. Шесть компонентов (`server/`, `client/`, `bot/`, `botai/`, `botcouch/`, `scripts/`) должны быть с ним согласованы. При расхождениях побеждает этот файл.

---

## 1. Стек и нагрузка

- Python 3.12, стандартная библиотека где возможно.
- Сеть: TCP, line-delimited JSON (одно сообщение — одна строка с `\n`, UTF-8).
- Сервер — **asyncio** (`asyncio.start_server` + `StreamReader/StreamWriter`). Цель — до ~100 одновременных клиентов на одной машине без проседаний.
- Терминальный рендер у клиента: Rich (Live + Layout + Panel + Table); карта одним символом на клетку или на блок `VIEW_PACK × VIEW_PACK` клеток (downsample).
- `python-dotenv` для `.env`.
- Стиль кода — `~/.claude/rules/python.md` (snake_case, type hints, `main()`, формат логов `"%(asctime)s.%(msecs)03d [%(levelname)s]: (%(name)s) %(message)s"`).
- Не делать O(N²) по игрокам в горячем пути — коллизии через grid, не попарно.

---

## 2. Карта и базовые правила

- Карта — 2D grid `MAP_W × MAP_H` (по умолчанию **2000 × 1000**). Для одиночного отладочного запуска допустимо `--map-w 80 --map-h 40`.
- Координаты `(x, y)`: `x` — столбец `0..MAP_W-1`, `y` — строка `0..MAP_H-1`, `y` растёт вниз.
- Каждая клетка имеет:
  - `zone_owner` — id игрока-владельца (0 = никто).
  - `trail_owner` — id игрока, чья линия проходит через клетку (0 = нет).
  - Зона и trail могут одновременно жить на одной клетке, если владельцы разные.
- Игрок: `(x, y)`, направление `dir ∈ {"W","A","S","D","N"}` (`N` = стоит, пока не выбрал), `id`, имя, цвет.
- Стартовая зона — свободный квадрат 3×3, игрок в центре, счёт = 9.
- Управление: `W` (y−1), `S` (y+1), `A` (x−1), `D` (x+1). После выбора направления игрок не может встать сам.
- Скорость движения `SPEED` клеток/сек (целое или float). Сервер тикает `TICK_RATE=20` Гц; шаг происходит каждые `1/SPEED` сек.
- **90°-only**: поворот на 180° запрещён (`request_direction` отбрасывает противоположное). После каждого поворота — обязательный `turn_cooldown=1` шаг.
- Все игроки равны: и человек (`client`), и бот (`bot`/`botai`) подчиняются одним правилам.

### 2.1. Линия (trail)

- Пока клетка под игроком принадлежит **его** зоне — trail не растёт.
- Как только игрок шагнул на клетку, не принадлежащую его зоне, эта клетка становится его trail, `trail_len` растёт на 1.
- Пересечение **собственной** trail безопасно — игрок проходит сквозь, длина повторно не растёт. (Сознательное отступление от классики жанра ради удобства управления.)
- Если кто-то другой шагает на клетку с trail игрока X → игрок X умирает, его линия и не-захваченное стираются.

### 2.2. Захват зоны

Когда игрок с непустым trail возвращается на клетку своей зоны:

1. Все клетки его trail становятся его зоной.
2. Flood-fill от границ карты по всем клеткам, не принадлежащим зоне игрока.
3. Все клетки внутри bbox операции, **не** достижимые flood-fill, переходят в его зону (включая клетки чужих зон).
4. Чужой trail внутри захвата → владелец умирает; чужая зона внутри захвата — переходит без смерти владельца.

### 2.3. Связность зоны

После любого `capture` для каждого другого игрока выполняется BFS из его текущей позиции по его клеткам зоны. **Несвязанные** клетки (отрезанные «острова») обнуляются; площадь и `peak_area` пересчитываются. Гарантия: зона игрока всегда односвязна.

### 2.4. Смерть

| `reason`            | Условие                                                                            |
|---------------------|------------------------------------------------------------------------------------|
| `out_of_bounds`     | Шаг за пределы карты. Killer не записывается, `total_deaths` **не** растёт.        |
| `hit_enemy_trail`   | Другой игрок наехал на твою trail. Умирает владелец trail, наехавший живёт.        |
| `captured`          | Твой trail оказался внутри чужого захвата (flood-fill).                            |
| `trapped_in_zone`   | Каждая клетка твоего trail лежит внутри **одной и той же** чужой зоны.             |

`trapped_in_zone` защищает крупные территории от сквозного прохода: идти по краю чужой зоны или через несколько разных зон можно, полностью внутри одной — нельзя.

При смерти зона и trail обнуляются. Через `RESPAWN_DELAY` секунд (по умолчанию 3) сервер ищет новое свободное 3×3 и выдаёт игроку стартовую зону. Кумулятивные `kills`, `deaths`, `total_alive_seconds`, `peak_area` сохраняются.

**Инвариант kill/death-баланса**: смерть без явного killer (`out_of_bounds`) не увеличивает `total_deaths`. Гарантирует `sum(kills) == sum(deaths)` по серверу.

### 2.5. Pause / Resume

При **дисконнекте клиента** игрок не убивается, а ставится на паузу: `paused=True`, `paused_at=monotonic()`.

- `tick` пропускает paused-игроков в цикле движения; зона/trail остаются на карте.
- Если `trail_len == 0` — paused-игрок **полностью защищён**.
- Если `trail_len > 0` — другие могут наехать на trail и убить (иначе брошенные хвосты становились бы непробиваемыми преградами).
- При **повторном `join` с тем же `name`** сервер находит paused-игрока и восстанавливает его (id, x, y, zone, trail, area, kills, deaths). В `welcome` идёт исходный id.
- Если пауза длится дольше `PAUSE_TIMEOUT` (env, default 300 сек) — игрок удаляется полностью, id больше не используется; при reconnect — новый id и новая зона.

---

## 3. Протокол сети

### 3.1. Клиент → сервер

```json
{"cmd":"join","name":"player1","token":"<jwt>","is_bot":false,"is_view":false,"follow_rank":0}
```
- `token` — JWT из `data/auth.db`; пустая строка — анонимный join, сервер сам выдаёт токен в `auth_ok`.
- `is_bot` помечает клиента как бота (для метрик).
- `is_view=true` — наблюдатель: WASD игнорируется, спектрум pid'ов 1024..; `follow_rank>0` центрирует view на N-м игроке лидерборда.

```json
{"cmd":"dir","d":"W"}
{"cmd":"ping","t":1234567890.123}
{"cmd":"quit"}
{"cmd":"admin_auth","token":"<ADMIN_TOKEN>"}
{"cmd":"admin_view"}
```

`admin_auth` авторизует соединение как admin (только при совпадении со server-side `ADMIN_TOKEN`); далее `admin_view` отдаёт полную карту вместо урезанной — используется `server/views.py`.

### 3.2. Сервер → клиент

**Приветствие:**
```json
{"type":"welcome","id":42,"map_w":2000,"map_h":1000,"tick_rate":20,"speed":5.0,
 "view_w":201,"view_h":101,"handicap":3,"is_bot_handicap":0}
```
`view_w`/`view_h` всегда **нечётные** (игрок в центре).

**Состояние (с частотой `STATE_RATE`, по умолчанию 10 Гц):**
```json
{"type":"state","tick":1234,"uptime_sec":3600,
 "me":{"id":42,"x":50,"y":20,"dir":"W","alive":true,
        "trail_len":12,"area":18,"score":18,"deaths":0,"kills":1,
        "spectating":false,"follow_rank":0},
 "view":{"x0":30,"y0":10,"w":201,"h":101,
         "zone":[[0,0,1,...],...],
         "trail":[[0,0,0,...],...]},
 "players":[{"id":1,"x":55,"y":20,"name":"bot1","dir":"D"}],
 "scores":[{"id":42,"name":"p1","area":18,"peak_area":33,
            "avg_area_1m":15.3,"kills":1,"deaths":0,
            "alive":true,"paused":false,"alive_seconds":120.4,
            "alive_human":"2m"}]}
```
- `uptime_sec` — секунды с момента старта сервера (показывается в footer клиента).
- `view.zone[y][x]` / `view.trail[y][x]` — id владельцев (0 = пусто); координаты в массиве относительны: `(x0 + x_idx, y0 + y_idx)`.
- `players` — только видимые в окне обзора (с учётом handicap).
- `scores` — полный список (для dashboard).

**События:**
```json
{"type":"died","reason":"hit_enemy_trail","tick":1234,"killer":7,"area_lost":18}
{"type":"captured","tick":1234,"area_gained":15,"trail_len":12,"total_area":33}
{"type":"kill","tick":1234,"victim":7,"victim_name":"bot2","via":"trail"}
{"type":"respawn","tick":1240,"x":60,"y":30}
{"type":"pong","t":1234567890.123,"server_t":1234567890.500}
{"type":"auth_ok","new":true,"token":"<jwt>"}
{"type":"auth_error","reason":"...","message":"..."}
{"type":"admin_auth_result","ok":true}
{"type":"admin_state",...}
```

### 3.3. Идентификаторы

- Настоящие игроки: pid `1..`.
- Spectators (view-only): pid `1024..` (не пересекаются с реальными игроками, не показываются в `players_visible`, не могут быть `follow`-целью).

---

## 4. Конфигурация (.env)

`.env.example` в корне (закоммичен; реальный `.env` в `.gitignore`).

```dotenv
# Server
SERVER_HOST=0.0.0.0
SERVER_PORT=5555
MAP_W=2000
MAP_H=1000
TICK_RATE=20
STATE_RATE=10
SPEED=5.0
VIEW_W=201
VIEW_H=101
VIEW_PACK=5            # Client-side downsample: N×N cells folded into one terminal char
HANDICAP=3
BOT_HANDICAP=0
RESPAWN_DELAY=3.0
PAUSE_TIMEOUT=300.0
MAX_PLAYERS=128
LOG_LEVEL=INFO
STATS_FILE=stats.txt
STATS_INTERVAL=5.0
ADMIN_TOKEN=           # пусто → сервер сгенерирует и впишет через dotenv.set_key
AUTH_DB_PATH=data/auth.db

# Client
CLIENT_ADDR=127.0.0.1
CLIENT_PORT=5555
CLIENT_NAME=player
CLIENT_LOG_FILE=
CLIENT_FOLLOW_RANK=0

# Bot — основной конфиг в bot/bot.yml; env остаётся как fallback / для CI.
BOT_ADDR=127.0.0.1
BOT_PORT=5555
BOT_NAME=bot                 # "" или "bot" → автонумерация bot1/bot2/...
BOT_VISION_RADIUS=50
BOT_MAX_EXPLORE_DIST=100
BOT_MAX_TRAIL_LEN=80
BOT_SAFETY_FACTOR=2.0        # форс-RETURN если враг в N× ближе к моей зоне
BOT_WAYPOINT_FORWARD=20
BOT_WAYPOINT_SIDE=12
BOT_LOG_FILE=log.csv
```

### Приоритет конфига бота

CLI → env (`BOT_*`) → `bot/bot_optimized.yml` (если botcouch его сгенерировал) → `bot/bot.yml` → defaults.

### Bot YAML (`bot/bot.yml`)

```yaml
addr: 127.0.0.1
port: 5555
name: bot
vision_radius: 50
max_explore_dist: 100
max_trail_len: 80
safety_factor: 2.0
waypoint_forward: 20
waypoint_side: 12
log_file: log.csv
rounds: 0
log_level: INFO
```

### Admin token

`ADMIN_TOKEN` гейтит `server/views.py` (full-map admin viewer). Логика — `server/config.py:ensure_admin_token()`:

- Если `ADMIN_TOKEN` пуст — сервер генерирует `secrets.token_urlsafe(32)` и через `dotenv.set_key` записывает обратно в `.env`. Путь — `find_dotenv(usecwd=True)`.
- В Docker `.env` примонтирован RW в `boc_server` (`./.env:/opt/game-online/.env`), чтобы `set_key` работал внутри.
- `views.py` берёт токен из env через `load_dotenv` + `os.getenv("ADMIN_TOKEN")`.
- Проверка токена — **только** на сервере (`net.py:admin_auth`).

---

## 5. CLI

```
server/server.py [--host H] [--port P] [--map-w W] [--map-h H] [--speed S] [--tick-rate R] [--max-players N]
client/client.py [-a addr] [-p port] [-n name] [-l log.csv] [-f follow_rank]
bot/bot.py       [--addr A] [--port P] [--name N] [--vision R] [--max-dist D] [--max-trail T]
                 [--safety-factor F] [--waypoint-forward N] [--waypoint-side N]
                 [--rounds N] [--config bot.yml] [--log log.csv]
botai/botai.py   [--addr A] [--port P] [--name N] [--lr X] [--log log.csv]
botcouch/train.py [--input FILE[:FILE...]] [--output FILE] [--model FILE]
                  [--multi N] [--fail-penalty X] [--report] [--no-keras]
server/views.py  [-a addr] [-p port] [-t ADMIN_TOKEN] [-i interval]
```

Приоритет: CLI > env > defaults.

---

## 6. Раскладка репозитория

```
game-online/
├── .env.example, README.md, RULES.md, IDEAS.md, CHANGELOG.md
├── server/      server.py · game.py · net.py · views.py · auth.py · config.py · requirements.txt
├── client/      client.py · render.py · input.py · logger.py · config.py · token_io.py · requirements.txt
├── bot/         bot.py · ai.py · logger.py · config.py · bot.yml · requirements.txt · configs/
├── botai/       botai.py · probabilistic.py · logger.py · config.py · botai.yml · requirements.txt
├── botcouch/    train.py · features.py · model.py · optimize.py · requirements.txt
└── scripts/     orchestrator.py · mutate_configs.py · botcouch_loop.sh · requirements.txt
```

`LOOP.md` — служебный (cron-чек-лист), в гит не коммитим.

---

## 7. Боты

### 7.1. Детерминированный `bot/`

Состояния: `IDLE`, `EXPLORING`, `RETURNING`, `HUNTING_TRAIL`, `DEAD`.

Переходы (проверяются каждый тик):
1. `alive == false` → `DEAD`, ждать respawn.
2. Видна чужая trail-клетка, владелец виден, и `dist(self, enemy_trail) < dist(enemy_pos, enemy_trail)` → `HUNTING_TRAIL`.
3. **Safety-factor**: для каждого видимого врага `D_self` (Манхэттен до моей зоны) и `D_enemy` (то же от него до моей зоны). Если `D_enemy × BOT_SAFETY_FACTOR < D_self` → принудительный `RETURNING`. Событие `safety_retreat`.
4. Враг в радиусе `BOT_VISION_RADIUS` (Чебышёв) → `RETURNING`.
5. `trail_len > BOT_MAX_TRAIL_LEN` или `dist_to_home > BOT_MAX_EXPLORE_DIST` → `RETURNING`.
6. Иначе → `EXPLORING`.

Pathfinding: BFS на view, эвристика — Манхэттен. Если цель за пределами view — идти к ней по компасу, избегая чужих trail и края карты. Своя trail проходима.

#### Waypoint exploration

Прямоугольный план из 4 фаз:
1. `forward` — `BOT_WAYPOINT_FORWARD` шагов прочь от центра зоны (доминирующая ось от `home_center` к текущей позиции).
2. `side` — `BOT_WAYPOINT_SIDE` шагов перпендикулярно (направление по `my_id % 2`).
3. `backward` — те же `forward` шагов в противоположном направлении.
4. `side2` — `side` шагов обратно.

После завершения 4 фаз — принудительный `RETURNING`. Прямая линия не используется: квадрат с возвратом устойчивее к перерезанию. Если в обзоре **нет** врагов — `forward`/`side` удваиваются.

### 7.2. Probabilistic `botai/`

Для каждого `d ∈ {W,A,S,D}`:

- `P_survive(d) = sigmoid(z)`, `z` — линейная комбинация фич (расстояние до врагов и их trail, шаг за границу, safety_ratio).
- `E_area(d) = w_a0 + w_a_capture · f_capture + w_a_explore · f_explore`.
- `score(d) = P_survive · max(0, E_area) − w_pen · (1 − P_survive)`.

Выбор: `argmax` (или softmax-семплинг при `softmax_temperature > 0`).

**Online learning (REINFORCE-like):** после каждого `episode_end`:

```
reward    = captured_area_total − 0.5 × deaths − 0.2 × wasted_trail_total
advantage = reward − baseline_ema
w        := clip(w + lr × advantage × ∇score(action_taken), ±0.5 per step)
```

Веса сохраняются в `botai/botai.yml`.

---

## 8. Логи

Все три актёра (`client`, `bot`, `botai`) пишут **один CSV-формат**. Фиксированный порядок колонок:

```
t, episode_id, kind, event, action, ai_state, tick_outcome,
x, y, dir, trail_len, own_area, alive_seconds,
dist_to_home, nearest_enemy_dist, nearest_enemy_dx, nearest_enemy_dy,
nearest_enemy_trail_dist, n_enemies_visible,
source, actor_name,
cfg_vision_radius, cfg_max_explore_dist, cfg_max_trail_len, cfg_safety_factor,
extra
```

- `kind ∈ {tick, event}`. Для `kind=tick` поле `event` пусто; для `kind=event` — `action`/`tick_outcome` пусты.
- `event ∈ {capture, capture_fail, hunt_start, hunt_kill, hunt_abort, hunt_fail, explore_fail, explore_plan_start, safety_retreat, death, respawn, kill, player_input, round_summary, episode_end}`.
- `source ∈ {bot, botai, human}` — `botcouch` использует как категориальный признак.
- `tick_outcome ∈ {success, failure, neutral}` проставляется **ретроактивно** при flush буфера эпизода (на milestone-событии). Так в логе есть и положительные, и отрицательные размеченные примеры.
- `extra` — JSON-строка с доп. полями (`area_gained`, `killer`, `reason`, `fwd_dir`, `side_steps`, `weights`, `score_per_dir`, …).

Файлы можно скармливать `botcouch/train.py` через двоеточие-разделитель: `--input bot/log.csv:botai/log.csv:client/alice.csv`.

### Семантика буферизации

Бот/botai буферизуют per-tick записи внутри текущего эпизода и сбрасывают их на диск на каждом milestone (`capture`, `capture_fail`, `hunt_fail`, `explore_fail`, `death`), проставляя `tick_outcome`. В конце эпизода — агрегирующая запись `episode_end` (kind=event):

```jsonc
// extra-поле episode_end:
{"captured_area_total":40,"captured_length_total":80,"kills":1,"deaths":1,
 "alive_seconds":18.3,"survived":false,
 "capture_fails":2,"hunt_fails":1,"explore_fails":1,
 "wasted_trail_total":33,"final_area":18,"avg_capture_area":13.3}
```

`wasted_trail_total` — суммарная длина trail, не приведённого к захвату (по всем `*_fail` событиям). Прямой негативный сигнал.

---

## 9. Очки, dashboard, статистика

| Поле                   | Что означает                                                                |
|------------------------|-----------------------------------------------------------------------------|
| `area`                 | Текущая площадь зоны игрока в клетках. Это «очки».                          |
| `peak_area`            | Максимальная площадь за сессию.                                             |
| `avg_area_1m`          | Среднее `area` за последние 60 секунд (выборка `STATS_INTERVAL` сек).       |
| `kills`                | Кумулятивное число убитых.                                                  |
| `deaths`               | Кумулятивное число смертей с явным killer (см. инвариант баланса).          |
| `alive_seconds`        | Кумулятивное время жизни.                                                   |
| `alive_human`          | Человекочитаемый формат: `1h15m` / `22m` / `8s`.                            |

Сервер раз в `STATS_INTERVAL` секунд (default 5) перезаписывает `stats.txt` с лидербордом, отсортированным по `area` ↓. Те же поля приходят клиенту в `state.scores` и рисуются в Rich-панели **`dashboard`** (исторически называлась `scoreboard` — теперь только `dashboard`).

---

## 10. Цвета и рендер у клиента

- 16-цветная палитра (8 ANSI + bright); индекс цвета владельца = `(owner_id - 1) % 16`.
- Клетка зоны: фон владельца.
- Клетка trail: тот же фон, но с `dim`-стилем (полупрозрачный «след домой»). Символ `·`.
- Клетка игрока: `@` (свой) / `O` (чужой) поверх фона.
- Пустая клетка: фон по умолчанию, пробел.
- Header: имя/id игрока, area, trail, kills, deaths, dir.
- Footer: подсказка управления + recent events + **server uptime** + статус соединения (`connected` / `reconnecting…`).
- Dashboard справа от карты (узкая колонка, 3 столбца: name / area / k-d), если терминал шире 60 cols.
- Handicap: бот получает урезанное view от сервера (`view_w − 2·handicap` × `view_h − 2·handicap`); клиент ничего сам не считает.

### Downsample (VIEW_PACK)

Карта на 2000×1000 не помещается в терминал. Клиент `client/render.py:build_map` свёртывает блоки `pack × pack` клеток в один символ: trail побеждает zone, маркер игрока поверх. Тот же приём в `server/views.py` для admin-viewer'а (там pack подбирается автоматически по ширине консоли).

Важно: сэмплировать **весь блок**, а не угол — иначе при `pack ≥ 3` тонкие trail'ы становятся невидимыми.

### Реконнект

Клиент держит Live-контекст через любой обрыв TCP: при `recv == 0` сокет закрывается, статус становится `reconnecting…`, ждём backoff (0.5 s → ×2 → cap 5 s), вызываем `connect_and_join` снова. Сервер по тому же `name`+`token` восстанавливает paused-игрока.

---

## 11. BotCouch — что обучаем

Цель: подобрать конфиг бота (`vision_radius`, `max_explore_dist`, `max_trail_len`, `safety_factor`, `waypoint_*`), который максимизирует `captured_area_total` за эпизод при низком `deaths`.

### Подходы

1. **sklearn `GradientBoostingRegressor`** — `(config, agg_features) → episode_reward`. `KFold` для валидации, R².
2. **keras dense network** — то же, но больше capacity. Включается по умолчанию; `--no-keras` отключает.
3. Подбор оптимума: `scipy.optimize` или сеточный + диверсификация (см. ниже).

### Per-episode фичи

Из CSV извлекаются на эпизод:

- `source` — категориальный (`bot`/`botai`/`human`).
- Средние/максимум: `dist_to_home`, `trail_len`, `nearest_enemy_dist`.
- Доли тиков с `n_enemies_visible > 0`, по AI-состояниям.
- Счётчики действий W/A/S/D, частота смены направления.
- `start_area`, `final_area`, `peak_area`, длительность эпизода.
- `captures`, `avg_capture_area`.
- `capture_fails`, `hunt_fails`, `explore_fails`, `wasted_trail_total` — негативные сигналы.
- Доли `tick_outcome ∈ {success, failure, neutral}`.

Дополнительно — классификатор `tick_outcome` по per-tick obs + config; при подборе конфига учитывается **двойная цель**: максимизировать `captured_area_total` и одновременно минимизировать `capture_fails + hunt_fails + explore_fails`.

### Diversity (`--multi N`)

Greedy MaxMin в нормализованном пространстве параметров: `N` конфигов с максимально разнообразными весами для параллельного запуска `N` ботов.

### Выход

YAML-конфиги в `bot/configs/botN.yml` (читается ботом поверх `bot.yml`).

---

## 12. Замечания по совместимости

- Все программы используют `logging.basicConfig` с форматом из `~/.claude/rules/python.md`.
- Сервер обязан корректно обрабатывать обрыв соединения клиента (paused → timeout → cleanup).
- Сервер не блокируется из-за медленного клиента: broadcast через asyncio с буфером на клиент; при переполнении клиент дисконнектится.
- pid не переиспользуется внутри сессии.
- Любые изменения правил/протокола начинаются с правки этого файла.
