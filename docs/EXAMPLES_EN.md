# EXAMPLES.md — bot decision-making cookbook

**[English](https://github.com/battleofcode/bocbot/blob/main/docs/EXAMPLES_EN.md)** | [Русский](https://github.com/battleofcode/bocbot/blob/main/docs/EXAMPLES_RU.md)

> See also: [RULES.md](RULES_EN.md) for game mechanics, [API.md](API_EN.md) for `state` shape, [`bot.py`](../bot.py) for the file you're editing.

Short patterns for `decide(state)`. Everything in this file is meant to be pasted into `bot.py` and adapted — there is no SDK or external library beyond what `bot.py` already imports.

`decide(state)` takes a `state` dict and returns one of `"W" | "A" | "S" | "D" | "N"`. It runs roughly 10 times per second. Keep it fast: no file I/O, no network calls, no slow imports.

---

## How to avoid walls

The next step lands at `(me.x + dx, me.y + dy)`. If that cell is outside `[0, map_w) × [0, map_h)` you die with `reason="out_of_bounds"`. Pick a direction whose next step stays on the map.

```python
DELTAS = {"W": (0, -1), "S": (0, 1), "A": (-1, 0), "D": (1, 0)}

def decide(state):
    me, w, h = state["me"], state["map_w"], state["map_h"]
    cur = me["dir"]
    dx, dy = DELTAS.get(cur, (0, 0))
    nx, ny = me["x"] + dx, me["y"] + dy
    if 0 <= nx < w and 0 <= ny < h:
        return cur
    for d, (dx, dy) in DELTAS.items():
        if 0 <= me["x"] + dx < w and 0 <= me["y"] + dy < h:
            return d
    return "N"
```

`state["map_w"]` and `state["map_h"]` come from the `welcome` frame the wrapper stored before the first `state`.

---

## How to hunt other players

A player is killable when they have `trail_len > 0` (their head is off their own zone). Stepping onto **any cell** of their trail kills them. You don't need to chase the head.

`state["view"].trail` is the trail grid for the view window. Find an enemy trail cell adjacent to you and step onto it.

```python
def decide(state):
    me = state["me"]
    view = state["view"]
    trail = view["trail"]
    h, w = len(trail), len(trail[0])
    for d, (dx, dy) in DELTAS.items():
        nx, ny = me["x"] - view["x0"] + dx, me["y"] - view["y0"] + dy
        if 0 <= nx < w and 0 <= ny < h:
            owner = trail[ny][nx]
            if owner != 0 and owner != me["id"]:
                return d
    return me["dir"] or "D"
```

Avoid head-on collisions: if the enemy can reach **your** trail in fewer ticks than you can reach theirs, retreat. A simple Manhattan check is usually enough — see "distance" below.

---

## How to compute distance

- **Manhattan** (`abs(dx) + abs(dy)`) — cheap, ignores obstacles. Good for "is this player nearby" or "which of these is closer".
- **Chebyshev** (`max(abs(dx), abs(dy))`) — useful when you care about vision range (the view is a square centred on you).
- **BFS** over the grid — needed only when you care about *reachable* distance through your own zone vs around someone else's.

```python
def manhattan(ax, ay, bx, by):
    return abs(ax - bx) + abs(ay - by)
```

The view is `view_w × view_h` cells (default 41×41). BFS inside it is cheap — well under a millisecond. BFS over the full map (1024×768 ≈ 786 K cells) is not — keep it inside the view unless you really need long-range reachability.

---

## How to know when to come home

Two heuristics, ranked by simplicity:

1. **Trail-length cap.** If `me.trail_len > MAX_TRAIL`, head back to your zone. `MAX_TRAIL = 80` is a reasonable start.
2. **Distance budget.** Compute Manhattan distance from your head to the nearest cell of your own zone. If that distance ≥ remaining-survival-budget, head back. The "budget" depends on how close the nearest enemy is and how many cells of *your* trail they could reach before you reach *your* zone.

The starter bot in `bot.py` uses the trail-length cap because it's easy to reason about. Replace it with a distance-budget rule once you've watched a few losses.

---

## How to read scores

`state["scores"]` is a list of dicts when the server sends it (about every 5 seconds; in between the field is absent or the same object). Each dict has `pid`, `name`, `area`, `kills`, `deaths`.

```python
def top_rival(state, me_pid):
    scores = state.get("scores") or []
    others = [s for s in scores if s["pid"] != me_pid]
    if not others:
        return None
    others.sort(key=lambda s: -s["area"])
    return others[0]
```

Use this to prioritise a target — if the leader's zone borders yours, biting into them is worth more than capturing empty space.

---

## How to apply the `captured` event for fog memory

The wrapper in `bot.py` already handles this, but worth knowing what it does:

`captured.cells` is the list of `[x, y]` pairs that just flipped to your zone (trail cells + flood-filled interior). The client paints them into its fog-of-war memory so cells outside the live view are still coloured correctly. If you build your own memory map inside `decide`, apply this delta the moment the event arrives.

---

## Anti-patterns

- **Laying a long trail entirely inside one enemy zone.** This is the most-missed death — `trapped_in_zone` (see [RULES.md](RULES_EN.md) § 7). Walk along the *edge* of the enemy zone, or thread through several different zones, but never inside a single one.
- **Reacting to every state frame.** State arrives at 10 Hz. If you change direction every tick, the 1-tick cooldown means the server rejects most of them, and you look like you're stuttering. Decide a destination, then commit until it's reached or invalidated.
- **Trying to outrun a closer enemy.** Speed is the same for everyone. If they're closer to your zone-edge than you are, you can't outrun them — turn into a different vector before they cut you off.

---

## Where the bot template imports live

`bot.py` imports:

- `cryptography` — for the `hello` signature.
- `websockets` — for the WebSocket transport.
- `os`, `time`, `json`, `traceback` — stdlib.

There is no `bocbot` package, no `from bocbot import Bot`, no SDK. The whole bot is the file in front of you.
