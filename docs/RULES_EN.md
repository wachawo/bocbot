# RULES.md — Battle of Code game rules

**[English](https://github.com/battleofcode/bocbot/blob/main/docs/RULES_EN.md)** | [Русский](https://github.com/battleofcode/bocbot/blob/main/docs/RULES_RU.md)

> See also: [AUTH.md](AUTH_EN.md) for signup, [API.md](API_EN.md) for the wire protocol.

This document is the single source of truth for **game mechanics**: the map, how a player moves, how zones and trails work, how captures happen, and how death is decided. If your bot ever does something that contradicts this file, the file wins — file a bug.

---

## 1. Map and coordinates

- The map is a 2D grid of size `MAP_W × MAP_H` cells. Default: **1024 × 768**.
- `(x, y)` coordinates: `x ∈ [0, MAP_W)`, `y ∈ [0, MAP_H)`. `y` grows **downwards**.
- Each cell carries two pieces of state:
  - `zone_owner` — pid of the player who owns this cell as captured territory (`0` = unowned).
  - `trail_owner` — pid of the player whose unclosed trail passes through this cell (`0` = no trail).
- A cell can carry zone and trail at the same time, owned by different players.

---

## 2. Player and movement

- Each player has a position `(x, y)`, a direction (one of the five protocol values `W`/`A`/`S`/`D`/`N` — see [API.md §4](API_EN.md) for the wire format and the [keyboard table in the top-level README](../README.md#playing-manually) for the human controls), a pid, a username, and a colour.
- Movement speed is `SPEED` cells/second (default 5.0). The server ticks at `TICK_RATE = 20 Hz` and the player advances one cell every `1/SPEED` seconds.
- **90°-only turns.** Reversing direction (180°) is forbidden — the server silently drops the command.
- **Turn cooldown.** After each successful turn the player must travel at least one cell before turning again.
- Once a direction is set, the player cannot stop voluntarily. Walking off the map kills them (see Section 7).

---

## 3. Spawn

- A fresh player gets a 3×3 starting zone on a free patch of the map, with the player centred. Initial area = 9.
- On respawn after death, the same rule applies — the server picks a new free 3×3 patch and emits a `respawn` event with the chosen `(x, y)`.

---

## 4. Trail

- While the player is standing on a cell of **their own** zone, the trail does not grow.
- The moment the player steps onto a cell that is **not** part of their zone, that cell becomes their trail and `trail_len` grows by 1. Each successive non-zone cell extends the trail.
- **Crossing your own trail is safe.** You walk through; the length does not grow again on the same cell. (This is a deliberate departure from the classic of the genre — it makes manual play tractable.)
- If any other player steps on a cell of your trail → **you die**. Your trail and uncaptured cells are wiped. The other player keeps moving.

---

## 5. Capture

A player with a non-empty trail closes a loop when they step back onto a cell of **their own** zone. At that moment the server runs the **capture** procedure:

1. All cells of the player's trail become part of their zone.
2. Compute the bounding box of the new zone (zone + just-converted trail).
3. Run a **flood fill** from the edges of that bounding box across cells that are **not** in the player's zone.
4. Any cell inside the bounding box that the flood fill **cannot reach** flips to the player's zone — including cells previously owned by other players.

Side effects of capture:

- **Enemy trail caught inside the captured region** → the trail's owner dies (`reason="captured"`), their trail and uncaptured cells are wiped.
- **Enemy zone caught inside the captured region** → ownership transfers; the original owner does **not** die.
- The capturing player receives a `captured` event listing every cell that just flipped to their zone (`captured.cells`). Clients use this delta to repaint fog-of-war memory outside the live view.

---

## 6. Zone connectivity

After every `capture`, for **every other player** the server runs a BFS from their current position over their zone cells. Any cell of their zone that cannot be reached this way (a stranded "island") is zeroed out, area is recomputed, and `peak_area` is updated.

Invariant: a player's zone is always a single connected region.

---

## 7. Death

| `reason`            | Trigger                                                                            | Killer credited? |
|---------------------|------------------------------------------------------------------------------------|------------------|
| `out_of_bounds`     | Stepping outside `[0, MAP_W) × [0, MAP_H)`. Suicide.                                | No. `deaths` counter is **not** incremented either. |
| `trail_cut`         | Another player stepped on a cell of your trail. The other player keeps moving.      | Yes — the one who stepped on the trail. |
| `captured`          | Your trail ended up inside someone else's capture region during their flood-fill.   | Yes — the capturer. |

Enemy zones are freely walkable — classic paper.io behaviour. There used to be a house rule (`trapped_in_zone`) that killed a player whose entire trail sat inside a single enemy zone; it was removed because it caught honest players far more often than it caught the transit-corridor exploit it was meant to discourage.

**Kill/death balance invariant.** Deaths without an attributable killer (`out_of_bounds`) do not increment the global `total_deaths` counter. This guarantees `sum(kills) == sum(deaths)` across the server.

After death: the player's zone and trail are wiped. After `RESPAWN_DELAY` seconds (default 3) the server picks a new free 3×3 and emits `respawn`. Cumulative `kills`, `deaths`, `total_alive_seconds`, `peak_area` survive the death.

---

## 8. Pause and resume

When a WebSocket connection drops, the server **does not delete the player** — it pauses them:

- `paused = true`, `paused_at = monotonic()`.
- The tick loop skips paused players for movement, but their zone and trail stay on the map.
- A paused player with `trail_len == 0` is **fully invulnerable**.
- A paused player with `trail_len > 0` can still be killed by trail-cut. Otherwise abandoned trails would become impassable barriers.

**Resume.** When a connection arrives with a fresh signed `hello` for the same username, the server restores the paused player: same pid, same `(x, y)`, same zone, same trail, same kills/deaths/area. The `welcome` frame ships the full owned-cell list so the client can repaint fog memory.

**Timeout.** If the pause exceeds `PAUSE_TIMEOUT` seconds (default `300`), the server reaps the player — pid is freed, zone is wiped. A subsequent connect creates a brand-new player with a new pid and a fresh 3×3 spawn.

**Takeover.** If a connection is already open for username `alice` and a second valid signed `hello` for `alice` arrives, the new connection wins: the old one is closed with WebSocket close code `4408 takeover`. This is how you kick a forgotten session.

---

## 9. View and fog of war

- Each player sees a **live view** window of `view_w × view_h` cells centred on themselves (default 41×41 for humans).
- Beyond the live view, the player has **fog memory** of cells they've previously seen. The fog payload is shipped in each `state` frame as a wider `fog_w × fog_h` window (default 123×123) around the player. Trail inside fog is filtered to the recipient pid only — you can see your own trail outside the live view, but never enemy trails.
- **Bot handicap.** Bots get a tighter view: `(view_w − 2·BOT_HANDICAP) × (view_h − 2·BOT_HANDICAP)`. The handicap exists so reflex-perfect bots aren't an outright nightmare for humans.

---

## 10. Spectator mode

Setting `is_view = true` on the `hello` frame opens a spectator session:

- WSAD direction commands are ignored.
- Spectators receive pids in the range `1024..` (separate from real players in `1..1023`).
- `follow_rank = N` (1..128) centres the view on the live player currently ranked N on the leaderboard. The view re-anchors each tick if the target moves.
- The spectator's `welcome.your_zone` and `welcome.your_trail` are empty arrays.
- Kills and deaths do not count for the spectator.

---

## 11. Scoring and dashboard

| Field                  | What it means                                                                |
|------------------------|------------------------------------------------------------------------------|
| `area`                 | Current zone size in cells. **This is your score.**                          |
| `peak_area`            | Maximum area held during the session.                                        |
| `avg_area_1m`          | Mean `area` over the last 60 seconds.                                        |
| `kills`                | Cumulative players killed.                                                   |
| `deaths`               | Cumulative deaths **with an attributable killer** (see Section 7 invariant). |
| `alive_seconds`        | Cumulative time alive.                                                       |
| `alive_human`          | Human-readable formatting: `1h15m` / `22m` / `8s`.                           |

The dashboard panel of the live client shows the top players sorted by `area` descending. The server emits the `scores` list in `state` frames roughly every 5 seconds; in between, the client keeps the cached list.

---

## 12. Hard rules the server enforces

You can write a bot that tries to do any of the following, but the server will silently ignore the bad input or kill you:

- Sending a 180° direction change. Dropped.
- Sending a direction within one tick of the previous turn. Dropped.
- Walking off the map. Death (`out_of_bounds`).
- Submitting an invalid `hello` (skew > 30 s, bad signature, unknown user). Connection closed with code `4401`.
- Reconnecting under another live player's username with a valid signature. Old connection kicked, new one wins (takeover, code `4408`).

---

## 13. Anti-patterns and rules-of-thumb

What to avoid and what to lean on when writing `decide(state)`. These all follow from the rules above; they're collected here because each one corresponds to a specific cause of death or a specific lost opportunity.

**Survival**

- Your zone is safe footing. Your trail outside your zone is exposure.
- Long trails are exponentially riskier — every extra cell is one more place an enemy can cut you.
- Close loops back through your own zone as soon as feasible.
- Don't try to outrun an enemy who is closer to your zone-edge than you are. Speed is the same for everyone — they'll get there first and cut you off. Turn into a different vector.

**Offence**

- Killing an enemy: step on **any cell** of their trail. You don't need to chase the head.
- A player is killable only when `trail_len > 0` (their head is off their own zone). In their own zone they're untouchable.

**Pacing**

- Don't react to every `state` frame. State arrives at 10 Hz; the 1-tick turn-cooldown means the server rejects most rapid direction flips. Decide a destination, then commit to it until reached or invalidated.
- The captured-cells delta is your only way to update memory outside the live view window without revisiting — apply it as soon as the event arrives (see Section 5 and [API.md](API_EN.md) § 3).

---

## 14. Versioning

Game-rule changes are versioned through the protocol — see [API.md](API_EN.md) § 8. Breaking changes will move to `/v2`. Additive changes (new event types, new fields) preserve `/v1`.
