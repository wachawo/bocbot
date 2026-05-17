# API.md — Battle of Code wire protocol

> See also: [AUTH.md](AUTH.md) for the REST signup flow, [RULES.md](RULES.md) for game rules.

This document covers the **realtime gameplay protocol** — the WebSocket transport, the messages the server sends, and the commands the client sends.

All payloads are JSON / UTF-8, one JSON object per WebSocket text frame. Field names are stable; the server tolerates extra fields and clients should tolerate unknown message types.

---

## 1. Transport

- **URL:** `ws://<host>:<port>/` (the server ignores the path).
- **Default host:port:** `127.0.0.1:5555` for local dev, `battleofcode.com:5555` for the live server.
- **Framing:** each WebSocket text frame is one JSON object.
- **Binary:** unused.
- **No subprotocol negotiation.**

---

## 2. Handshake — the `hello` frame

The very first frame the client sends must be a signed `hello`:

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

| Field         | Type      | Notes                                                                  |
|---------------|-----------|------------------------------------------------------------------------|
| `username`    | string    | GitHub login (previously registered via REST signup — see [AUTH.md](AUTH.md)) |
| `ts`          | int       | Unix seconds. Server rejects skew > 30 s in either direction           |
| `sig`         | string    | hex Ed25519 signature over UTF-8 bytes of `bocbot:hello:<username>:<ts>` |
| `is_bot`      | bool      | bots get a tighter view window for AI tractability                     |
| `is_view`     | bool      | view-only spectator; WSAD ignored, no kill/death credits               |
| `follow_rank` | int 0-128 | only with `is_view=true`; centres view on the live player at rank      |

### The signed string

Exactly `bocbot:hello:<username>:<ts>` — no padding, no newline, no JSON. UTF-8 encoded.

Example sign:

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import time
key = Ed25519PrivateKey.from_private_bytes(open("keys/alice.key", "rb").read())
ts  = int(time.time())
sig = key.sign(f"bocbot:hello:alice:{ts}".encode()).hex()
```

### Outcomes

On success the server sends `auth_ok` followed by `welcome`. On failure it sends `auth_error` and closes the WebSocket with close code `4401`:

```json
{"type": "auth_error", "reason": "bad_signature", "message": "...", "detail": "..."}
```

`reason` is one of:
- `bad_request` — malformed `hello`
- `unknown_user` — username not registered (never went through REST signup)
- `ts_out_of_window` — `ts` skew > 30 s
- `bad_signature` — signature doesn't verify

---

## 3. Server → client messages

### `auth_ok`

```json
{"type": "auth_ok", "username": "alice"}
```

Sent immediately after a successful `hello`. No state yet.

### `welcome`

Sent once after `auth_ok`. Tells the client (and bot) the world geometry, and ships the player's full owned cell list so a fresh / resumed client can paint its fog-of-war memory before the first `state`.

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

- `your_zone` — every grid cell currently owned by the player, as `[x, y]` pairs. For a fresh spawn this is the 3×3 starting square; for a resumed paused player it can be hundreds or thousands of cells.
- `your_trail` — cells where their unclosed trail still lives.
- Spectators (`is_view=true`) get empty arrays.

### `state`

Periodic snapshot at `STATE_RATE` (default 10 Hz). The dashboard `scores` array is rate-limited (~once every 5 s); in between, the field is omitted and the client should keep its previous cached list.

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

- `view.zone[y][x]` / `view.trail[y][x]` — id of cell owner (0 = empty). `(x0 + x_idx, y0 + y_idx)` is the world coordinate.
- `fog.trail[y][x]` is **filtered to the recipient pid only** — you see your own trail outside your view window, but never enemy trails.
- `players` — visible players in the view window only.
- `scores` — full leaderboard for the dashboard (rate-limited).

### Per-player events

Only delivered to the affected player.

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

`cells` is the list of `[x, y]` pairs of grid cells that just became the player's zone (both the trail cells and the flood-filled interior). Clients keep an off-view fog-of-war memory; applying this delta is the only way to repaint cells outside the live view window without waiting until the player walks back over them.

#### `died`

```json
{"type": "died", "reason": "trail_cut", "killer": 7, "area_lost": 27}
```

`reason ∈ {trail_cut, out_of_bounds, trapped_in_zone}`.

#### `kill`

```json
{"type": "kill", "victim": 42, "victim_name": "alice", "via": "trail_cut"}
```

Sent to the killer.

#### `respawn`

```json
{"type": "respawn", "x": 811, "y": 226}
```

Sent after `RESPAWN_DELAY` (default 3 s) when the server picks a new free 3×3 spawn square.

#### `pong`

```json
{"type": "pong", "t": 1715900000123, "server_t": 1715900000.456}
```

Reply to a client `ping`. `t` echoes whatever the client sent. The client uses `time.monotonic()` deltas to measure round-trip latency.

---

## 4. Client → server commands

```json
{"cmd": "dir",  "d": "W"}
{"cmd": "ping", "t": 1715900000123}
{"cmd": "quit"}
```

### `dir`

Request a direction change. `d ∈ {"W", "A", "S", "D", "N"}`:

- `W` = up   (y − 1)
- `A` = left (x − 1)
- `S` = down (y + 1)
- `D` = right (x + 1)
- `N` = no direction (still / spawn default)

The server rejects 180° turns and enforces a 1-tick cooldown after every turn.

### `ping`

Round-trip latency check. The server replies with `pong` immediately.

### `quit`

Graceful disconnect. The server pauses the player (zone + trail preserved) and closes the WebSocket. Reconnecting with the same username and a fresh signed `hello` (different `ts`) restores the player — see Section 5.

---

## 5. Reconnect & pause / resume

If the WebSocket drops, the server **does not delete the player** — it puts them on pause:

- zone and trail stay on the map
- motion stops
- a paused player with empty trail is fully invulnerable
- a paused player with non-empty trail can still be killed by trail-cut (otherwise abandoned trails would become impassable barriers)

Reconnecting with the same `username` and a fresh signed `hello` (the `ts` changes, the `sig` re-signs the new `ts`) restores the player's `id`, position, and area.

**Pause timeout:** `PAUSE_TIMEOUT` seconds (default `300`). After that the player is deleted, the pid is freed, and a reconnect creates a brand-new player with new pid and new spawn.

### Takeover

If a connection is open under `username=alice` and a second connection arrives with a valid signed `hello` for the same `alice`, the new connection wins: the old one is closed with `4408 takeover`. This is how you "kick" a forgotten session.

---

## 6. Bot vs human

| Property         | Human (`is_bot=false`) | Bot (`is_bot=true`) |
|------------------|------------------------|---------------------|
| View dims        | `view_w × view_h`      | `(view_w − 2·BOT_HANDICAP) × (view_h − 2·BOT_HANDICAP)` |
| State rate       | `STATE_RATE` (10 Hz)   | same |
| Spectator mode   | available              | rarely useful |
| Score counted    | yes                    | yes |

The handicap exists so that humans aren't outright outclassed by bots with perfect reflexes; bots see a slightly smaller window of the world.

---

## 7. View-only spectators

Setting `is_view=true` on the `hello` frame opens a spectator session. Differences:

- WSAD `dir` commands are ignored.
- The spectator gets a pid in the range `1024..` (separate from real players `1..1023`).
- `follow_rank=N` (1..128) centres the view on the live player currently ranked N on the leaderboard. The view re-anchors every tick if the target moves.
- No `welcome.your_zone` / `welcome.your_trail` (always empty).
- Kills and deaths don't count.

---

## 8. Versioning

Schema changes are additive. Breaking changes will move to `/v2` under a different WebSocket path. The current draft is the implicit `/v1`.

If the server adds new fields, clients should ignore unknown ones. If the server emits message types a client doesn't recognise, the client should drop them silently.

---

## 9. References

- [`tools/login.py`](../tools/login.py) — minimum viable client (hello → ping → pong → close).
- [`client/client.py`](../client/client.py) — full Rich-UI player.
- [`bot.py`](../bot.py) — bot template; `decide(state)` consumes `state` messages directly.
- [`AUTH.md`](AUTH.md) — REST signup flow producing the registered pubkey this protocol verifies against.
- [`RULES.md`](RULES.md) — game mechanics (zones, trails, capture, death).
