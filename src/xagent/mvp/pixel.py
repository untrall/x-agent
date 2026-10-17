"""Warm pixel look for the agent TUI: theme, palette, avatars, spinner.

Presentation only — nothing here touches negotiation state.
"""
from __future__ import annotations

from rich.text import Text
from textual.theme import Theme

ORANGE = "#D97757"   # primary: borders, titles, my side
AMBER = "#E8B34B"    # accent: needs-you, the other side
BG = "#1F1E1D"       # warm black
SURFACE = "#262624"
PANEL = "#2F2D2A"
INK = "#F0EEE6"      # body text
DIM = "#8A8580"      # secondary text

THEME = Theme(
    name="x-agent-pixel",
    primary=ORANGE,
    secondary=AMBER,
    accent=AMBER,
    warning=AMBER,
    error="#E5534B",
    success="#C9A26B",
    foreground=INK,
    background=BG,
    surface=SURFACE,
    panel=PANEL,
    dark=True,
)

# Pixel pets, 9x7 pixels, one pixel = two terminal cells (one row), so no
# half-block seams between rows even with extra terminal line spacing.
# Exact xterm-256 colours, so they look the same inside tmux's 256-colour mode.
DARK, SNOW = "#1c1c1c", "#eeeeee"
_PETS = {
    1: ({"b": "#87d75f", "s": "#5faf5f", "a": "#d7ff87", "e": DARK, "w": SNOW, "m": "#5f875f"}, [
        "a.......a",   # 阿哲: green ET alien with antennae and big almond eyes
        ".s.....s.",
        "..bbbbb..",
        ".bbbbbbb.",
        "bwebbbewb",
        "beebbbeeb",
        ".bbbmbbb.",
    ]),
    2: ({"b": "#ff875f", "i": "#d75f5f", "e": DARK, "w": SNOW, "n": DARK}, [
        "b.......b",   # 陈语桐: orange fox, white muzzle
        "bi.....ib",
        "bbbbbbbbb",
        "bebbbbbeb",
        "bbwwwwwbb",
        ".bwwnwwb.",
        "..wwwww..",
    ]),
    3: ({"b": "#ffd7d7", "i": "#ff87af", "e": DARK, "r": "#ff87af", "n": "#d75f87", "m": "#d75f87"}, [
        ".bb...bb.",   # 方糖: pink bunny, long ears, rosy cheeks
        ".bi...ib.",
        ".bbbbbbb.",
        "bbebbbebb",
        "brbbnbbrb",
        "bbbmbmbbb",
        ".bbbbbbb.",
    ]),
    4: ({"b": "#444444", "w": SNOW, "e": DARK, "y": "#ffaf00"}, [
        "..bbbbb..",   # 林小满: penguin, calm and steady
        ".bbbbbbb.",
        "bbwwbwwbb",
        "bwewbwewb",
        "bwwwywwwb",
        "bwwwwwwwb",
        ".bbwwwbb.",
    ]),
}
# Anyone else: the little X-Agent critter.
_CRITTER = ({"b": ORANGE, "e": DARK}, [
    "..bbbbb..",
    ".bbbbbbb.",
    "bbebbbebb",
    "bbbbbbbbb",
    ".bbbbbbb.",
    "..b...b..",
    ".bb...bb.",
])

# Claude-Code-style thinking glyphs, cycled while an agent works.
SPINNER = ["·", "✢", "✳", "✶", "✻", "✽", "✻", "✶", "✳", "✢"]


def _number(agent_id: str | None) -> int | None:
    tail = str(agent_id or "").rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else None


def avatar(agent_id: str | None) -> Text:
    """A different pixel pet per agent, so the windows are easy to tell apart."""
    colors, bitmap = _PETS.get(_number(agent_id), _CRITTER)
    text = Text()
    for row in bitmap:
        for pixel in row:
            # Full block in fg AND bg: the glyph fills the cell, the background
            # fills any line spacing (and a bare-background space gets dropped).
            text.append("██" if pixel != "." else "  ",
                        style=f"{colors[pixel]} on {colors[pixel]}" if pixel != "." else "")
        text.append("\n")
    text.rstrip()
    return text


# One colour per role, the same in every window.
ROLE_COLORS = {
    "me": "#ffd75f",          # 我
    "my_agent": ORANGE,       # 我的 Agent
    "peer": "#ff87af",        # X本人
    "peer_agent": "#d7af87",  # X的 Agent
    "internal": DIM,          # 我的 Agent（内部）
}


def role_line(speaker: tuple[str, str], target: tuple[str, str] | None, body: str) -> Text:
    """'speaker → target' with each role in its own colour, then the message."""
    role, label = speaker
    text = Text(label, style=f"bold {ROLE_COLORS[role]}")
    if target:
        text.append(" → ", style=DIM)
        text.append(target[1], style=f"bold {ROLE_COLORS[target[0]]}")
    text.append("\n  " + body, style=DIM if role == "internal" else INK)
    return text
