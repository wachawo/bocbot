#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rich-based renderer for Battle of Code: header + map + dashboard + footer."""

import time
from typing import Any, Deque, Dict, List, Optional, Tuple
from collections import deque

from rich.console import Console, Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align

# Player-zone background palette. Index = (owner_id - 1) % 16.
# Using explicit 256-colour indices (NOT ANSI names like "red"): different
# terminal themes redefine the 16-colour ANSI palette wildly — one user's
# "red" is a pinkish scarlet, another's is a deep brick. 256-colour indices
# are pinned to the xterm RGB cube and render identically across themes.
#
# BG_PALETTE = the SATURATED in-view colour (cube row 4-5: bold, vivid).
# DIM_PALETTE = the PALE in-fog colour (cube row 1-2: washed-out / pastel).
# The pale variant is intentionally LIGHTER, not darker — fog-of-war is
# "faded memory", not "deep shadow". Players read the contrast as
# "saturated = I see it right now, pastel = I remember it being there".
BG_PALETTE: List[str] = [
    "color(160)",  # deep red       #D70000
    "color(34)",   # deep green     #00AF00
    "color(178)",  # deep yellow    #D7AF00
    "color(20)",   # deep blue      #0000D7
    "color(127)",  # deep magenta   #AF00AF
    "color(37)",   # deep cyan      #00AFAF
    "color(7)",    # white-ish
    "color(196)",  # vivid red      #FF0000  (alt for pid 8)
    "color(46)",   # vivid green
    "color(190)",  # vivid yellow
    "color(33)",   # vivid blue
    "color(165)",  # vivid magenta
    "color(51)",   # vivid cyan
    "color(15)",   # vivid white
    "color(208)",  # orange
    "color(201)",  # pink/violet
]

DIM_PALETTE: List[str] = [
    "color(52)",   # dim red       #5F0000  (darker hue of c160 red)
    "color(22)",   # dim green     #005F00
    "color(58)",   # dim yellow    #5F5F00
    "color(17)",   # dim blue      #00005F
    "color(53)",   # dim magenta   #5F005F
    "color(23)",   # dim cyan      #005F5F
    "color(244)",  # dim white-ish
    "color(88)",   # dim vivid_red #870000
    "color(28)",   # dim vivid_green
    "color(100)",  # dim vivid_yellow
    "color(19)",   # dim vivid_blue
    "color(89)",   # dim vivid_magenta
    "color(30)",   # dim vivid_cyan
    "color(250)",  # dim vivid_white
    "color(130)",  # dim orange
    "color(89)",   # dim pink/violet
]

# Bright colors where black foreground contrasts better; others use white.
LIGHT_BG_INDICES = {1, 2, 6, 7, 8, 9, 10, 12, 13}

# Footer event ring buffer
EVENT_RING_MAX = 4


def bg_for(owner_id: int, trail: bool = False) -> Optional[str]:
    """Return rich color name for a given owner id (None = empty).

    `trail=True` is kept for compatibility; trail cells share the zone color
    of their owner. The semi-transparent look is achieved by combining the
    same bg with a `dim` style at the render call site, not by switching
    palettes.
    """
    if owner_id <= 0:
        return None
    idx = (owner_id - 1) % 16
    return BG_PALETTE[idx]


def dim_bg_for(owner_id: int) -> Optional[str]:
    """Darker variant of `bg_for(owner_id)` — used to fade OWN cells that
    are outside the live view."""
    if owner_id <= 0:
        return None
    idx = (owner_id - 1) % 16
    return DIM_PALETTE[idx]


def fg_on(owner_id: int) -> str:
    """Foreground contrasting with the bg palette."""
    if owner_id <= 0:
        return "default"
    idx = (owner_id - 1) % 16
    if idx in LIGHT_BG_INDICES:
        return "black"
    return "bright_white"


class RenderState:
    """Holds rolling event ring for the footer."""

    def __init__(self) -> None:
        self.events: Deque[Tuple[str, float]] = deque(maxlen=EVENT_RING_MAX)

    def push_event(self, msg: str, ttl: float = 4.0) -> None:
        self.events.append((msg, time.monotonic() + ttl))

    def visible_events(self) -> List[str]:
        now = time.monotonic()
        return [m for (m, exp) in self.events if exp > now]


class MemoryMap:
    """Fog-of-war buffer.

    The client receives small server views (41×41); we keep everything we've
    seen so the screen can show terrain that's no longer in the live view as
    a dim "from memory" overlay. This way the player can see they're moving
    (zones drift off-screen behind them) even when the area ahead is empty.

    `zone` / `trail` are flat lists of length map_w * map_h (owner ids, 0 =
    never seen). `seen` marks any cell whose memory should be drawn — zeros
    mean we've never looked at this cell.
    """

    def __init__(self) -> None:
        self.map_w: int = 0
        self.map_h: int = 0
        self.zone: List[int] = []
        self.trail: List[int] = []
        self.seen: bytearray = bytearray()

    def resize(self, map_w: int, map_h: int) -> None:
        n = map_w * map_h
        self.map_w = map_w
        self.map_h = map_h
        self.zone = [0] * n
        self.trail = [0] * n
        self.seen = bytearray(n)

    def update_from_view(self, view: Dict[str, Any]) -> None:
        if self.map_w == 0:
            return
        x0 = int(view.get("x0", 0))
        y0 = int(view.get("y0", 0))
        w = int(view.get("w", 0))
        h = int(view.get("h", 0))
        zone_rows: List[List[int]] = view.get("zone") or []
        trail_rows: List[List[int]] = view.get("trail") or []
        for vy in range(h):
            y = y0 + vy
            if y < 0 or y >= self.map_h:
                continue
            zrow = zone_rows[vy] if vy < len(zone_rows) else []
            trow = trail_rows[vy] if vy < len(trail_rows) else []
            base = y * self.map_w
            for vx in range(w):
                x = x0 + vx
                if x < 0 or x >= self.map_w:
                    continue
                z = zrow[vx] if vx < len(zrow) else 0
                t = trow[vx] if vx < len(trow) else 0
                self.zone[base + x] = z
                self.trail[base + x] = t
                self.seen[base + x] = 1

    def update_from_fog(self, fog: Dict[str, Any]) -> None:
        """Apply the server's wider context window (state.fog).

        Fog covers ``fog_w × fog_h`` cells centred on the player. The
        server ships zone (any owner) AND trail (filtered to OWN pid
        only — enemy trails stay invisible outside the live view).

        This overwrites both fields in memory: zone is authoritative
        from the server; trail is authoritative for own-trail and zero
        elsewhere. Apply BEFORE ``update_from_view`` so that for cells
        in the live view the richer (full-trail) view data wins.
        """
        if self.map_w == 0:
            return
        x0 = int(fog.get("x0", 0))
        y0 = int(fog.get("y0", 0))
        w = int(fog.get("w", 0))
        h = int(fog.get("h", 0))
        zone_rows: List[List[int]] = fog.get("zone") or []
        trail_rows: List[List[int]] = fog.get("trail") or []
        mw = self.map_w
        mh = self.map_h
        for ry in range(h):
            wy = y0 + ry
            if wy < 0 or wy >= mh:
                continue
            if ry >= len(zone_rows):
                break
            zrow = zone_rows[ry]
            trow = trail_rows[ry] if ry < len(trail_rows) else []
            base = wy * mw
            for rx in range(min(w, len(zrow))):
                wx = x0 + rx
                if wx < 0 or wx >= mw:
                    continue
                z = zrow[rx]
                if z < 0:                       # out-of-map marker
                    continue
                self.zone[base + wx] = z
                self.trail[base + wx] = trow[rx] if rx < len(trow) else 0
                self.seen[base + wx] = 1

    def commit_capture(self, pid: int, cells: Optional[List[Any]] = None) -> None:
        """Apply a capture delta to local memory.

        Preferred form: server ships ``cells`` — a list of ``[x, y]`` pairs
        for every grid cell that just became ``pid``'s zone. We mark each
        as zone=pid, trail=0, seen=1. This covers BOTH the trail and the
        enclosed interior, even cells the player never saw before.

        Fallback (legacy capture events without a delta): walk memory and
        rewrite ``trail == pid`` into ``zone == pid``. Catches the trail
        but not the polygon interior.
        """
        if self.map_w == 0 or pid <= 0:
            return
        if cells:
            mw = self.map_w
            mh = self.map_h
            for cell in cells:
                try:
                    x = int(cell[0])
                    y = int(cell[1])
                except Exception:
                    continue
                if 0 <= x < mw and 0 <= y < mh:
                    i = y * mw + x
                    self.zone[i] = pid
                    self.trail[i] = 0
                    self.seen[i] = 1
            return
        n = self.map_w * self.map_h
        for i in range(n):
            if self.trail[i] == pid:
                self.trail[i] = 0
                self.zone[i] = pid


def make_console() -> Console:
    """Build a rich Console attached to stdout."""
    return Console()


def build_header(me: Dict[str, Any], name: str,
                 scores: Optional[List[Dict[str, Any]]] = None,
                 server_uptime_sec: int = 0,
                 connection: str = "connected",
                 latency_ms: int = -1) -> Panel:
    """Top panel with player metrics + server uptime + connection status.

    Layout: player summary on the left, server status on the right.

    Columns (same order as the dashboard table for muscle memory):
        area · trail · total · a/min · k · d · k/d · ttl · conn · dir
    """
    my_id = int(me.get("id", 0))
    area = int(me.get("area", 0))
    trail_len = int(me.get("trail_len", 0))
    direction = str(me.get("dir", "N"))
    alive = bool(me.get("alive", True))

    # Per-player aggregate metrics live in `scores`; me only carries the
    # tick-level fields. Look up our row by id.
    my_score = None
    for s in (scores or []):
        if int(s.get("id", 0)) == my_id:
            my_score = s
            break

    total_captured = int(my_score.get("total_captured", 0)) if my_score else 0
    if my_score and "avg_area_1h" in my_score:
        a_per_min = float(my_score.get("avg_area_1h", 0.0))
    else:
        alive_sec = float(my_score.get("alive_seconds", 0.0)) if my_score else 0.0
        a_per_min = max(0, area - 9) * 60.0 / alive_sec if alive_sec > 1.0 else 0.0
    kills_full = int(my_score.get("kills", me.get("kills", 0))) if my_score else int(me.get("kills", 0))
    deaths_full = int(my_score.get("deaths", me.get("deaths", 0))) if my_score else int(me.get("deaths", 0))
    kd = kills_full / deaths_full if deaths_full > 0 else float(kills_full)
    alive_sec = float(my_score.get("alive_seconds", 0.0)) if my_score else 0.0
    conn_sec = float(my_score.get("conn_seconds", 0.0)) if my_score else 0.0

    swatch = Text("  ", style=f"on {bg_for(my_id) or 'default'}") if my_id > 0 else Text("  ")

    spectating = bool(me.get("spectating", False))
    follow_rank = int(me.get("follow_rank", 0))

    left = Text()
    if spectating:
        left.append("spectating ", style="bold yellow")
        left.append(f"rank #{follow_rank}: ", style="bold bright_yellow")
        left.append(f"following #{my_id} ", style="bold bright_white")
    else:
        left.append("you: ", style="bold")
        left.append(f"{name} ", style="bold bright_white")
        left.append(f"(#{my_id}) ", style="dim")
    left.append("  ")
    left.append_text(swatch)
    left.append("  trail=", style="dim")
    left.append(f"{trail_len:,}", style="bold yellow")
    left.append("  area=", style="dim")
    left.append(f"{area:,}", style="bold cyan")
    left.append("  total=", style="dim")
    left.append(f"{total_captured:,}", style="bold bright_cyan")
    left.append("  a/min=", style="dim")
    left.append(f"{a_per_min:,.1f}", style="bold bright_cyan")
    left.append("  k=", style="dim")
    left.append(f"{kills_full}", style="bold green")
    left.append("  d=", style="dim")
    left.append(f"{deaths_full}", style="bold red")
    left.append("  k/d=", style="dim")
    left.append(f"{kd:.1f}", style="bold bright_green" if kd >= 1 else "yellow")
    left.append("  ttl=", style="dim")
    left.append(format_uptime(int(alive_sec)) if alive else "—",
                style="dim bright_white")
    left.append("  conn=", style="dim")
    left.append(format_uptime(int(conn_sec)) if conn_sec > 0 else "—",
                style="dim bright_white")
    left.append("  dir=", style="dim")
    left.append(f"{direction}", style="bold magenta")
    if not alive:
        left.append("  [DEAD]", style="bold red on yellow")

    right = Text()
    right.append("up ", style="dim")
    right.append(format_uptime(int(server_uptime_sec)), style="bold bright_cyan")
    right.append("  ")
    if connection == "connected":
        right.append("● Online", style="green")
        if latency_ms >= 0:
            right.append(f" ({latency_ms}ms)", style="dim green")
    elif connection == "reconnecting":
        right.append("● Offline", style="red")
    else:
        right.append(f"● {connection.capitalize()}", style="red")

    # Two-column layout: player metrics flex-left, server status right-justified.
    bar = Table.grid(expand=True)
    bar.add_column(justify="left",  ratio=1)
    bar.add_column(justify="right", no_wrap=True)
    bar.add_row(left, right)
    return Panel(bar, border_style="bright_blue", padding=(0, 1))


# Cache the most recently built map panel keyed on object identity of the
# server-state dicts. `last_view is view` is True only when the caller
# passes the SAME dict (which client.py does: it stores `last_view = msg["view"]`
# and only replaces it on a new state message). Rebuilding the panel costs
# 10-40 ms on a 200×100 view — caching halves CPU when refresh_per_second
# pings come faster than state messages arrive.
_MAP_CACHE: Dict[str, Any] = {"key": None, "panel": None}


def build_map(
    me: Dict[str, Any],
    view: Dict[str, Any],
    players: List[Dict[str, Any]],
    pack_x: int = 1,
    pack_y: Optional[int] = None,
    cell_w: int = 1,
    cell_h: int = 1,
    map_w: int = 0,
    map_h: int = 0,
    memory: Optional[MemoryMap] = None,
    screen_cells_w: int = 0,
    screen_cells_h: int = 0,
) -> Panel:
    """Build map panel.

    pack_x / pack_y — number of *cells* folded into one screen character.
    cell_w / cell_h — number of *screen characters* each pack-block expands to
    on screen.

    When `memory` and `screen_cells_w/h` are provided, the rendered window
    spans `screen_cells_*` cells around the player and the renderer pulls
    terrain from memory. Cells inside the current `view` rectangle are drawn
    bright; cells outside are dim ("fog of war" — terrain we've seen
    before). Cells never visited are blank. Without memory the renderer
    falls back to the legacy view-only rendering.
    """
    x0 = int(view.get("x0", 0))
    y0 = int(view.get("y0", 0))
    w = int(view.get("w", 0))
    h = int(view.get("h", 0))
    pack_x = max(1, int(pack_x))
    pack_y = max(1, int(pack_y)) if pack_y is not None else 2 * pack_x
    cell_w = max(1, int(cell_w))
    cell_h = max(1, int(cell_h))
    use_memory = (memory is not None and memory.map_w > 0
                  and screen_cells_w > 0 and screen_cells_h > 0)

    # Window in world coordinates. Memory mode: centred on the player and
    # sized by `screen_cells_*`. Legacy mode: the server view rectangle.
    if use_memory:
        me_x = int(me.get("x", 0))
        me_y = int(me.get("y", 0))
        scr_w = min(screen_cells_w, memory.map_w + 4)
        scr_h = min(screen_cells_h, memory.map_h + 4)
        # Cap the rendered window to the 3×view fog ring — anything
        # beyond that is empty memory the server hasn't refreshed in
        # the latest tick anyway. Wider terminals stop growing the
        # square once it reaches the fog payload size.
        view_w_render = int(view.get("w", 0))
        view_h_render = int(view.get("h", 0))
        if view_w_render > 0:
            scr_w = min(scr_w, view_w_render * 3)
        if view_h_render > 0:
            scr_h = min(scr_h, view_h_render * 3)
        # Clamp to packs.
        scr_w = max(pack_x, (scr_w // pack_x) * pack_x)
        scr_h = max(pack_y, (scr_h // pack_y) * pack_y)
        win_x0 = me_x - scr_w // 2
        win_y0 = me_y - scr_h // 2
        # No snap: player stays exactly centred, the viewport shifts by 1
        # cell per 1 cell of motion → smooth half-char sliding with the
        # half-block renderer, no integer-char "jumps" every 2 steps.
        win_w = scr_w
        win_h = scr_h
        zone_arr: List[int] = memory.zone
        trail_arr: List[int] = memory.trail
        seen_arr: bytearray = memory.seen
        mw = memory.map_w
    else:
        win_x0 = x0
        win_y0 = y0
        win_w = w
        win_h = h
        # legacy: 2D rows from the view object
        zone_legacy: List[List[int]] = view.get("zone", []) or []
        trail_legacy: List[List[int]] = view.get("trail", []) or []
        mw = 0

    # Cache key: include the player position + view geometry so memory
    # updates and motion both bust the cache.
    cache_key = (
        id(view), id(players), id(me),
        int(me.get("x", 0)), int(me.get("y", 0)), int(me.get("trail_len", 0)),
        bool(me.get("alive", True)),
        pack_x, pack_y, cell_w, cell_h,
        win_x0, win_y0, win_w, win_h, use_memory,
        memory.map_w if memory else 0,
        memory.map_h if memory else 0,
    )
    if _MAP_CACHE.get("key") == cache_key and _MAP_CACHE.get("panel") is not None:
        return _MAP_CACHE["panel"]

    # Player markers — only those whose world coord lands in our window.
    pmap: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for p in players:
        px = int(p.get("x", -1))
        py = int(p.get("y", -1))
        if win_x0 <= px < win_x0 + win_w and win_y0 <= py < win_y0 + win_h:
            pmap[(px, py)] = p

    my_x = int(me.get("x", -1))
    my_y = int(me.get("y", -1))
    my_pid = int(me.get("id", 0))

    # Distance-based fog dim. Live view ≈ ±20 cells; the fog payload from
    # the server covers a 3× window (≈ ±60). We map Chebyshev distance to
    # 3 dim levels so the colour visibly fades as zones drift away from
    # the player toward the screen edge instead of all sitting at one
    # uniform grey.
    view_half_w = max(1, w // 2)
    view_half_h = max(1, h // 2)
    fog_step_1 = max(view_half_w, view_half_h)                 # just outside view
    fog_step_2 = fog_step_1 + max(8, fog_step_1 // 2)          # mid-fog
    # Beyond fog_step_2 → deepest dim.

    # Helper: is world cell currently inside the live view rectangle?
    def in_view(wx: int, wy: int) -> bool:
        return x0 <= wx < x0 + w and y0 <= wy < y0 + h

    # Per-cell sample — pulls (zone_owner, trail_owner, has_me, enemy_pid,
    # in_view, seen, is_wall) for ONE world cell (wx, wy). enemy_pid is the
    # pid of any *other* player standing on this cell (0 = none) so the
    # renderer can colour their `×` marker with their own zone palette.
    def sample(wx: int, wy: int):
        is_wall = False
        if wx < 0 or wy < 0:
            is_wall = True
        elif map_w > 0 and wx >= map_w:
            is_wall = True
        elif map_h > 0 and wy >= map_h:
            is_wall = True
        zone_owner = 0
        trail_owner = 0
        seen = False
        if not is_wall:
            if use_memory:
                midx = wy * mw + wx
                if seen_arr[midx]:
                    seen = True
                    zone_owner = zone_arr[midx]
                    trail_owner = trail_arr[midx]
            else:
                vx = wx - x0
                vy = wy - y0
                if 0 <= vy < len(zone_legacy):
                    row = zone_legacy[vy]
                    if 0 <= vx < len(row):
                        zone_owner = row[vx]
                if 0 <= vy < len(trail_legacy):
                    row = trail_legacy[vy]
                    if 0 <= vx < len(row):
                        trail_owner = row[vx]
                seen = True
        cell_has_me = (wx == my_x and wy == my_y) and not is_wall
        enemy_pid = 0
        if not cell_has_me and (wx, wy) in pmap:
            enemy_pid = int(pmap[(wx, wy)].get("id", 0))
        cell_in_view = in_view(wx, wy)
        return zone_owner, trail_owner, cell_has_me, enemy_pid, cell_in_view, seen, is_wall

    # Per-half style: take a sample tuple, return (zone_bg_color_or_None,
    # marker_glyph_or_None, trail_owner_pid). zone_bg is the half's
    # background colour (zone fill or fog-dim grey or wall grey or None);
    # marker is "@" / "O" / "·" if a special glyph should fill the whole
    # char (markers always override the half-block ▀). trail_owner_pid is
    # carried out separately so render_char can pick the trail's fg colour.
    #
    # `char_in_view` is the OR of both halves' in_view flags. We use the
    # char-level signal (not the per-cell one) for fog-dimming so a char
    # that straddles the live-view boundary doesn't render one half bright
    # and the other dim — the player would see a "half-transparent square
    # right next to me" artefact instead of a clean view boundary.
    def half_style(samp, char_in_view: bool, dist: int):
        z, t, me_, en_pid, iv, sn, wall = samp
        if wall:
            return "grey50", None, 0
        if not sn and use_memory:
            return None, None, 0
        col: Optional[str] = bg_for(z) if z > 0 else None
        owned = (z > 0 and z == my_pid) or (t > 0 and t == my_pid)
        if use_memory and not char_in_view and not me_:
            if owned:
                # Own zone outside view: use the dim version of our own
                # palette colour so it visibly differs from the bright
                # red inside the live view (player can tell at a glance
                # what's currently visible vs only remembered).
                if col is not None:
                    col = dim_bg_for(my_pid)
            elif col is not None:
                # Graduated grey for foreign zones in fog.
                if dist <= fog_step_1:
                    col = "color(237)"   # grey ~23%
                elif dist <= fog_step_2:
                    col = "color(235)"   # grey ~15%
                else:
                    col = "color(233)"   # grey ~7%
        # LIVE VIEW = the BRIGHT region: empty in-view cells get a
        # noticeably light backdrop (color 238 ≈ grey ~30%) so the
        # view rectangle is the "illuminated" zone, like a spotlight.
        # FOG ring = the DIM region: stays at terminal default. The
        # contrast between them must be obvious; using close shades
        # (234 vs default) had users perceiving them as the same.
        if col is None and iv and not wall:
            col = "color(238)"
        marker: Optional[str] = None
        if me_:
            marker = "ME"          # internal token; rendered as `×` bright_white
        elif en_pid > 0:
            marker = "EN"          # internal token; rendered as `×` enemy-coloured
        elif t > 0 and t != z and (char_in_view or owned):
            # `·` for trails. Server clears trail on closed-loop capture,
            # so trail inside own zone is naturally absent — and that's
            # the correct visual: the moment you close, your home is
            # blank again. No client-side ghost-tracking.
            marker = "·"
        # Carry whichever pid drives the marker colour so render_char can
        # pick it up without re-sampling.
        marker_pid = en_pid if marker == "EN" else t
        return col, marker, marker_pid

    def render_char(upper_samp, lower_samp, wx_here: int, upper_y: int, lower_y: int):
        char_in_view = upper_samp[4] or lower_samp[4]
        # Chebyshev distance from player to the char (closer of the two halves).
        dx = abs(wx_here - my_x)
        dy = min(abs(upper_y - my_y), abs(lower_y - my_y))
        dist = max(dx, dy)
        u_col, u_marker, u_trail = half_style(upper_samp, char_in_view, dist)
        l_col, l_marker, l_trail = half_style(lower_samp, char_in_view, dist)
        if u_marker is not None or l_marker is not None:
            order = {"ME": 0, "EN": 1, "·": 2}
            if u_marker is not None and l_marker is not None:
                token, side = (u_marker, "u") if order[u_marker] <= order[l_marker] else (l_marker, "l")
            elif u_marker is not None:
                token, side = u_marker, "u"
            else:
                token, side = l_marker, "l"
            pid_here = u_trail if side == "u" else l_trail
            if token == "ME":
                # `×` (U+00D7) — diagonal cross, narrow (A-width, renders
                # as 1 cell in mainstream monospace fonts). The smiley
                # alternative ㋡ is East-Asian Wide → spawn rows ended up
                # 1 column out of phase, breaking the rectangle shape.
                ch, fg = "×", "bright_white"
            elif token == "EN":
                ch, fg = "×", (bg_for(pid_here) or "bright_white")
            else:                                       # trail
                ch, fg = "·", (bg_for(pid_here) or "white")
            bg = u_col if side == "u" else l_col
            if bg is None:
                bg = u_col if u_col is not None else l_col
            return ch, fg, bg
        # No markers — collapse halves to one solid colour where possible.
        FLOOR = "color(234)"   # the empty-but-in-view backdrop
        if u_col is None and l_col is None:
            return " ", "default", None
        if u_col is not None and l_col is not None:
            if u_col == l_col:
                return " ", "default", u_col          # solid same-colour fill
            # Treat "view floor" as transparent for over-paint purposes:
            # if the other half has a real zone colour, over-paint the
            # floor side with the zone colour. This keeps a 3×3 spawn as
            # a uniform 2-char × 3-char rectangle instead of a half-block
            # silhouette at its edges.
            if u_col == FLOOR and l_col != FLOOR:
                return " ", "default", l_col
            if l_col == FLOOR and u_col != FLOOR:
                return " ", "default", u_col
            return "▀", u_col, l_col                  # honest two-tone (two zones)
        # One half missing entirely (no zone, no seen): use the existing
        # half-block glyph so the edge of the rendered window stays sharp.
        if u_col is not None:
            return "▀", u_col, None
        return "▄", l_col, None

    rows: List[Text] = []
    for ry in range(0, win_h, pack_y):
        line = Text(no_wrap=True, overflow="crop")
        run_ch: str = ""
        run_style: str = ""
        run_len: int = 0
        upper_y = win_y0 + ry
        lower_y = win_y0 + ry + 1 if pack_y > 1 else upper_y
        for rx in range(0, win_w, pack_x):
            wx = win_x0 + rx
            upper_samp = sample(wx, upper_y)
            lower_samp = sample(wx, lower_y) if pack_y > 1 else upper_samp
            ch, fg, bg = render_char(upper_samp, lower_samp, wx, upper_y, lower_y)
            style = fg if bg is None else f"{fg} on {bg}"
            if ch == run_ch and style == run_style:
                run_len += cell_w
            else:
                if run_len > 0:
                    line.append(run_ch * run_len, style=run_style)
                run_ch = ch
                run_style = style
                run_len = cell_w
        if run_len > 0:
            line.append(run_ch * run_len, style=run_style)
        # Replicate the line cell_h times vertically (currently always 1).
        for _ in range(cell_h):
            rows.append(line)

    if not rows:
        rows.append(Text("(waiting for state...)", style="dim"))

    # Coordinate rulers along the panel's left and bottom edges. Origin
    # (0, 0) is the centre of the world map. Y labels are prepended to
    # each map row inline (Rich's Table.grid silently truncated a
    # separate column to "…" when the map cell dominated the row); the
    # X label is appended as the final row.
    Y_TICK = 5
    X_TICK = 10
    LABEL_W = 5            # max " -384" / "+1000" width
    sep = " "              # 1-char gap between Y label and map content
    labelled_rows: List[Text] = []
    for r_idx, row in enumerate(rows):
        wy_world = win_y0 + r_idx * pack_y
        wy = wy_world - (map_h // 2 if map_h > 0 else 0)
        prefix = Text()
        if r_idx % Y_TICK == 0:
            prefix.append(f"{wy:+{LABEL_W}d}", style="bright_blue")
        else:
            prefix.append(" " * LABEL_W)
        prefix.append(sep)
        combined = Text(no_wrap=True, overflow="crop")
        combined.append_text(prefix)
        combined.append_text(row)
        labelled_rows.append(combined)

    char_cols = max(1, win_w // pack_x)
    x_label = Text(" " * (LABEL_W + len(sep)))   # align under the map content
    for c in range(char_cols):
        wx_world = win_x0 + c * pack_x
        wx = wx_world - (map_w // 2 if map_w > 0 else 0)
        if c % X_TICK == 0:
            s = f"{wx:+d}"
            x_label.append(s, style="bright_blue")
            pad = X_TICK * cell_w - len(s)
            if pad > 0:
                x_label.append(" " * pad)

    body = Align.center(Group(*labelled_rows, x_label), vertical="middle")
    if pack_x == 1 and pack_y == 1 and cell_w == 1 and cell_h == 1:
        title = "map"
    else:
        title = f"map (pack {pack_x}×{pack_y} cell {cell_w}×{cell_h})"
    panel = Panel(body, border_style="bright_blue", padding=(0, 0), title=title)
    _MAP_CACHE["key"] = cache_key
    _MAP_CACHE["panel"] = panel
    return panel


def build_dashboard(
    scores: List[Dict[str, Any]],
    my_id: int,
    server_uptime_sec: int = 0,
    connection: str = "connected",
) -> Panel:
    """Dashboard panel: top-N players + server uptime row at the bottom.

    Compact 3-column table (name / area / k-d) — roughly 1/3 the width of
    the legacy six-column layout, fits a thin right-hand strip next to the
    map. The uptime + connection-status footer lives *inside* this panel
    (not in the screen footer) so it stays right where the user looks for
    the leaderboard.
    """
    top = sorted(scores or [], key=lambda s: int(s.get("area", 0)), reverse=True)

    table = Table(show_header=True, header_style="bold bright_blue",
                  box=None, padding=(0, 0), expand=True)
    table.add_column("name",  min_width=8, no_wrap=True, overflow="ellipsis")
    table.add_column("area",  justify="right", width=6)
    table.add_column("total", justify="right", width=7)
    table.add_column("a/min", justify="right", width=7)
    table.add_column("k",     justify="right", width=4)
    table.add_column("d",     justify="right", width=4)
    table.add_column("k/d",   justify="right", width=5)
    table.add_column("ttl",   justify="right", width=7)
    table.add_column("conn",  justify="right", width=7)

    for s in top:
        sid = int(s.get("id", 0))
        sname = str(s.get("name", "?"))
        sarea = int(s.get("area", 0))
        skills = int(s.get("kills", 0))
        sdeaths = int(s.get("deaths", 0))
        s_alive = bool(s.get("alive", True))
        s_paused = bool(s.get("paused", False))
        alive_sec = float(s.get("alive_seconds", 0.0))
        # a/min = server-computed net rate over the past hour (captures minus
        # death-losses, divided by effective window). Falls back to per-life
        # for older servers.
        if "avg_area_1h" in s:
            area_per_min = float(s.get("avg_area_1h", 0.0))
        else:
            area_per_min = max(0, sarea - 9) * 60.0 / alive_sec if alive_sec > 1.0 else 0.0
        kd = skills / sdeaths if sdeaths > 0 else float(skills)
        bg = bg_for(sid) or "default"
        name_color = bg if bg != "default" else "white"
        if sid == my_id:
            name_text = Text(f">{sname}", style=f"bold {name_color}")
        elif not s_alive:
            name_text = Text(sname + " (dead)", style="dim grey50")
        elif s_paused:
            name_text = Text(sname + " (paused)", style=f"italic {name_color}")
        else:
            name_text = Text(sname, style=name_color)
        ttl_text = format_uptime(int(alive_sec)) if s_alive else "—"
        total_captured = int(s.get("total_captured", 0))
        conn_sec = float(s.get("conn_seconds", 0.0))
        conn_text = format_uptime(int(conn_sec)) if conn_sec > 0 else "—"
        table.add_row(
            name_text,
            Text(str(sarea),                 style="cyan"),
            Text(str(total_captured),        style="bright_cyan"),
            Text(f"{area_per_min:.1f}",      style="bright_cyan"),
            Text(str(skills),                style="green"),
            Text(str(sdeaths),               style="red"),
            Text(f"{kd:.1f}",
                 style="bold bright_green" if kd >= 1 else "yellow"),
            Text(ttl_text,                   style="dim bright_white"),
            Text(conn_text,                  style="dim bright_white"),
        )

    # Server uptime + connection status moved to the top header (right
    # side). Keeping the dashboard panel clean to just the leaderboard.
    return Panel(table, border_style="bright_blue", title="dashboard", padding=(0, 0))


def format_uptime(sec: int) -> str:
    """Compact uptime: 1h05m, 22m, 8s."""
    if sec >= 3600:
        return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"
    if sec >= 60:
        return f"{sec // 60}m{sec % 60:02d}s"
    return f"{sec}s"


def build_footer(
    events: List[str],
    flash: Optional[Tuple[str, float]] = None,
) -> Panel:
    """Footer: control hint + recent events.

    Server uptime / connection status moved to the dashboard panel — the
    footer keeps just the keybind hint and the rolling event tape.
    """
    hint = Text()
    hint.append("W/A/S/D", style="bold bright_white on blue")
    hint.append(" move (player only)  ")
    hint.append("Esc", style="bold bright_white on red")
    hint.append(" / ", style="dim")
    hint.append("Ctrl+C×2", style="bold bright_white on red")
    hint.append(" quit  ")

    if events:
        hint.append(" | ", style="dim")
        for i, msg in enumerate(events):
            style = "bright_yellow" if i == len(events) - 1 else "yellow"
            hint.append(msg, style=style)
            if i < len(events) - 1:
                hint.append("  ·  ", style="dim")

    body: Any
    if flash is not None and flash[1] > time.monotonic():
        flash_text = Text(flash[0], style="bold black on bright_yellow", justify="center")
        body = Group(hint, Align.center(flash_text))
    else:
        body = hint

    return Panel(body, border_style="bright_blue", padding=(0, 1))


def fit_view_to_window(view_w: int, view_h: int,
                       cols: int, rows: int) -> Tuple[int, int, int, int]:
    """Return (pack_x=1, pack_y=1, cell_w=1, cell_h=1).

    Every world cell maps to exactly one terminal character. This is the
    only configuration where movement is perfectly smooth in both axes:
    every 1-cell step shifts on-screen content by exactly 1 char.

    Trade-offs:
    * The world appears vertically stretched (chars are typically 1:2
      wide:tall).
    * If the terminal cannot fit the entire 41×41 view, the edges of
      the view are clipped rather than compressed.

    Previously we tried pack_y=2 + half-block ``▀`` glyphs, which gives
    a square aspect ratio at the cost of parity-driven flicker: every
    other 1-cell step swaps a feature between ▀ and ▄ glyphs at
    adjacent char rows. The user reads that as "everything jumps".
    Half-char precision is fundamentally unachievable in a text grid.
    """
    return 1, 1, 1, 1


def build_layout(
    me: Dict[str, Any],
    view: Dict[str, Any],
    players: List[Dict[str, Any]],
    scores: List[Dict[str, Any]],
    events: List[str],
    flash: Optional[Tuple[str, float]],
    name: str,
    console_width: int,
    console_height: int = 40,
    pack_x: int = 0,
    pack_y: Optional[int] = None,
    server_uptime_sec: int = 0,
    connection: str = "connected",
    map_w: int = 0,
    map_h: int = 0,
    memory: Optional[MemoryMap] = None,
    latency_ms: int = -1,
) -> Layout:
    """Assemble the full Rich Layout.

    If pack_x <= 0 (default) the renderer auto-fits the view to fill the
    map panel — folds cells when view exceeds the window, expands cells
    when view is smaller.
    """
    header = build_header(me, name,
                          scores=scores,
                          server_uptime_sec=server_uptime_sec,
                          connection=connection,
                          latency_ms=latency_ms)
    view_w = int(view.get("w", 0))
    view_h = int(view.get("h", 0))
    # Side dashboard when view is wide enough AND console can fit it.
    side = (view_w >= 40) and (console_width >= 60)

    # Estimate map panel size for pack auto-fit. Side mode: map ≈ 5/7 width;
    # stacked: full width. Vertically: header (3) + footer (3) + dashboard.
    if side:
        map_cols = max(20, int(console_width * 4 / 7) - 4)
        map_rows = max(10, console_height - 3 - 3 - 2)  # header, footer, panel borders
    else:
        map_cols = max(20, console_width - 4)
        # dashboard takes ratio 1 of (map ratio 2 + dashboard ratio 1) → ~33%.
        map_rows = max(10, int((console_height - 6) * 2 / 3) - 2)

    if pack_x and pack_x > 0:
        eff_pack_x = max(1, int(pack_x))
        eff_pack_y = int(pack_y) if pack_y is not None and pack_y > 0 else 2 * eff_pack_x
        cell_w, cell_h = 1, 1
    else:
        eff_pack_x, eff_pack_y, cell_w, cell_h = fit_view_to_window(
            view_w, view_h, map_cols, map_rows
        )

    # When fog-of-war memory is available, render a wider window so the
    # player sees terrain they've already explored. Window size in cells =
    # screen char budget * pack / cell_size, bounded by the map size.
    screen_cells_w = 0
    screen_cells_h = 0
    if memory is not None and memory.map_w > 0:
        # The map panel reserves 5 char-cols on the left for the Y ruler
        # and 1 char-row at the bottom for the X ruler. Subtract those
        # from the available budget so the rulers don't push the map
        # off the edge (the X axis was getting clipped).
        RULER_W = 5
        RULER_H = 1
        screen_cells_w = ((map_cols - RULER_W) // cell_w) * eff_pack_x
        screen_cells_h = ((map_rows - RULER_H) // cell_h) * eff_pack_y
        screen_cells_w = max(view_w, min(memory.map_w, screen_cells_w))
        screen_cells_h = max(view_h, min(memory.map_h, screen_cells_h))

    map_panel = build_map(me, view, players,
                          pack_x=eff_pack_x, pack_y=eff_pack_y,
                          cell_w=cell_w, cell_h=cell_h,
                          map_w=map_w, map_h=map_h,
                          memory=memory,
                          screen_cells_w=screen_cells_w,
                          screen_cells_h=screen_cells_h)
    dashboard = build_dashboard(scores, int(me.get("id", 0)),
                                server_uptime_sec=server_uptime_sec,
                                connection=connection)
    footer = build_footer(events, flash)

    layout = Layout()
    if side:
        layout.split_column(
            Layout(header, name="header", size=3),
            Layout(name="body", ratio=1),
            Layout(footer, name="footer", size=3),
        )
        layout["body"].split_row(
            Layout(map_panel, name="map", ratio=4),
            Layout(dashboard, name="side", ratio=3, minimum_size=58),
        )
    else:
        layout.split_column(
            Layout(header, name="header", size=3),
            Layout(map_panel, name="map", ratio=2),
            Layout(dashboard, name="side", ratio=1, minimum_size=10),
            Layout(footer, name="footer", size=3),
        )

    return layout


def main():
    pass


if __name__ == "__main__":
    main()
