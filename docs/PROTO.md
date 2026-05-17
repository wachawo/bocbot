# PROTO.md — Battle of Code wire protocol

The Battle of Code stack has two endpoints:

- **REST auth API** — HTTP, served by `boc_api` on `:8000`. Used for one-time signup.
- **Realtime game** — WebSocket, served by `boc_server` on `:5555`. Used for joining a game, receiving state, sending direction changes.

All payloads are JSON / UTF-8. Field names are stable; the server tolerates extra fields and clients should tolerate unknown message types.

---

## Identity model

A player is identified by their **GitHub login**. The trust anchor is an Ed25519 keypair:

- **Private key** — 32 raw bytes, stored locally at `keys/<username>.key` (mode `0600`).
- **Public key** — the matching 32 bytes, hex-encoded, committed to `keys/<username>.pub` on a branch named `<username>` in the player's fork of `bocbot`. The server fetches it once at signup time from `https://raw.githubusercontent.com/<username>/bocbot/<username>/keys/<username>.pub`.

After signup the server caches `(username, pubkey)` in its SQLite auth store and never talks to GitHub for that user again. There is no shared secret, no bearer token, no password, no certificate.

---

## REST: signup

Two POST calls, both rate-limited per source IP: **10/hour**, **50/day**. The two-step flow exists because the server must prove the caller actually controls the GitHub-published public key.

### Step 1 — `POST /api/auth/signup`

The server fetches `key.pub` from the GitHub branch, stashes `(pubkey, nonce)` in Redis with a short TTL, and returns the nonce.

Request:

```json
{"username": "alice"}
```

Response 200:

```json
{"status": "challenge", "nonce": "0f1e2d3c4b5a69788796a5b4c3d2e1f0", "ttl": 60}
```

Errors:

| Status | `error`               | When                                                              |
|-------:|-----------------------|-------------------------------------------------------------------|
| 400    | `bad_username`        | empty, reserved (`default`, `admin`, ...), or fails GitHub regex  |
| 404    | `pubkey_fetch_failed` | branch/file not found at the expected URL                         |
| 400    | `pubkey_fetch_failed` | `key.pub` body has no 64-char hex token                           |
| 429    | `rate_limited`        | per-IP cap exceeded                                               |
| 502    | `pubkey_fetch_failed` | GitHub unreachable                                                |

### Step 2 — `POST /api/auth/signup/verify`

The client signs the **raw bytes of the nonce** (the 16 bytes decoded from the hex string) with its Ed25519 private key and submits the hex-encoded signature.

Request:

```json
{"username": "alice", "sig": "abcd1234..."}
```

Response 200:

```json
{"status": "ok", "username": "alice"}
```

Errors:

| Status | `error`         | When                                                       |
|-------:|-----------------|------------------------------------------------------------|
| 400    | `nonce_missing` | no active signup nonce (expired or never issued)           |
| 401    | `bad_signature` | signature does not verify against the stored public key    |
| 500    | `db_error`      | server-side persistence failure                            |

---

## Game: WebSocket

URL: `ws://<host>:<port>/` (the server ignores the path).

### Handshake

The very first frame the client sends must be a `hello`:

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

| Field         | Type      | Notes                                                              |
|---------------|-----------|--------------------------------------------------------------------|
| `username`    | string    | GitHub login (previously registered via REST signup)               |
| `ts`          | int       | Unix seconds. Server rejects skew > 30 s in either direction       |
| `sig`         | string    | hex Ed25519 signature over UTF-8 bytes of `bocbot:hello:<u>:<ts>`  |
| `is_bot`      | bool      | bots get a tighter view window for AI tractability                 |
| `is_view`     | bool      | view-only spectator; WSAD ignored, no kill/death credits           |
| `follow_rank` | int 0-128 | only with `is_view=true`; centres view on the live player at rank  |

The signed string is exactly `bocbot:hello:<username>:<ts>` — no padding, no newline.

On success the server sends `auth_ok` then `welcome`. On failure it sends `auth_error` and closes the WebSocket with code `4401`:

```json
{"type": "auth_error", "reason": "bad_signature", "message": "...", "detail": "..."}
```

`reason ∈ {bad_request, unknown_user, ts_out_of_window, bad_signature}`.

### Server → client messages

#### `auth_ok`

```json
{"type": "auth_ok", "username": "alice"}
```

#### `welcome`

Sent once after `auth_ok`. Tells the client (and bot) the world geometry and ships the player's full owned cell list so a fresh / resumed client can paint its fog-of-war memory before the first `state`.

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

`your_zone` is every grid cell currently owned by the player; `your_trail` is the cells where their unclosed trail still lives. Both are `[x, y]` pairs. For a fresh spawn `your_zone` is the 3×3 starting square; for a resumed paused player it can be hundreds or thousands of cells. Spectators (`is_view=true`) get empty arrays.

#### `state`

Periodic snapshot at `STATE_RATE` (default 10 Hz). The dashboard `scores` array is rate-limited (~once every 5 s); in between, the field is omitted and the client should keep its previous cached list.

```json
{
  "type":       "state",
  "tick":       12345,
  "uptime_sec": 320,
  "me":         {"id": 42, "x": 314, "y": 159, "dir": "D", "alive": true, "area": 27, "trail_len": 0},
  "view":       {"x0": 290, "y0": 140, "w": 41, "h": 41, "zone": [...], "trail": [...]},
  "players":    [...],
  "scores":     [{"pid": 7, "name": "bob", "area": 412, "kills": 3, "deaths": 1}]
}
```

#### Events (only to the affected player)

```json
{"type": "captured", "area_gained": 18, "trail_len": 0, "total_area": 45,
 "cells": [[120, 80], [121, 80], ...]}
{"type": "died",     "reason": "trail_cut", "killer": 7, "area_lost": 27}
{"type": "kill",     "victim": 42, "victim_name": "alice", "via": "trail_cut"}
{"type": "respawn",  "x": 811, "y": 226}
```

`captured.cells` is the list of `[x, y]` pairs of grid cells that just became the player's zone (both the trail cells and the flood-filled interior). Clients keep an off-view fog-of-war memory; applying this delta is the only way to repaint cells outside the live view window without waiting until the player walks back over them.

`reason ∈ {trail_cut, out_of_bounds, trapped_in_zone}`.

### Client → server messages

```json
{"cmd": "dir",  "d": "W"}
{"cmd": "ping", "t": 1715900000123}
{"cmd": "quit"}
```

`d ∈ {"W", "A", "S", "D", "N"}`. Server rejects 180° turns and enforces a 1-tick cooldown after every turn.

Server reply to `ping`:

```json
{"type": "pong", "t": 1715900000123, "server_t": 1715900000.456}
```

---

## Reconnect & pause/resume

If the WebSocket drops, the server **does not delete the player** — it puts them on pause: zone and trail stay on the map, motion stops. Reconnecting with the same `username` and a fresh signed `hello` (the ts changes) restores the player's `id`, position, and area. Pause expires after `PAUSE_TIMEOUT` seconds (default 300).

A paused player with empty trail is fully invulnerable; with non-empty trail the trail can still be crossed and the player killed — otherwise abandoned trails would become impassable barriers.

---

## Versioning

Schema changes are additive. Breaking changes will move to `/v2` under a different WebSocket path. The current draft is the implicit `/v1`.
