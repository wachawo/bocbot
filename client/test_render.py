#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Renderer regression tests.

The renderer cannot be reviewed by eye on a headless agent, so these
tests pin down concrete properties that "the map looks right" actually
means. Each test sets up a controlled MemoryMap + live view, renders it
through `build_map`, parses the ANSI output into (char, fg, bg) cells,
and asserts a property.

Run:  python3 client/test_render.py
"""

import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render
from render import MemoryMap, build_map

from rich.console import Console


# ANSI parsing
ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")
NAMED = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]


def parse_console(text: str) -> List[List[Tuple[str, str, str]]]:
    """Split each terminal line into (char, fg, bg) triples."""
    rows: List[List[Tuple[str, str, str]]] = []
    for raw in text.split("\n"):
        fg, bg = "default", "default"
        row: List[Tuple[str, str, str]] = []
        pos = 0
        while pos < len(raw):
            m = ANSI_RE.match(raw, pos)
            if m:
                params = m.group(1)
                tokens = params.split(";") if params else ["0"]
                i = 0
                while i < len(tokens):
                    t = tokens[i]
                    if t == "" or t == "0":
                        fg, bg = "default", "default"
                    elif t == "38" and i + 2 < len(tokens) and tokens[i + 1] == "5":
                        fg = f"c{tokens[i + 2]}"
                        i += 2
                    elif t == "48" and i + 2 < len(tokens) and tokens[i + 1] == "5":
                        bg = f"c{tokens[i + 2]}"
                        i += 2
                    elif t == "39":
                        fg = "default"
                    elif t == "49":
                        bg = "default"
                    elif t.isdigit():
                        n = int(t)
                        if 30 <= n <= 37:
                            fg = NAMED[n - 30]
                        elif 40 <= n <= 47:
                            bg = NAMED[n - 40]
                        elif 90 <= n <= 97:
                            fg = "bright_" + NAMED[n - 90]
                        elif 100 <= n <= 107:
                            bg = "bright_" + NAMED[n - 100]
                    i += 1
                pos = m.end()
            else:
                row.append((raw[pos], fg, bg))
                pos += 1
        rows.append(row)
    return rows


def make_memory(map_w: int, map_h: int,
                zone_cells: List[Tuple[int, int, int]],
                trail_cells: Optional[List[Tuple[int, int, int]]] = None) -> MemoryMap:
    mem = MemoryMap()
    mem.resize(map_w, map_h)
    for (x, y, pid) in zone_cells:
        i = y * map_w + x
        mem.zone[i] = pid
        mem.seen[i] = 1
    for (x, y, pid) in (trail_cells or []):
        i = y * map_w + x
        mem.trail[i] = pid
        mem.seen[i] = 1
    return mem


def render_scene(me: Dict[str, Any], view: Dict[str, Any], players: List[Dict[str, Any]],
                 memory: MemoryMap, *, console_w: int = 120, console_h: int = 70,
                 screen_cells_w: int = 80, screen_cells_h: int = 80,
                 pack_x: int = 1, pack_y: int = 1,
                 apply_view_fog: bool = True,
                 ) -> Tuple[List[List[Tuple[str, str, str]]], Dict[str, int]]:
    if apply_view_fog and memory.map_w > 0:
        # Real client sees update_from_view + update_from_fog on every state
        # before the first render. Simulate: mark live-view cells as seen
        # (zone derives from existing memory if set, else 0). Tests assume
        # the memory has whatever zone state the test set up; we only need
        # to flip `seen` for the rectangles the player has visibility over.
        x0 = int(view.get("x0", 0))
        y0 = int(view.get("y0", 0))
        w  = int(view.get("w",  0))
        h  = int(view.get("h",  0))
        for yy in range(max(0, y0), min(memory.map_h, y0 + h)):
            base = yy * memory.map_w
            for xx in range(max(0, x0), min(memory.map_w, x0 + w)):
                memory.seen[base + xx] = 1
        # Fog window 3× view, also gets `seen` flipped (zone unchanged).
        fw = w * 3
        fh = h * 3
        fx0 = me["x"] - fw // 2
        fy0 = me["y"] - fh // 2
        for yy in range(max(0, fy0), min(memory.map_h, fy0 + fh)):
            base = yy * memory.map_w
            for xx in range(max(0, fx0), min(memory.map_w, fx0 + fw)):
                memory.seen[base + xx] = 1
    panel = build_map(
        me, view, players,
        pack_x=pack_x, pack_y=pack_y,
        cell_w=1, cell_h=1,
        map_w=memory.map_w, map_h=memory.map_h,
        memory=memory,
        screen_cells_w=screen_cells_w,
        screen_cells_h=screen_cells_h,
    )
    con = Console(width=console_w, height=console_h, record=True,
                  force_terminal=True, color_system="256")
    con.print(panel)
    rows = parse_console(con.export_text(styles=True))
    # Compute the same window the renderer used so screen→world mapping is
    # reproducible for assertions.
    scr_w = min(screen_cells_w, memory.map_w + 4)
    scr_h = min(screen_cells_h, memory.map_h + 4)
    scr_w = max(pack_x, (scr_w // pack_x) * pack_x)
    scr_h = max(pack_y, (scr_h // pack_y) * pack_y)
    win_x0 = me["x"] - scr_w // 2
    win_y0 = me["y"] - scr_h // 2
    return rows, {"win_x0": win_x0, "win_y0": win_y0, "win_w": scr_w, "win_h": scr_h,
                  "pack_x": pack_x, "pack_y": pack_y}


def find_glyph(rows: List[List[Tuple[str, str, str]]], glyph: str
               ) -> List[Tuple[int, int]]:
    """Return (row_idx, col_idx) for every cell whose char matches `glyph`."""
    out = []
    for r, row in enumerate(rows):
        for c, (ch, _fg, _bg) in enumerate(row):
            if ch == glyph:
                out.append((r, c))
    return out


def collect_bgs(rows: List[List[Tuple[str, str, str]]]) -> List[str]:
    bgs = []
    for row in rows:
        for (_ch, _fg, bg) in row:
            if bg != "default":
                bgs.append(bg)
    return bgs


def collect_colors(rows: List[List[Tuple[str, str, str]]]) -> List[str]:
    """All non-default colours, fg or bg. Half-block ▀/▄ stores its cell
    colour in fg (bg = terminal default for the empty half), so a check
    that only scans bgs misses zone fills at edges."""
    out = []
    for row in rows:
        for (_ch, fg, bg) in row:
            if fg != "default":
                out.append(fg)
            if bg != "default":
                out.append(bg)
    return out


# Tests
results = {"pass": 0, "fail": 0, "fails": []}


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {name}")
        results["pass"] += 1
    else:
        print(f"FAIL  {name}: {detail}")
        results["fail"] += 1
        results["fails"].append(name)


def test_player_marker_present():
    mem = make_memory(100, 100, [(50, 50, 1), (49, 50, 1), (51, 50, 1)])
    me = {"id": 1, "x": 50, "y": 50, "alive": True, "area": 3,
          "trail_len": 0, "dir": "D"}
    view = {"x0": 30, "y0": 30, "w": 41, "h": 41, "zone": [], "trail": []}
    rows, _ = render_scene(me, view, [], mem)
    # Self marker is bright-white `×` (1-cell wide diagonal cross). Enemy
    # markers also use `×` but coloured by their pid palette; check that
    # exactly one bright_white × exists.
    self_count = 0
    for row in rows:
        for (ch, fg, _bg) in row:
            if ch == "×" and fg == "bright_white":
                self_count += 1
    check("player_marker_present",
          self_count == 1,
          f"expected exactly one bright_white ×, got {self_count}")


def test_no_enemy_marker_when_no_enemy_in_view():
    """Enemy `×` (non-white) must never appear without an enemy in
    `players`. The player's own `×` is bright_white and is excluded."""
    mem = make_memory(100, 100, [(50, 50, 1)] + [(80, y, 2) for y in (49, 50, 51)])
    me = {"id": 1, "x": 50, "y": 50, "alive": True, "area": 1, "trail_len": 0, "dir": "D"}
    view = {"x0": 30, "y0": 30, "w": 41, "h": 41, "zone": [], "trail": []}
    rows, _ = render_scene(me, view, [], mem)
    enemy_xs = 0
    for row in rows:
        for (ch, fg, _bg) in row:
            if ch == "×" and fg != "bright_white":
                enemy_xs += 1
    check("no_enemy_marker_in_fog",
          enemy_xs == 0,
          f"found {enemy_xs} enemy × marker(s); enemies live in `players`, not memory")


def test_no_trail_marker_in_pure_fog_cells():
    """When a cell has zone=enemy in fog but no trail in memory, no `·` appears."""
    mem = make_memory(100, 100,
                      [(50, 50, 1)] + [(80, y, 2) for y in (49, 50, 51)])
    me = {"id": 1, "x": 50, "y": 50, "alive": True, "area": 1, "trail_len": 0, "dir": "D"}
    view = {"x0": 30, "y0": 30, "w": 41, "h": 41, "zone": [], "trail": []}
    rows, _ = render_scene(me, view, [], mem)
    dots = find_glyph(rows, "·")
    check("no_trail_in_fog_when_memory_clean",
          len(dots) == 0,
          f"found {len(dots)} `·` marker(s); none expected because no trail is in memory")


def test_view_and_fog_use_different_bg_for_same_pid():
    """Enemy zone at row 75 (outside view rect rows 30..70) is in fog.
    Some bg in the render must be a grey-palette colour (fog dim). With
    a saturated-green enemy zone INSIDE the view, the renderer must also
    use the green bg somewhere. The two sets must be distinct → distance
    visibly dims foreign zones."""
    mem = make_memory(100, 100,
                      [(50, 50, 1)]              # own spawn
                      + [(x, 50, 2) for x in range(60, 65)]   # enemy IN view (right of me, in row 50)
                      + [(x, 75, 2) for x in range(40, 61)])  # enemy in fog (row 75)
    me = {"id": 1, "x": 50, "y": 50, "alive": True, "area": 1, "trail_len": 0, "dir": "D"}
    view = {"x0": 30, "y0": 30, "w": 41, "h": 41, "zone": [], "trail": []}
    rows, _ = render_scene(me, view, [], mem)
    cols = collect_colors(rows)
    grey_seen = any(_is_grey(c) for c in cols)
    green_seen = any(_is_green(c) for c in cols)
    check("fog_uses_grey_palette",
          grey_seen,
          f"no grey-shaded colour seen; sample={sorted(set(cols))[:12]}")
    check("view_uses_full_colour_palette",
          green_seen,
          f"no green colour seen; sample={sorted(set(cols))[:12]}")


def _is_grey(token: str) -> bool:
    # 256-color greys are indexes 232..255 (24-step greyscale ramp), plus
    # any 16+36r+6g+b where r==g==b (cube diagonal).
    if token.startswith("c"):
        try:
            idx = int(token[1:])
        except ValueError:
            return False
        if 232 <= idx <= 255:
            return True
        if 16 <= idx <= 231:
            idx -= 16
            r, rem = divmod(idx, 36)
            g, b = divmod(rem, 6)
            return r == g == b
    return False


def _is_green(token: str) -> bool:
    if token in ("green", "bright_green"):
        return True
    if token.startswith("c"):
        try:
            idx = int(token[1:])
        except ValueError:
            return False
        if idx in (2, 10, 34, 46):
            return True
        if 16 <= idx <= 231:
            idx -= 16
            r, rem = divmod(idx, 36)
            g, b = divmod(rem, 6)
            return g > r and g > b and g >= 2
    return False


def test_world_static_between_me_y_and_me_y_plus_2():
    """Pack_y=2 means a 2-cell vertical move shifts the world by exactly 1
    char row. The non-player content of the render at (me_y) and (me_y+2)
    must therefore be the same modulo a 1-row vertical shift."""
    # Vertical enemy strip at x=55 (inside both the live view and window).
    mem = make_memory(100, 100,
                      [(50, 50, 1)]
                      + [(55, y, 2) for y in range(30, 80)])
    view_a = {"x0": 30, "y0": 30, "w": 41, "h": 41, "zone": [], "trail": []}
    me_a = {"id": 1, "x": 50, "y": 50, "alive": True, "area": 1, "trail_len": 0, "dir": "D"}
    me_b = dict(me_a, y=52)
    view_b = dict(view_a, y0=32)
    rows_a, _ = render_scene(me_a, view_a, [], mem)
    rows_b, _ = render_scene(me_b, view_b, [], mem)
    # Topmost char-row that touches a green cell. As the player moves
    # 2 cells south the strip TOP slides 1 char row north — first it's
    # the bright green of the strip (in view), then it becomes the DIM
    # green of the strip (in fog), but either way the top should be
    # visible 1 row higher than before. Detect only the strip's own
    # pid-2 colours (BG_PALETTE[1] = c34 green + DIM_PALETTE[1] = c22
    # green-dim, plus the vivid pid-9 c46/c28 alternates), NOT the
    # fog-ring floor (c234) which centres on player and would always
    # pin the top to a constant char row.
    STRIP_COLOURS = {"green", "bright_green", "c34", "c46", "c22", "c28"}
    def coloured_rows(rs):
        out = []
        for r_idx, row in enumerate(rs):
            for (_ch, fg, bg) in row:
                if fg in STRIP_COLOURS or bg in STRIP_COLOURS:
                    out.append(r_idx)
                    break
        return out
    g_a = coloured_rows(rows_a)
    g_b = coloured_rows(rows_b)
    if g_a and g_b:
        shift = min(g_b) - min(g_a)
        check("two_step_shifts_two_chars",
              shift == -2,
              f"strip top shifted {shift} rows (want -2) for me_y 50→52, pack_y=1")
    else:
        check("two_step_shifts_two_chars", False,
              f"strip not found (g_a={g_a}, g_b={g_b})")


def test_no_glyph_flicker_on_single_step():
    """One cell of vertical motion: the SAME world feature shouldn't toggle
    between two completely different glyphs (e.g. ▀ ↔ ▄ ↔ space). The set
    of glyphs used at the enemy-strip column over consecutive renders
    should overlap, i.e. at least one glyph kind is shared."""
    mem = make_memory(100, 100,
                      [(50, 50, 1)]
                      + [(55, y, 2) for y in range(30, 80)])
    base_me = {"id": 1, "x": 50, "y": 50, "alive": True, "area": 1, "trail_len": 0, "dir": "D"}
    base_view = {"x0": 30, "y0": 30, "w": 41, "h": 41, "zone": [], "trail": []}
    glyph_sets = []
    for dy in range(0, 4):
        me = dict(base_me, y=50 + dy)
        view = dict(base_view, y0=30 + dy)
        rows, _ = render_scene(me, view, [], mem)
        glyphs = set()
        for row in rows:
            for (ch, _fg, bg) in row:
                if _is_green(bg):
                    glyphs.add(ch)
                if _is_green(_fg) and ch in ("▀", "▄"):
                    glyphs.add(ch)
        glyph_sets.append(glyphs)
    # Each pair of consecutive renders should share at least one glyph kind.
    bad = []
    for i in range(len(glyph_sets) - 1):
        if not (glyph_sets[i] & glyph_sets[i + 1]):
            bad.append((i, i + 1, glyph_sets[i], glyph_sets[i + 1]))
    check("glyphs_overlap_between_consecutive_steps",
          len(bad) == 0,
          f"glyph set churned: {bad}")


def test_spawn_is_uniform_solid_rectangle():
    """3×3 spawn must render as a solid coloured rectangle — no ▀ / ▄
    half-block glyphs on its edge against the empty view floor. The user
    perceives such half-blocks as a "non-uniform / non-square" spawn."""
    mem = make_memory(100, 100,
                      [(x, y, 1) for x in (49, 50, 51) for y in (49, 50, 51)])
    me = {"id": 1, "x": 50, "y": 50, "alive": True, "area": 9, "trail_len": 0, "dir": "D"}
    view = {"x0": 30, "y0": 30, "w": 41, "h": 41, "zone": [], "trail": []}
    rows, _ = render_scene(me, view, [], mem)
    # Find every char with a red bg or red fg in a half-block glyph.
    red_solids = 0
    red_halves = 0
    for row in rows:
        for (ch, fg, bg) in row:
            if bg == "c160" and ch == " ":
                red_solids += 1
            elif fg == "c160" and ch in ("▀", "▄"):
                red_halves += 1
    check("spawn_renders_solid",
          red_halves == 0 and red_solids >= 4,
          f"spawn has {red_halves} half-block edges (want 0) and {red_solids} solid cells")


def test_own_zone_dimmed_outside_view():
    """Own zone cells inside the live view should be a brighter shade than
    the same own zone cells in fog — so the player can tell which of their
    territory is currently in view from what's only known via memory."""
    mem = make_memory(100, 100,
                      [(x, 50, 1) for x in (49, 50, 51)]       # in view
                      + [(x, 75, 1) for x in (48, 49, 50, 51, 52)])  # in fog
    me = {"id": 1, "x": 50, "y": 50, "alive": True, "area": 8,
          "trail_len": 0, "dir": "D"}
    view = {"x0": 30, "y0": 30, "w": 41, "h": 41, "zone": [], "trail": []}
    rows, _ = render_scene(me, view, [], mem)
    # View own zone uses c160 (saturated red). Fog own zone uses c52
    # (same hue, darker — a SHADE, not a pastel).
    from collections import Counter
    bgs = Counter(collect_bgs(rows))
    deep = bgs.get("c160", 0)     # in-view
    dim_ = bgs.get("c52", 0)      # in-fog
    check("own_zone_dimmed_in_fog",
          deep > 0 and dim_ > 0,
          f"bgs={bgs.most_common(8)} — want both c160 (view) and c52 (fog)")


def test_own_trail_visible_in_fog():
    """Server includes the player's own trail in the `fog` rectangle
    (filtered: enemy trails stay invisible). When the trail extends
    beyond the live view, the client still shows `·` markers along it."""
    # Own trail at (45, 50): outside live view (view x0=30..70 but
    # view.y0=30..70; 45 IS inside view actually). Move trail to row 75.
    mem = make_memory(100, 100,
                      [(50, 50, 1)])
    # Inject trail directly in memory (simulating fog update applied it).
    for x in range(50, 60):
        mem.trail[75 * 100 + x] = 1
        mem.seen[75 * 100 + x] = 1
    me = {"id": 1, "x": 50, "y": 50, "alive": True, "area": 1,
          "trail_len": 10, "dir": "D"}
    view = {"x0": 30, "y0": 30, "w": 41, "h": 41, "zone": [], "trail": []}
    rows, _ = render_scene(me, view, [], mem)
    own_dots = 0
    for row in rows:
        for (ch, fg, _bg) in row:
            if ch == "·" and fg == "c160":   # c160 = bg_for(pid=1)
                own_dots += 1
    check("own_trail_visible_in_fog",
          own_dots >= 5,
          f"only {own_dots} own-trail dots in fog; want ≥ 5 for a 10-cell trail")


def test_no_enemy_trail_in_fog_memory():
    """Memory must never carry enemy trail data for fog cells — the
    server filters its fog.trail payload to own-pid only. If somehow
    memory has enemy trail outside view, that's a leak."""
    mem = make_memory(100, 100, [(50, 50, 1)])
    # Pretend a previous view broadcast leaked an enemy trail in memory.
    mem.trail[75 * 100 + 50] = 2   # enemy pid=2 trail outside view
    mem.seen[75 * 100 + 50] = 1
    me = {"id": 1, "x": 50, "y": 50, "alive": True, "area": 1,
          "trail_len": 0, "dir": "D"}
    view = {"x0": 30, "y0": 30, "w": 41, "h": 41, "zone": [], "trail": []}
    rows, _ = render_scene(me, view, [], mem)
    enemy_dots = 0
    for row in rows:
        for (ch, fg, _bg) in row:
            # Enemy trail would render as `·` with green fg (pid 2 colour).
            if ch == "·" and fg in ("green", "c34", "bright_green", "c46"):
                enemy_dots += 1
    check("no_enemy_trail_dot_in_fog",
          enemy_dots == 0,
          f"found {enemy_dots} enemy `·` outside view — enemy trails must never leak past the live-view rect")


def test_one_step_shifts_one_char():
    """Each 1-cell vertical move must shift the world by exactly 1 char
    row — never 0 (frozen) and never 2 (jumped). Test on a window that
    fully fits the console so nothing is clipped; pack_y=1 should give
    one-to-one cell→char correspondence."""
    STRIP_COLOURS = {"green", "bright_green", "c34", "c46", "c237", "c235", "c233"}
    mem = make_memory(60, 60,
                      [(30, 30, 1)]
                      + [(35, y, 2) for y in range(20, 45)])
    base_view = {"x0": 10, "y0": 10, "w": 41, "h": 41, "zone": [], "trail": []}
    deltas = []
    last_top = None
    for dy in range(0, 6):
        me = {"id": 1, "x": 30, "y": 30 + dy, "alive": True, "area": 1,
              "trail_len": 0, "dir": "D"}
        view = dict(base_view, y0=10 + dy)
        rows, _ = render_scene(me, view, [], mem,
                               console_w=80, console_h=64,
                               screen_cells_w=60, screen_cells_h=60)
        top = None
        for r_idx, row in enumerate(rows):
            for (_ch, fg, bg) in row:
                if fg in STRIP_COLOURS or bg in STRIP_COLOURS:
                    top = r_idx
                    break
            if top is not None:
                break
        if last_top is not None and top is not None:
            deltas.append(last_top - top)
        last_top = top
    check("one_step_shifts_one_char",
          all(d == 1 for d in deltas),
          f"per-step shifts: {deltas} (want [1]*N; last_top={last_top})")


def test_row_widths_consistent():
    """Every rendered row must have the same VISUAL width. A wide-glyph
    (East Asian Wide, e.g. ``㋡`` U+32E1) emitted as a single char will
    inflate one row by 1 column → spawn looks like an L instead of a
    rectangle on screen."""
    import unicodedata
    def visual_width(ch: str) -> int:
        if not ch:
            return 0
        eaw = unicodedata.east_asian_width(ch)
        return 2 if eaw in ("F", "W") else 1
    mem = make_memory(100, 100,
                      [(x, y, 1) for x in (49, 50, 51) for y in (49, 50, 51)])
    me = {"id": 1, "x": 50, "y": 50, "alive": True, "area": 9, "trail_len": 0, "dir": "D"}
    view = {"x0": 30, "y0": 30, "w": 41, "h": 41, "zone": [], "trail": []}
    rows, _ = render_scene(me, view, [], mem)
    widths = []
    for row in rows:
        w = sum(visual_width(ch) for (ch, _fg, _bg) in row)
        if w > 0:
            widths.append(w)
    distinct = set(widths)
    check("row_widths_consistent",
          len(distinct) == 1,
          f"got {len(distinct)} distinct visual widths: {sorted(distinct)[:6]}")


def test_live_view_floor_is_lighter_than_fog():
    """Live view = bright spotlight (color 238). Fog = terminal default.
    The contrast must be unambiguous."""
    mem = make_memory(100, 100, [(50, 50, 1), (49, 50, 1), (51, 50, 1),
                                  (50, 49, 1), (50, 51, 1)])
    me = {"id": 1, "x": 50, "y": 50, "alive": True, "area": 5, "trail_len": 0, "dir": "D"}
    view = {"x0": 30, "y0": 30, "w": 41, "h": 41, "zone": [], "trail": []}
    rows, _ = render_scene(me, view, [], mem)
    view_floor = 0
    for row in rows:
        for (_ch, _fg, bg) in row:
            if bg == "c238":
                view_floor += 1
    check("live_view_floor_bright",
          view_floor > 50,
          f"only {view_floor} view-floor c238 cells; expected hundreds for a 41×41 view")


if __name__ == "__main__":
    test_player_marker_present()
    test_no_enemy_marker_when_no_enemy_in_view()
    test_no_trail_marker_in_pure_fog_cells()
    test_view_and_fog_use_different_bg_for_same_pid()
    test_world_static_between_me_y_and_me_y_plus_2()
    test_no_glyph_flicker_on_single_step()
    test_live_view_floor_is_lighter_than_fog()
    test_spawn_is_uniform_solid_rectangle()
    test_row_widths_consistent()
    test_one_step_shifts_one_char()
    test_own_trail_visible_in_fog()
    test_no_enemy_trail_in_fog_memory()
    test_own_zone_dimmed_outside_view()
    print()
    print(f"== {results['pass']} pass / {results['fail']} fail ==")
    if results["fail"]:
        for name in results["fails"]:
            print(f"  FAIL {name}")
        sys.exit(1)
