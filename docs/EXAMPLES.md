# Examples — cookbook

Short snippets showing common bot patterns. All examples assume the Python SDK:

```python
from bocbot import Bot
```

Look at `bot/example/ai.py` for a fully worked deterministic strategy.

---

## How to avoid walls

TODO: pattern for clamping the chosen direction so the next step stays inside `[0, map_w) × [0, map_h)`.

```python
def decide(self, state):
    you = state["you"]
    # ...
    return "D"
```

---

## How to hunt other players

TODO: pattern for picking a victim from `state["players"]` whose trail you can step on this tick.

Key idea:
- A player is killable when they are off their own zone (their `trail_len > 0`).
- Step onto any cell of their trail to kill them — don't chase the head.
- Avoid head-on collisions: if the enemy can reach your trail in fewer ticks than you can reach theirs, retreat.

---

## How to compute distance

TODO: Manhattan vs BFS, when each is appropriate.

- Manhattan (`abs(dx) + abs(dy)`) — cheap, ignores obstacles, fine for "is this player nearby".
- BFS over the grid — required whenever you care about reachable distance through your own zone vs around someone else's.

---

## How to know when to come home

TODO: rule of thumb tying `trail_len` to `dist_to_home` and the safety margin the example bot uses.

Reference: `bot/example/ai.py` — see `should_return()` and the `RETURN` state branch.

---

## How to read scores

TODO: example using the `scores` message to track a target rival and prioritise stealing their territory.
