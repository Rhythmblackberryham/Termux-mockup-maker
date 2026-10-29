#!/usr/bin/env python3
"""
SnapForge - website screenshots + scrolling videos in Termux
Full page, desktop mode + mobile mode, animations included.
An animated mascot and a rose that grows while your files are made,
plus a 1080x1920 rose growth reel you can post on Instagram.

FIRST TIME SETUP (once):
    python shot.py --setup

EASY MODE (menu):
    python shot.py

COMMAND MODE:
    python shot.py example.com                      # screenshots, both modes
    python shot.py example.com -t video             # scrolling video
    python shot.py example.com -t both -m mobile    # shot + video, mobile only
    python shot.py example.com -t video -s slow     # slow / standard / fast / number
    python shot.py example.com -a fast              # quick shot, skips animation pass
    python shot.py example.com -w 2                 # wait 2s per section (slow animations)
    python shot.py example.com -q ultra             # sharper screenshots
    python shot.py example.com -t mockup            # laptop + phone mockup image
    python shot.py example.com -t mockup --layout all --theme rose
    python shot.py example.com -t mockup --media video   # page scrolls in the mockup
    python shot.py example.com -t mockup --media video --theme greenscreen --zoom
    python shot.py example.com -t video --pause 6   # wait 6s at the top first
    python shot.py example.com -t shot --pause 0    # no waiting
    python shot.py example.com --format png         # bigger PNG instead of JPG
    python shot.py --clean                          # free up storage
    python shot.py -t rose                          # Instagram rose growth reel
    python shot.py -t rose --rose-quality fast      # quicker preview of the reel
    python shot.py -t rose --rose-theme greenscreen # green screen background

Saved to ~/storage/shared/Pictures/WebShots (Gallery) or ./WebShots
"""

import argparse
import base64
import io
import json
import math
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime
from urllib.parse import urlparse

try:                       # gives proper line editing (backspace, paste, arrows)
    import readline  # noqa: F401
    HAS_READLINE = True
except ImportError:
    HAS_READLINE = False

DESKTOP = {"width": 1920, "height": 1080,
           "ua": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
MOBILE = {"width": 390, "height": 844,
          "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 "
                "Mobile/15E148 Safari/604.1"}

QUALITY = {"standard": (1.0, 2.0), "high": (1.5, 3.0), "ultra": (2.0, 3.0)}
# Video quality. dpr = (desktop, phone) sharpness of the page itself; "mock" =
# (laptop canvas scale, phone canvas scale, laptop dpr, phone dpr) for mockups.
# Zoom-ready mockups: (laptop dpr, phone dpr). The screen is drawn 1:1 with the
# pixels the browser captured, so nothing gets blurred by resizing.
ZOOM_DPR = {"standard": (1.0, 2.0), "high": (1.5, 3.0), "ultra": (2.0, 3.0)}

VIDEO_Q = {
    "standard": {"crf": 23, "preset": "veryfast", "fmt": "jpeg", "q": 90,
                 "dpr": (1.0, 2.0), "mock": (0.6, 0.54, 1.0, 2.0)},
    "high":     {"crf": 18, "preset": "fast", "fmt": "jpeg", "q": 96,
                 "dpr": (1.0, 1080 / 390), "mock": (0.8, 0.72, 1.25, 2.0)},
    "ultra":    {"crf": 15, "preset": "medium", "fmt": "png", "q": 100,
                 "dpr": (1.5, 3.0), "mock": (1.0, 0.96, 2.0, 3.0)},
}
for _k, _v in VIDEO_Q.items():
    _v["zoom"] = ZOOM_DPR[_k]

SPEEDS = {"slow": 150, "standard": 400, "fast": 800}   # page px per second
DEFAULT_SPEED = "standard"
VIDEO_FPS = 30
HOLD_FRAMES = 20

MAX_TOTAL_PIXELS = 120_000_000
CHUNK_DEVICE_PX = 6000
MAX_PAGE_CSS_HEIGHT = 40000
DEFAULT_SETTLE = 1.0           # seconds to let animations play per section

# ----------------------------------------------------------------------
# Look & feel
# ----------------------------------------------------------------------
LIVE = sys.stdout.isatty()
USE_COLOR = LIVE and not os.environ.get("NO_COLOR")
CYAN, GREEN, YELLOW, RED, MAG = "36", "32", "33", "31", "35"
BOLD, DIM = "1", "2"


def paint(text, *codes):
    if not USE_COLOR:
        return text
    return "\033[" + ";".join(codes) + "m" + text + "\033[0m"


def say(msg=""):
    print(msg, flush=True)


FACES = {"ready": "(◕‿◕)", "work": "(⌐■_■)", "happy": "(^▽^)", "sad": "(╥_╥)"}


def talk(mood, msg, color=CYAN):
    say(f"{paint(FACES[mood], color, BOLD)} {msg}")


def ask(text, codes=(BOLD, YELLOW)):
    """input() with a coloured prompt.

    The colour codes are wrapped in \001 ... \002 so readline knows they take
    no space on screen. Without that, deleting a letter leaves the last
    letter behind (the bug with pasted text)."""
    if USE_COLOR:
        start, end = "\033[" + ";".join(codes) + "m", "\033[0m"
        if HAS_READLINE:
            start, end = "\001" + start + "\002", "\001" + end + "\002"
        prompt = start + text + end
    else:
        prompt = text
    try:
        return input(prompt)
    finally:
        try:                                   # drop leftover pasted lines
            import termios
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            pass


def heading(text):
    say()
    say(paint("━━ " + text + " ━━", BOLD, MAG))


# ----------------------------------------------------------------------
# Animated mascot
# ----------------------------------------------------------------------
EYE_CYCLE = ([" ◉ ◉ "] * 8 + ["  ◉ ◉"] * 4 + [" ◉ ◉ "] * 8 + ["◉ ◉  "] * 4
             + [" ◉ ◉ "] * 6 + [" ─ ─ "] * 2)
MOUTH_CYCLE = ["  ▽  ", "  ▽  ", "  ▽  ", "  ○  "]


def mascot_rows(tick, mood="work"):
    """7 rows, each exactly 11 characters wide."""
    if mood == "happy":
        eyes, mouth = " ^ ^ ", "  ‿  "
        ant = "*" if tick % 2 else "+"
    elif mood == "sad":
        eyes, mouth = " ╥ ╥ ", "  ∩  "
        ant = "─"
    else:
        eyes = EYE_CYCLE[tick % len(EYE_CYCLE)]
        mouth = MOUTH_CYCLE[(tick // 3) % len(MOUTH_CYCLE)]
        ant = "*" if (tick // 3) % 2 else "─"
    light = "●" if (tick // 4) % 2 == 0 else "○"
    light_col = RED if mood == "work" else (GREEN if mood in ("ready", "happy") else DIM)
    return [
        paint("   ╭─" + ant + "─╮   ", CYAN),
        paint("╭──┴───┴──╮", CYAN),
        paint("│ ╭─────╮ │", CYAN),
        paint("│ │", CYAN) + paint(eyes, YELLOW, BOLD) + paint("│ │", CYAN),
        paint("│ │", CYAN) + paint(mouth, YELLOW) + paint("│ │", CYAN),
        paint("│ ╰─────╯ │", CYAN),
        paint("╰────", CYAN) + paint(light, light_col, BOLD) + paint("────╯", CYAN),
    ]


# ----------------------------------------------------------------------
# Procedural rose (terminal preview + Instagram reel)
# ----------------------------------------------------------------------
D_W, D_H = 100.0, 135.0
R_CX, R_GROUND, R_STEM = 50.0, 124.0, 84.0

STEM_C, STEM_HI = (38, 98, 56), (92, 164, 104)
LEAF_DK, LEAF_LT, LEAF_RIB = (24, 92, 56), (66, 160, 94), (170, 220, 160)
SEPAL_C = (44, 122, 70)
THORN_C = (140, 56, 60)
PET_IN, PET_OUT = (88, 4, 30), (236, 56, 92)
LEAVES = [(0.13, 1, 21, 64), (0.25, -1, 24, 60), (0.38, 1, 22, 56),
          (0.51, -1, 18, 52), (0.64, 1, 14, 46)]
THORNS = [0.08, 0.19, 0.31, 0.44, 0.57, 0.70]
NPT = 34


def _clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def _smooth(x):
    x = _clamp(x)
    return x * x * (3 - 2 * x)


def _lerp(a, b, t):
    return a + (b - a) * t


def _mix(c1, c2, t):
    return tuple(int(_lerp(c1[i], c2[i], t)) for i in range(3))


def _shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


def _ellipse_pts(cx, cy, rx, ry, rot=0.0, n=22):
    cr, sr = math.cos(rot), math.sin(rot)
    pts = []
    for i in range(n):
        th = 2 * math.pi * i / n
        ex, ey = rx * math.cos(th), ry * math.sin(th)
        pts.append((cx + ex * cr - ey * sr, cy + ex * sr + ey * cr))
    return pts


def _leaf_poly(x0, y0, dx, dy, L, wf, droop=0.0, steps=10,
               t0=0.0, t1=1.0, wscale=1.0):
    nx, ny = -dy, dx
    left, right = [], []
    for i in range(steps + 1):
        tt = t0 + (t1 - t0) * i / steps
        cx_ = x0 + dx * L * tt
        cy_ = y0 + dy * L * tt + droop * L * tt * tt
        hw = wf * L * wscale * (math.sin(math.pi * tt) ** 0.75) * (1 - 0.15 * tt)
        left.append((cx_ + nx * hw, cy_ + ny * hw))
        right.append((cx_ - nx * hw, cy_ - ny * hw))
    return left + right[::-1]


def stem_point(u, t=0.0):
    return (R_CX + 5.0 * math.sin(2.2 * u) + 1.4 * math.sin(t * 1.4) * u ** 1.5,
            R_GROUND - R_STEM * u)


def rose_geometry(p, t=0.0):
    """Bloom centre (design units), radius and open amount."""
    q = _clamp((p - 0.55) / 0.45)
    R = 17.0 * (_smooth(q) ** 0.85)
    tx, ty = stem_point(1.0, t)
    return tx, ty - 0.25 * R, R, q


def render_rose(p, t=0.0, width=30, ss=4, fall=0.0, sparkle=False,
                star=1.0, detail=False):
    """Draw the rose plant at growth p (0..1). Returns a transparent RGBA image."""
    from PIL import Image, ImageDraw

    h = int(round(D_H / 100.0 * width))
    W, H = width * ss, h * ss
    s = W / D_W
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def P(x, y):
        return (x * s, H - (D_H - y) * s)

    def poly(pts, fill):
        d.polygon([P(x, y) for x, y in pts], fill=fill)

    def ell(cx, cy, rx, ry, fill):
        x0, y0 = P(cx - rx, cy - ry)
        x1, y1 = P(cx + rx, cy + ry)
        d.ellipse([x0, y0, x1, y1], fill=fill)

    def line(pts, fill, wd):
        d.line([P(x, y) for x, y in pts], fill=fill,
               width=max(1, int(round(wd * s))), joint="curve")

    # soil mound
    ell(R_CX, R_GROUND + 1.5, 19, 4.4, (46, 26, 26))
    ell(R_CX, R_GROUND + 0.6, 16, 3.2, (74, 44, 38))
    ell(R_CX - 3, R_GROUND - 0.2, 7, 1.2, (100, 64, 52))

    g = 1 - (1 - _clamp(p / 0.55)) ** 2

    # leaves (behind the stem)
    for up, side, ln, ang in LEAVES:
        lf = _clamp((g - up) / 0.14)
        if lf <= 0:
            continue
        x0, y0 = stem_point(up, t)
        a = math.radians(ang)
        dx, dy = side * math.sin(a), -math.cos(a)
        L = ln * (0.2 + 0.8 * _smooth(lf))
        poly(_leaf_poly(x0, y0, dx, dy, L, 0.30, 0.32), LEAF_DK)
        poly(_leaf_poly(x0, y0, dx, dy, L, 0.30, 0.32, t0=0.06, t1=0.94,
                        wscale=0.5), LEAF_LT)
        if detail:
            rib = [(x0 + dx * L * tt, y0 + dy * L * tt + 0.32 * L * tt * tt)
                   for tt in (0.05, 0.25, 0.5, 0.75, 0.92)]
            line(rib, LEAF_RIB, 0.28)

    # stem
    if g > 0.005:
        steps = max(3, int(g * 48))
        pts = [stem_point(g * i / steps, t) for i in range(steps + 1)]
        for i in range(steps):
            wd = _lerp(3.4, 2.1, g * i / steps)
            line([pts[i], pts[i + 1]], STEM_C, wd)
            ell(pts[i][0], pts[i][1], wd / 2, wd / 2, STEM_C)
        ell(pts[-1][0], pts[-1][1], 1.05, 1.05, STEM_C)
        line([(x - 0.55, y) for x, y in pts], STEM_HI, 0.55)

    # thorns
    for k, up in enumerate(THORNS):
        if g < up + 0.02:
            continue
        side = 1 if k % 2 == 0 else -1
        x0, y0 = stem_point(up, t)
        poly([(x0 + side * 0.8, y0 - 0.9), (x0 + side * 0.8, y0 + 0.9),
              (x0 + side * 3.0, y0 + 0.7)], THORN_C)

    # bloom
    bx, by, R, q = rose_geometry(p, t)
    if R > 0.7:
        eq = _smooth(q)
        for k in range(5):
            a0 = (-120, -105, -90, -75, -60)[k]
            a1 = (-200, -230, 90, 50, 20)[k]
            a = math.radians(_lerp(a0, a1, eq))
            Ls = R * _lerp(1.35, 1.0, eq)
            poly(_leaf_poly(bx, by + 0.35 * R, math.cos(a), math.sin(a),
                            Ls, 0.27), SEPAL_C)

        n = min(NPT, max(1, int(8 + (NPT - 8) * q)))
        for j in range(n - 1, -1, -1):
            tt = j / (NPT - 1)
            a = math.radians(j * 137.508 + 20)
            dd = R * (0.05 + 0.50 * tt ** 0.85)
            rw = R * (0.20 + 0.45 * tt)
            rh = R * (0.16 + 0.38 * tt)
            px_ = bx + dd * math.cos(a)
            py_ = by + dd * math.sin(a) * 0.82
            col = _mix(PET_IN, PET_OUT, tt)
            jit = ((j * 37) % 7 - 3) * 2
            col = tuple(max(0, min(255, v + jit)) for v in col)
            pts = _ellipse_pts(px_, py_, rw, rh, a)
            poly(pts, col)
            if detail:
                hx = px_ + math.cos(a) * 0.28 * rw
                hy = py_ + math.sin(a) * 0.28 * rw * 0.82
                poly(_ellipse_pts(hx, hy, rw * 0.58, rh * 0.5, a), _shade(col, 1.2))
                line(pts + [pts[0]], _shade(col, 0.55), 0.28)
        if detail and q > 0.6:
            sp = []
            for i in range(40):
                th = i * 0.32
                r = R * (0.02 + 0.2 * i / 40)
                sp.append((bx + r * math.cos(th), by + r * math.sin(th) * 0.82))
            line(sp, _shade(PET_IN, 0.7), 0.4)

    # falling petals
    if fall > 0:
        for k in range(7):
            tau = fall - k * 0.45
            if tau <= 0:
                continue
            x = bx + (k - 3) * R * 0.16 + 5.0 * math.sin(tau * 1.6 + k * 1.3) \
                + (k - 3) * 0.8 * tau
            y = by + R * 0.95 + (10 + 1.5 * k) * tau
            ground = R_GROUND + 0.5 + (k % 3) * 0.7
            rest = y >= ground
            if rest:
                y = ground
            rot = k * 0.9 if rest else tau * (1.2 + 0.3 * k)
            poly(_ellipse_pts(x, y, 2.9, 1.7, rot),
                 _mix(PET_IN, PET_OUT, 0.55 + 0.05 * k))

    # sparkles
    if sparkle and p >= 1.0:
        for k in range(8):
            ang = k * 2.399
            rr = R * (1.55 + 0.30 * ((k * 5) % 3))
            x = bx + rr * math.cos(ang)
            y = by + rr * math.sin(ang) * 0.9
            sz = star * (0.9 + 1.1 * (0.5 + 0.5 * math.sin(t * 4.0 + k * 1.7)))
            pts = []
            for i in range(8):
                rad = sz if i % 2 == 0 else sz * 0.26
                th = i * math.pi / 4
                pts.append((x + rad * math.cos(th), y + rad * math.sin(th)))
            poly(pts, (255, 236, 214))

    if ss > 1:
        res = getattr(Image, "Resampling", Image).LANCZOS
        img = img.resize((width, h), res)
    return img


# ----------------------------------------------------------------------
# Terminal: transparent image -> truecolor half-block lines
# ----------------------------------------------------------------------
def to_halfblocks(img, color=True, thr=90):
    px = img.load()
    w, h = img.size
    lines = []
    for y in range(0, h - 1, 2):
        out = []
        for x in range(w):
            r1, g1, b1, a1 = px[x, y]
            r2, g2, b2, a2 = px[x, y + 1]
            top, bot = a1 >= thr, a2 >= thr
            if not color:
                out.append("█" if top and bot else "▀" if top else "▄" if bot else " ")
            elif top and bot:
                out.append(f"\033[38;2;{r1};{g1};{b1};48;2;{r2};{g2};{b2}m▀")
            elif top:
                out.append(f"\033[0;38;2;{r1};{g1};{b1}m▀")
            elif bot:
                out.append(f"\033[0;38;2;{r2};{g2};{b2}m▄")
            else:
                out.append("\033[0m ")
        out.append("\033[0m")
        lines.append("".join(out))
    return lines


def rgb(text, color, bold=False):
    if not USE_COLOR:
        return text
    return f"\033[{'1;' if bold else ''}38;2;{color[0]};{color[1]};{color[2]}m{text}\033[0m"


def bubble_text(pct, mood):
    """Short speech for the mascot (max 11 characters)."""
    if mood == "happy":
        return "Ta-da!"
    if mood == "sad":
        return "Oops..."
    if pct < 15:
        return "Planting..."
    if pct < 40:
        return "Growing..."
    if pct < 65:
        return "Budding..."
    if pct < 90:
        return "Almost!"
    return "Blooming..."


# ----------------------------------------------------------------------
# Live scene: mascot + rose + percentage (redraws in place)
# ----------------------------------------------------------------------
class Scene:
    def __init__(self):
        self.live = LIVE
        cols, rows = shutil.get_terminal_size((44, 30))
        self.cols = cols
        self.show_mascot = cols >= 40
        cw = cols - (11 + 3 + 1) if self.show_mascot else cols - 1
        cw = max(16, min(30, cw))
        max_pix = max(20, (rows - 8) * 2)
        if round(1.35 * cw) > max_pix:
            cw = max(14, int(max_pix / 1.35))
        self.cw = cw
        self.pct = 0.0
        self.target = 0.0
        self.label = ""
        self.mood = "work"
        self.tick = 0
        self.done_tick = None
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self.thread = None
        self.drawn = False
        self._milestone = -1

    def start(self):
        if self.live:
            sys.stdout.write("\033[?25l")
            sys.stdout.flush()
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def set(self, pct, label=""):
        pct = max(0.0, min(100.0, pct))
        with self.lock:
            if pct > self.target:
                self.target = pct
            if label:
                self.label = label
        if not self.live:
            m = int(pct // 20)
            if m > self._milestone:
                self._milestone = m
                say(f"   {int(pct)}%  {label}")

    def note(self, text):
        with self.lock:
            self.label = text

    def frame(self):
        pct, tick, mood = self.pct, self.tick, self.mood
        p = pct / 100.0
        fall = 0.0
        if mood == "happy" and self.done_tick is not None:
            fall = max(0.0, (tick - self.done_tick) * 0.12 - 0.4)
        img = render_rose(p, t=tick * 0.12, width=self.cw, ss=4,
                          fall=fall, sparkle=(p >= 1.0), star=2.6)
        rose = to_halfblocks(img, color=USE_COLOR)
        R = len(rose)
        mas = mascot_rows(tick, mood)
        top = max(0, R - len(mas))
        lines = []
        for r in range(R):
            right = ""
            if self.show_mascot:
                k = r - top
                if 0 <= k < len(mas):
                    right = mas[k]
                elif r == top - 1:
                    right = paint(bubble_text(pct, mood).center(11), BOLD)
            lines.append(rose[r] + "   " + right)
        txt = f" {int(pct)}% "
        left = (self.cw - len(txt)) // 2
        lines.append(rgb("─" * left, (130, 56, 78))
                     + rgb(txt, (255, 140, 172), True)
                     + rgb("─" * (self.cw - len(txt) - left), (130, 56, 78)))
        f = int(self.cw * pct / 100)
        lines.append(rgb("━" * f, (255, 112, 152))
                     + rgb("─" * (self.cw - f), (86, 52, 64)))
        lines.append(paint(self.label[: max(10, min(60, self.cols - 2))], DIM))
        return lines

    def _draw(self):
        lines = self.frame()
        out = []
        if self.drawn:
            out.append(f"\033[{len(lines)}A")
        for ln in lines:
            out.append("\r\033[2K" + ln + "\n")
        sys.stdout.write("".join(out))
        sys.stdout.flush()
        self.drawn = True

    def _loop(self):
        while not self._stop.is_set():
            with self.lock:
                d = self.target - self.pct
                self.pct = self.target if abs(d) < 0.5 else self.pct + d * 0.35
                try:
                    self._draw()
                except Exception:
                    pass
                self.tick += 1
            time.sleep(0.12)

    def finish(self, ok):
        if not self.live:
            if ok:
                say("   100%  done")
            return
        self._stop.set()
        if self.thread:
            self.thread.join()
        with self.lock:
            if ok:
                self.pct = self.target = 100.0
                self.done_tick = self.tick
            self.mood = "happy" if ok else "sad"
            self.label = "Saved!" if ok else "Something went wrong"
        for _ in range(16 if ok else 1):
            with self.lock:
                try:
                    self._draw()
                except Exception:
                    pass
                self.tick += 1
            time.sleep(0.12)
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


SCENE = None


PROGRESS_SPAN = (0.0, 100.0)


def progress(pct, label=""):
    if SCENE:
        lo, hi = PROGRESS_SPAN
        SCENE.set(lo + (hi - lo) * pct / 100.0, label)


def note(msg):
    if SCENE:
        SCENE.note(msg)
    else:
        say(paint("   " + msg, DIM))


def run_job(fn, *args):
    """Run one capture/record job while the rose grows on screen."""
    global SCENE
    scene = Scene()
    SCENE = scene
    scene.start()
    ok = False
    try:
        result = fn(*args)
        ok = True
        return result
    finally:
        scene.finish(ok)
        SCENE = None


def banner():
    side = {
        1: paint("SnapForge", BOLD, YELLOW),
        2: "shots + scroll videos",
        3: paint("made for Termux", DIM),
    }
    say()
    if not LIVE:
        for i, row in enumerate(mascot_rows(0, "ready")):
            say("  " + row + "   " + side.get(i, ""))
    else:
        sys.stdout.write("\033[?25l")
        try:
            for t in range(18):
                rows = mascot_rows(t * 2, "ready")
                out = []
                if t:
                    out.append(f"\033[{len(rows)}A")
                for i, row in enumerate(rows):
                    out.append("\r\033[2K  " + row + "   " + side.get(i, "") + "\n")
                sys.stdout.write("".join(out))
                sys.stdout.flush()
                time.sleep(0.1)
        finally:
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
    say()
    talk("ready", "Hi! Give me a link, I'll do the rest.")


# ----------------------------------------------------------------------
# Setup
# ----------------------------------------------------------------------
def run_setup():
    cmds = [
        "pkg update -y",
        "pkg install -y x11-repo",
        "pkg install -y tur-repo",
        "pkg install -y python-pillow",
        "pkg install -y chromium",
        "pkg install -y ffmpeg",
        f"{sys.executable} -m pip install websocket-client",
        "termux-setup-storage",
    ]
    for c in cmds:
        say("\n" + paint(">>> " + c, YELLOW))
        subprocess.call(c, shell=True)
    talk("happy", "Setup finished. Now run:  python shot.py", GREEN)


# ----------------------------------------------------------------------
# Minimal Chrome DevTools client
# ----------------------------------------------------------------------
class Chrome:
    def __init__(self):
        try:
            import websocket
        except ImportError:
            talk("sad", "Missing 'websocket-client'. Run: python shot.py --setup", RED)
            sys.exit(1)
        self.websocket = websocket

        binary = None
        for n in ("chromium-browser", "chromium", "chrome"):
            binary = shutil.which(n)
            if binary:
                break
        if not binary:
            talk("sad", "Chromium not found. Run: python shot.py --setup", RED)
            sys.exit(1)

        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        self.tmp = tempfile.mkdtemp(prefix="shot_")
        self.proc = subprocess.Popen(
            [binary, "--headless=new", "--no-sandbox", "--disable-gpu",
             "--enable-unsafe-swiftshader",
             "--disable-dev-shm-usage", "--hide-scrollbars",
             "--no-first-run", "--ignore-certificate-errors",
             "--disk-cache-size=1", "--media-cache-size=1",
             "--autoplay-policy=no-user-gesture-required",
             "--disable-background-timer-throttling",
             "--disable-renderer-backgrounding",
             "--disable-backgrounding-occluded-windows",
             "--remote-allow-origins=*",
             f"--remote-debugging-port={port}",
             f"--user-data-dir={self.tmp}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                    for t in json.load(r):
                        if t.get("type") == "page":
                            ws_url = t["webSocketDebuggerUrl"]
                            break
                if ws_url:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ws_url:
            self.close()
            talk("sad", "Could not start Chromium.", RED)
            sys.exit(1)

        self.ws = websocket.create_connection(
            ws_url, timeout=120, suppress_origin=True)
        self.n = 0
        self.events = []

    def send(self, method, params=None):
        self.n += 1
        mid = self.n
        self.ws.send(json.dumps(
            {"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})
            if "method" in msg:
                self.events.append(msg["method"])

    def wait_event(self, name, timeout=60):
        end = time.time() + timeout
        self.ws.settimeout(2)
        try:
            while time.time() < end:
                if name in self.events:
                    return True
                try:
                    msg = json.loads(self.ws.recv())
                    if "method" in msg:
                        self.events.append(msg["method"])
                except self.websocket.WebSocketTimeoutException:
                    pass
        finally:
            self.ws.settimeout(120)
        return False

    def js(self, expr):
        r = self.send("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True})
        return r.get("result", {}).get("value")

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
JS_EAGER = ("document.querySelectorAll('img[loading=lazy]')"
            ".forEach(function(i){i.loading='eager'});")
JS_FORCE_REVEAL = (
    "var s=document.createElement('style');s.textContent="
    "'[data-aos],.wow,.reveal,.fade-in,.animate-on-scroll,.scroll-reveal"
    "{opacity:1!important;visibility:visible!important;transform:none!important}';"
    "document.head.appendChild(s);")
JS_HIDE_FIXED = (
    "document.querySelectorAll('*').forEach(function(e){"
    "var p=getComputedStyle(e).position;"
    "if(p==='fixed'||p==='sticky'){e.style.setProperty('visibility','hidden','important');}"
    "});")


_PASTE_JUNK = ("\x1b[200~", "\x1b[201~", "^[[200~", "^[[201~", "[200~", "[201~")


def normalize_url(raw):
    """Clean up a pasted link: hidden characters, spaces, quotes, <...>."""
    url = raw or ""
    for junk in _PASTE_JUNK:
        url = url.replace(junk, "")
    url = "".join(ch for ch in url if ch.isprintable() and not ch.isspace())
    url = url.strip("<>\"'`,;")
    if not url:
        return ""
    if "://" not in url:
        local = url.lower().startswith(("localhost", "127.0.0.1", "192.168."))
        url = ("http://" if local else "https://") + url
    return url


def url_problem(url):
    """None if the link looks usable, otherwise a short explanation."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return "Only http:// and https:// links work."
    host = (p.hostname or "")
    if not host:
        return "That doesn't look like a website address."
    if "." not in host and host != "localhost":
        return f"'{host}' doesn't look like a website. Try something like example.com"
    return None


def ask_url(text):
    """Ask until the link is usable. Empty answer = quit."""
    while True:
        url = normalize_url(ask(text))
        if not url:
            return ""
        problem = url_problem(url)
        if not problem:
            return url
        talk("sad", problem, RED)


def output_dir():
    shared = os.path.expanduser("~/storage/shared/Pictures")
    base = shared if os.path.isdir(shared) else os.getcwd()
    d = os.path.join(base, "WebShots")
    os.makedirs(d, exist_ok=True)
    return d


def where_saved(folder):
    shared = os.path.expanduser("~/storage/shared/Pictures")
    if folder.startswith(shared):
        return "Gallery > WebShots"
    return folder


def storage_hint(folder):
    shared = os.path.expanduser("~/storage/shared/Pictures")
    if not folder.startswith(shared):
        say(paint("   Tip: run  termux-setup-storage  once, then your files "
                  "show up in the Gallery.", DIM))


def go(c, url, event="Page.loadEventFired", timeout=60):
    """Open a page; fail with a clear message if the address can't be reached."""
    c.events.clear()
    res = c.send("Page.navigate", {"url": url})
    err = res.get("errorText") if isinstance(res, dict) else None
    if err:
        raise RuntimeError(f"Could not open the page ({err.replace('net::', '')}). "
                           "Check the link and your internet.")
    c.wait_event(event, timeout)


def page_height(c):
    return int(c.js(
        "Math.max(document.body?document.body.scrollHeight:0,"
        "document.documentElement.scrollHeight,"
        "document.documentElement.offsetHeight)") or 0)


def scroll_to_load(c, vh, delay):
    """Scroll down slowly so lazy content and scroll animations fire."""
    y = 0
    for _ in range(300):
        h = min(page_height(c), MAX_PAGE_CSS_HEIGHT)
        if y >= h:
            break
        progress(5 + 10 * min(1.0, y / max(h, 1)), "scrolling page to load it...")
        c.js(f"window.scrollTo({{top:{y},left:0,behavior:'instant'}})")
        time.sleep(delay)
        y += int(vh * 0.6)
    time.sleep(1.5)
    c.js("window.scrollTo({top:0,left:0,behavior:'instant'})")
    time.sleep(1.0)


def set_metrics(c, w, vh, dpr, mobile):
    c.send("Emulation.setDeviceMetricsOverride", {
        "width": w, "height": vh, "deviceScaleFactor": dpr,
        "mobile": mobile, "screenWidth": w, "screenHeight": vh})


def prepare(c, url, prof, dpr, mobile, delay):
    """Device emulation, open page, trigger lazy content and animations."""
    w, vh = prof["width"], prof["height"]
    progress(1, "opening page...")
    set_metrics(c, w, vh, dpr, mobile)
    c.send("Emulation.setUserAgentOverride", {"userAgent": prof["ua"]})
    if mobile:
        c.send("Emulation.setTouchEmulationEnabled",
               {"enabled": True, "maxTouchPoints": 5})
    else:
        c.send("Emulation.setTouchEmulationEnabled", {"enabled": False})
    try:
        c.send("Emulation.setEmulatedMedia", {"features": [
            {"name": "prefers-reduced-motion", "value": "no-preference"}]})
    except Exception:
        pass

    c.send("Page.enable")
    go(c, url)
    progress(4, "page loaded, waiting a moment...")
    time.sleep(3)
    c.js(JS_EAGER)
    scroll_to_load(c, vh, delay)
    progress(15, "ready to capture")
    return min(max(page_height(c), vh), MAX_PAGE_CSS_HEIGHT)


def shrink_dpr(w, height, dpr):
    while (w * dpr) * (height * dpr) > MAX_TOTAL_PIXELS and dpr > 1:
        dpr = round(dpr - 0.25, 2)
        note(f"page is very long, sharpness lowered to {dpr}x")
    return dpr


# ----------------------------------------------------------------------
# Saving (and keeping storage small)
# ----------------------------------------------------------------------


def save_image(img, base, fmt):
    """JPG is roughly 5-8x smaller than PNG with almost no visible loss."""
    if fmt == "jpg" and max(img.size) <= 65000:
        path = base + ".jpg"
        img.save(path, "JPEG", quality=95, subsampling=0)
    else:
        path = base + ".png"
        img.save(path, "PNG", compress_level=4)
    return path


def dir_size(path):
    total, n = 0, 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
                n += 1
            except OSError:
                pass
    return total, n


def clean_stale(max_age=3600):
    """Delete leftover temp folders from crashed or cancelled runs."""
    freed = 0
    tmp = tempfile.gettempdir()
    now = time.time()
    try:
        names = os.listdir(tmp)
    except OSError:
        return 0
    for name in names:
        if name.startswith(("shot_", "frames_", "reel_")):
            pth = os.path.join(tmp, name)
            try:
                if now - os.path.getmtime(pth) >= max_age:
                    freed += dir_size(pth)[0]
                    shutil.rmtree(pth, ignore_errors=True)
            except OSError:
                pass
    return freed


def enough_space(folder, need_mb=400):
    free = shutil.disk_usage(folder).free / 1048576
    if free < need_mb:
        talk("sad", f"Only {free:.0f} MB free. Free some space first "
                    "(python shot.py --clean).", RED)
        return False
    return True


def run_clean():
    heading("Cleaning up")
    talk("work", "Sweeping leftovers...", YELLOW)
    freed = clean_stale(0)
    say(f"   {paint('✔', GREEN)} leftover temp files removed: {freed / 1048576:.0f} MB")
    for cmd in ("pkg clean", f"{sys.executable} -m pip cache purge"):
        subprocess.call(cmd, shell=True, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
    say(f"   {paint('✔', GREEN)} package download caches cleared")
    folder = output_dir()
    total, n = dir_size(folder)
    free = shutil.disk_usage(folder).free / 1048576
    say(f"   {paint('•', CYAN)} WebShots folder: {n} files, {total / 1048576:.0f} MB")
    say(f"   {paint('•', CYAN)} free space on phone: {free:.0f} MB")
    talk("happy", f"Delete old files in {where_saved(folder)} to free more.", GREEN)


# ----------------------------------------------------------------------
# Video frames go straight into ffmpeg (nothing is written to storage)
# ----------------------------------------------------------------------
def open_ffmpeg(out_path, fps, crf, preset="veryfast", codec="mjpeg"):
    """Frames are fed through a pipe. The colour tags matter: without them
    phones and editors guess the wrong colour matrix and colours shift."""
    vf = ("scale=trunc(iw/2)*2:trunc(ih/2)*2:flags=lanczos+accurate_rnd+full_chroma_int"
          ":in_color_matrix=bt601:out_color_matrix=bt709:out_range=tv,format=yuv420p")
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "image2pipe", "-framerate", str(fps), "-c:v", codec, "-i", "-",
           "-vf", vf,
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
           "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-colorspace", "bt709", "-color_primaries", "bt709",
           "-color_trc", "bt709", "-color_range", "tv",
           "-movflags", "+faststart", out_path]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)


def pipe_write(proc, data, times=1):
    try:
        for _ in range(times):
            proc.stdin.write(data)
    except (BrokenPipeError, OSError):
        err = proc.stderr.read().decode(errors="ignore").strip()[-300:]
        raise RuntimeError("ffmpeg stopped: " + err)


def close_ffmpeg(proc):
    try:
        proc.stdin.close()
    except OSError:
        pass
    err = proc.stderr.read().decode(errors="ignore").strip()[-300:]
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed: " + err)


def kill_ffmpeg(proc):
    try:
        proc.kill()
        proc.wait(timeout=5)
    except Exception:
        pass


_FAST_SHOT = [True]
JS_NO_SNAP = ("var s=document.createElement('style');s.textContent="
              "'html,body,*{scroll-snap-type:none!important;"
              "scroll-behavior:auto!important}';"
              "if(document.head)document.head.appendChild(s);")
JS_FRAME = ("new Promise(function(r){var d=false;function f(){if(!d){d=true;r(1);}}"
            "requestAnimationFrame(function(){requestAnimationFrame(f);});"
            "setTimeout(f,300);})")


JS_VIDEO_SETUP = (
    "(function(){if(window.__sfSeek)return document.querySelectorAll('video').length;"
    "var recs=new Map();"
    "HTMLMediaElement.prototype.play=function(){try{this.pause();}catch(e){}"
    "return Promise.resolve();};"
    "window.__sfSeek=function(sec){"
    "var vs=Array.prototype.slice.call(document.querySelectorAll('video'));"
    "return Promise.all(vs.map(function(v){return new Promise(function(res){"
    "var d=v.duration;if(!isFinite(d)||d<=0){res(0);return;}"
    "var r=recs.get(v);"
    "if(!r){r={base:v.currentTime||0,start:sec};recs.set(v,r);try{v.pause();}catch(e){}}"
    "var t=r.base+(sec-r.start);"
    "t=v.loop?(t%d):Math.min(t,d-0.05);"
    "if(Math.abs(v.currentTime-t)<0.0005){res(1);return;}"
    "var done=false;function fin(){if(!done){done=true;"
    "v.removeEventListener('seeked',fin);res(1);}}"
    "v.addEventListener('seeked',fin);setTimeout(fin,400);"
    "try{v.currentTime=t;}catch(e){fin();}"
    "});}));};"
    "return document.querySelectorAll('video').length;})()")


def seek_videos(c, sec):
    """Put every <video> on the page at the exact moment this frame represents.

    Without this, a background video keeps playing in real time while each
    recorded frame takes longer than 1/30 s to grab, so it looks sped up."""
    try:
        r = c.send("Runtime.evaluate", {"expression": f"window.__sfSeek({sec:.4f})",
                                        "awaitPromise": True, "returnByValue": True})
        v = r.get("result", {}).get("value")
        return len(v) if isinstance(v, list) else 0
    except Exception:
        return 0


def wait_frame(c):
    """Wait until the browser has really painted the new scroll position."""
    try:
        c.send("Runtime.evaluate", {"expression": JS_FRAME,
                                    "awaitPromise": True, "returnByValue": True})
    except Exception:
        time.sleep(0.08)


def grab_frame(c, fmt="jpeg", quality=92):
    params = {"format": fmt, "fromSurface": True}
    if fmt == "jpeg":
        params["quality"] = quality
    if _FAST_SHOT[0]:
        params["optimizeForSpeed"] = True
    try:
        res = c.send("Page.captureScreenshot", params)
    except RuntimeError:
        if not _FAST_SHOT[0]:
            raise
        _FAST_SHOT[0] = False                 # older Chromium: retry without it
        params.pop("optimizeForSpeed", None)
        res = c.send("Page.captureScreenshot", params)
    return base64.b64decode(res["data"])


# ----------------------------------------------------------------------
# Screenshot: smart (animations play) and fast
# ----------------------------------------------------------------------
def capture_smart(c, url, prof, dpr, mobile, out_base, settle, fmt, pause=0.0):
    """Scrolls section by section so scroll-animations really play."""
    from PIL import Image

    w, vh = prof["width"], prof["height"]
    height = prepare(c, url, prof, dpr, mobile, max(0.4, settle * 0.6))
    dpr = shrink_dpr(w, height, dpr)
    set_metrics(c, w, vh, dpr, mobile)
    time.sleep(1)
    if pause > 0:                       # fresh reload: let the intro play, then shoot
        progress(15, f"waiting {pause:g}s at the top for the intro...")
        go(c, url)
        time.sleep(pause)
        height = max(height, min(page_height(c), MAX_PAGE_CSS_HEIGHT))

    max_scroll = max(0, height - vh)
    positions = list(range(0, max_scroll, vh)) + [max_scroll]
    total_w, total_h = int(round(w * dpr)), int(round(height * dpr))
    canvas = Image.new("RGB", (total_w, total_h), "white")

    for i, y in enumerate(positions):
        c.js(f"window.scrollTo({{top:{y},left:0,behavior:'instant'}})")
        time.sleep(settle)
        actual = c.js("window.scrollY") or 0
        res = c.send("Page.captureScreenshot",
                     {"format": "png", "fromSurface": True})
        img = Image.open(io.BytesIO(base64.b64decode(res["data"]))).convert("RGB")
        canvas.paste(img, (0, int(round(actual * dpr))))
        img.close()
        if i == 0:
            c.js(JS_HIDE_FIXED)       # sticky bars only once, not on every slice
        progress(15 + 83 * (i + 1) / len(positions),
                 f"capturing section {i + 1}/{len(positions)}")

    progress(98, "saving image...")
    path = save_image(canvas, out_base, fmt)
    canvas.close()
    return total_w, total_h, path


def capture_fast(c, url, prof, dpr, mobile, out_base, settle, fmt, pause=0.0):
    """Quick whole-page capture (some scroll animations may stay hidden)."""
    from PIL import Image

    w, vh = prof["width"], prof["height"]
    height = prepare(c, url, prof, dpr, mobile, 0.35)
    c.js(JS_FORCE_REVEAL)
    dpr = shrink_dpr(w, height, dpr)
    set_metrics(c, w, vh, dpr, mobile)
    time.sleep(1)

    chunk_css = max(500, int(CHUNK_DEVICE_PX / dpr))
    total_w, total_h = int(round(w * dpr)), int(round(height * dpr))
    canvas = Image.new("RGB", (total_w, total_h), "white")

    y, n = 0, 0
    parts = (height + chunk_css - 1) // chunk_css
    while y < height:
        h = min(chunk_css, height - y)
        n += 1
        res = c.send("Page.captureScreenshot", {
            "format": "png", "captureBeyondViewport": True,
            "fromSurface": True,
            "clip": {"x": 0, "y": y, "width": w, "height": h, "scale": 1}})
        img = Image.open(io.BytesIO(base64.b64decode(res["data"]))).convert("RGB")
        canvas.paste(img, (0, int(round(y * dpr))))
        img.close()
        progress(15 + 83 * n / parts, f"capturing part {n}/{parts}")
        y += h

    progress(98, "saving image...")
    path = save_image(canvas, out_base, fmt)
    canvas.close()
    return total_w, total_h, path


# ----------------------------------------------------------------------
# Scrolling video (intro is filmed live, then the page scrolls)
# ----------------------------------------------------------------------
def film_page(c, url, prof, dpr, mobile, speed, intro, sink, max_secs=None,
              shot=("jpeg", 92)):
    """Warm up, reload, film the intro live, then scroll the page.

    Every frame goes to sink(jpeg_bytes, times). Returns the frame count."""
    vh = prof["height"]
    # 1) warm-up pass: load every image / lazy section once
    height = prepare(c, url, prof, dpr, mobile, 0.5)
    max_scroll = max(0, height - vh)
    if max_scroll and max_secs:
        speed = max(speed, max_scroll / max_secs)      # keep long pages short
    step = speed / VIDEO_FPS
    moving = int(math.ceil(max_scroll / step)) + 1 if max_scroll else 1
    est = intro + moving / VIDEO_FPS + HOLD_FRAMES / VIDEO_FPS
    note(f"video will be about {est:.0f}s long")

    frames = 0
    # 2) fresh reload, so the intro animations play on camera
    progress(16, "reloading the page to film its intro...")
    go(c, url, "Page.domContentEventFired", 20)
    t0 = time.time()
    written = 0
    while intro > 0:
        data = grab_frame(c, *shot)
        el = time.time() - t0
        n = int(round(el * VIDEO_FPS)) - written            # keeps real-time pace
        if written == 0:
            n = max(n, 1)
        if n > 0:
            sink(data, n)
            written += n
        progress(16 + 4 * min(1.0, el / intro), "filming the intro animation...")
        if el >= intro:
            break
    frames += written

    # 3) scroll down, one exact step per frame
    c.js(JS_NO_SNAP)                    # sites with scroll-snap would make it jump
    nvid = c.js(JS_VIDEO_SETUP) or 0    # background videos: step them with the frames
    if nvid:
        note(f"syncing {nvid} background video(s) to the recording")
    ts0 = time.time()
    rate_done = False
    last = None
    for i in range(moving):
        y = min(max_scroll, i * step)
        y = round(y * dpr) / dpr        # land exactly on a screen pixel: even steps
        c.js(f"window.scrollTo({{top:{y:.4f},left:0,behavior:'instant'}})")
        if nvid or i % 15 == 0:         # (videos can also appear later on the page)
            nvid = seek_videos(c, i / VIDEO_FPS)
        wait_frame(c)
        last = grab_frame(c, *shot)
        sink(last, 1)
        frames += 1
        if i == 8 and not rate_done:
            # our frames take longer than 1/30 s to grab: slow the page's
            # CSS animations by the same factor so they keep their pace
            avg = (time.time() - ts0) / 9
            if avg > 1.5 / VIDEO_FPS:
                try:
                    c.send("Animation.setPlaybackRate",
                           {"playbackRate": max(0.05, (1.0 / VIDEO_FPS) / avg)})
                except Exception:
                    pass
            rate_done = True
        if i % 5 == 0 or i == moving - 1:
            progress(20 + 75 * (i + 1) / moving,
                     f"recording frame {i + 1}/{moving}")
    sink(last, HOLD_FRAMES)
    frames += HOLD_FRAMES
    return frames


def record(c, url, prof, dpr, mobile, speed, out_path, intro, vq):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg missing. Run: pkg install ffmpeg")
    proc = open_ffmpeg(out_path, VIDEO_FPS, vq["crf"], vq["preset"],
                       "png" if vq["fmt"] == "png" else "mjpeg")
    try:
        frames = film_page(c, url, prof, dpr, mobile, speed, intro,
                           lambda data, n: pipe_write(proc, data, n),
                           shot=(vq["fmt"], vq["q"]))
        progress(96, "finishing video...")
        close_ffmpeg(proc)
    except BaseException:
        kill_ffmpeg(proc)
        raise
    return frames / VIDEO_FPS


# ----------------------------------------------------------------------
# Laptop & phone mockups
# ----------------------------------------------------------------------
MOCK_DESKTOP = {"width": 1440, "height": 900, "ua": DESKTOP["ua"]}
MOCK_DPR = {"standard": (1.5, 2.0), "high": (2.0, 3.0), "ultra": (2.0, 3.0)}
THEMES = {
    "midnight": ((12, 14, 30), (46, 30, 84), (120, 90, 255)),
    "rose":     ((24, 6, 18), (96, 20, 54), (255, 90, 140)),
    "ocean":    ((6, 28, 48), (16, 104, 128), (70, 220, 230)),
    "light":    ((240, 242, 248), (206, 214, 234), (255, 255, 255)),
    "greenscreen": ((0, 255, 0), (0, 255, 0), (0, 255, 0)),   # pure chroma green
}
LAYOUTS = {"both": ["both"], "laptop": ["laptop"], "phone": ["phone"],
           "all": ["both", "laptop", "phone"]}


def _res():
    from PIL import Image
    return getattr(Image, "Resampling", Image).LANCZOS


def _gradient(w, h, c1, c2):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=_mix(c1, c2, y / max(1, h - 1)))
    return im


def _mask(w, h, r, top_square=False):
    from PIL import Image, ImageDraw
    k = 4
    r = max(1, min(int(r), min(w, h) // 2))
    m = Image.new("L", (w * k, h * k), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, w * k - 1, h * k - 1], radius=r * k, fill=255)
    if top_square:
        d.rectangle([0, 0, w * k - 1, h * k // 2], fill=255)
    return m.resize((w, h), _res())


def _paste_rr(canvas, x, y, src, r):
    canvas.paste(src, (int(x), int(y)), _mask(src.width, src.height, r))


def _fill_rr(canvas, x, y, w, h, r, fill):
    from PIL import Image
    _paste_rr(canvas, x, y, Image.new("RGB", (int(w), int(h)), fill), r)


SHADOWS_ON = True


def _shadow(canvas, x, y, w, h, r, blur, dy, alpha):
    if not SHADOWS_ON:
        return
    from PIL import Image, ImageDraw, ImageFilter
    pad = int(blur * 3)
    m = Image.new("L", (int(w) + 2 * pad, int(h) + 2 * pad), 0)
    ImageDraw.Draw(m).rounded_rectangle(
        [pad, pad, pad + int(w), pad + int(h)], radius=int(r), fill=alpha)
    m = m.filter(ImageFilter.GaussianBlur(blur))
    canvas.paste(Image.new("RGB", m.size, (0, 0, 0)),
                 (int(x) - pad, int(y) - pad + int(dy)), m)


def laptop_dims(sw, aspect):
    sh = int(round(sw * aspect))
    bs, bt, bb = int(sw * 0.018), int(sw * 0.024), int(sw * 0.018)
    lid_w, lid_h = sw + 2 * bs, sh + bt + bb
    base_w, base_h = int(lid_w * 1.08), max(10, int(sw * 0.020))
    return {"sh": sh, "bs": bs, "bt": bt, "bb": bb, "lid_w": lid_w, "lid_h": lid_h,
            "base_w": base_w, "base_h": base_h, "w": base_w, "h": lid_h + base_h}


def draw_laptop(canvas, shot, x, y, sw):
    from PIL import ImageDraw
    L = laptop_dims(sw, shot.height / shot.width)
    lx = x + (L["base_w"] - L["lid_w"]) // 2
    r = int(sw * 0.024)
    _shadow(canvas, x, y + L["lid_h"] * 0.1, L["base_w"],
            L["lid_h"] * 0.9 + L["base_h"], r, sw * 0.03, sw * 0.035, 150)
    _fill_rr(canvas, lx - 2, y - 2, L["lid_w"] + 4, L["lid_h"] + 4, r + 2, (74, 74, 82))
    _fill_rr(canvas, lx, y, L["lid_w"], L["lid_h"], r, (12, 12, 16))
    scr = shot.resize((sw, L["sh"]), _res())
    _paste_rr(canvas, lx + L["bs"], y + L["bt"], scr, sw * 0.008)
    d = ImageDraw.Draw(canvas)
    cr = max(2, int(sw * 0.0032))
    cx, cy = lx + L["lid_w"] // 2, y + L["bt"] // 2
    d.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=(40, 40, 52))
    by = y + L["lid_h"] - 1
    base = _gradient(L["base_w"], L["base_h"], (224, 226, 232), (156, 160, 170))
    canvas.paste(base, (x, by),
                 _mask(L["base_w"], L["base_h"], L["base_h"], top_square=True))
    nw, nh = int(L["base_w"] * 0.15), max(3, int(L["base_h"] * 0.5))
    _fill_rr(canvas, x + (L["base_w"] - nw) // 2, by, nw, nh, nh, (150, 154, 164))
    L.update(sx=lx + L["bs"], sy=y + L["bt"], sw=sw, sr=int(sw * 0.008))
    return L


def phone_dims(sh, aspect):
    sw = int(round(sh * aspect))
    bez = max(6, int(sh * 0.012))
    return {"sw": sw, "bez": bez, "w": sw + 2 * bez, "h": sh + 2 * bez}


def draw_phone(canvas, shot, x, y, sh):
    from PIL import ImageDraw
    P = phone_dims(sh, shot.width / shot.height)
    sw, bez, bw, bh = P["sw"], P["bez"], P["w"], P["h"]
    r = int(sw * 0.17)
    _shadow(canvas, x, y, bw, bh, r, sh * 0.035, sh * 0.03, 175)
    d = ImageDraw.Draw(canvas)
    bt = max(3, int(sh * 0.005))
    for yy, hh in ((0.17, 0.035), (0.23, 0.065), (0.31, 0.065)):
        d.rectangle([x - bt, y + int(sh * yy), x + 2, y + int(sh * (yy + hh))],
                    fill=(54, 54, 60))
    d.rectangle([x + bw - 2, y + int(sh * 0.26), x + bw + bt, y + int(sh * 0.36)],
                fill=(54, 54, 60))
    e = max(2, int(sh * 0.004))
    _fill_rr(canvas, x, y, bw, bh, r, (104, 104, 112))
    _fill_rr(canvas, x + e, y + e, bw - 2 * e, bh - 2 * e, r - e, (8, 8, 10))
    scr = shot.resize((sw, sh), _res())
    _paste_rr(canvas, x + bez, y + bez, scr, r * 0.82)
    iw, ih = int(sw * 0.28), int(sw * 0.078)
    ix, iy = x + bez + (sw - iw) // 2, y + bez + int(sw * 0.032)
    _fill_rr(canvas, ix, iy, iw, ih, ih // 2, (3, 3, 5))
    P.update(sx=x + bez, sy=y + bez, sh=sh, sr=int(r * 0.82),
             ix=ix, iy=iy, iw=iw, ih=ih)
    return P


def compose_mockup(desk, phone, layout, theme, scale=1.0, overlap=True):
    """Returns (image, geometry of the screens)."""
    from PIL import Image, ImageDraw, ImageFilter, ImageChops
    global SHADOWS_ON
    c1, c2, accent = THEMES[theme]
    base_w, base_h = (1500, 1875) if layout == "phone" else (2400, 1500)
    W, H = int(base_w * scale), int(base_h * scale)
    SHADOWS_ON = theme != "greenscreen"
    if theme == "greenscreen":
        canvas = Image.new("RGB", (W, H), (0, 255, 0))
    else:
        canvas = _gradient(W, H, c1, c2)
        gw, gh = W // 4, H // 4
        glow = Image.new("RGB", (gw, gh), (0, 0, 0))
        ImageDraw.Draw(glow).ellipse([gw * 0.15, gh * 0.10, gw * 0.85, gh * 0.80],
                                     fill=_shade(accent, 0.24))
        glow = glow.filter(ImageFilter.GaussianBlur(30)).resize((W, H), _res())
        canvas = ImageChops.add(canvas, glow)

    geo = {}
    if layout == "both":
        geo["laptop"] = draw_laptop(canvas, desk, int(190 * scale), int(170 * scale),
                                    int(1500 * scale))
        geo["phone"] = draw_phone(canvas, phone,
                                  int((1690 if overlap else 1735) * scale),
                                  int(330 * scale), int(1040 * scale))
    elif layout == "laptop":
        sw = int(1800 * scale)
        L = laptop_dims(sw, desk.height / desk.width)
        geo["laptop"] = draw_laptop(canvas, desk, (W - L["w"]) // 2,
                                    (H - L["h"]) // 2, sw)
    else:
        sh = int(1450 * scale)
        P = phone_dims(sh, phone.width / phone.height)
        geo["phone"] = draw_phone(canvas, phone, (W - P["w"]) // 2,
                                  (H - P["h"]) // 2, sh)
    return canvas, geo


def compose_native(desk, phone, layout, theme):
    """Mockup where every screen is drawn at exactly the captured pixel size,
    on a frame that hugs the devices. Best when you zoom or scale it later."""
    from PIL import Image, ImageDraw, ImageFilter, ImageChops
    global SHADOWS_ON
    c1, c2, accent = THEMES[theme]
    gs = theme == "greenscreen"
    SHADOWS_ON = not gs
    L = P = None
    gap = 0
    if layout in ("laptop", "both"):
        L = laptop_dims(desk.width, desk.height / desk.width)
    if layout in ("phone", "both"):
        P = phone_dims(phone.height, phone.width / phone.height)
    if layout == "laptop":
        cw, ch = L["w"], L["h"]
    elif layout == "phone":
        cw, ch = P["w"], P["h"]
    else:
        gap = int(L["w"] * 0.03)
        cw, ch = L["w"] + gap + P["w"], max(L["h"], P["h"])
    m = max(32, int(ch * (0.02 if gs else 0.07)))
    W, H = (cw + 2 * m) // 2 * 2, (ch + 2 * m) // 2 * 2
    if gs:
        canvas = Image.new("RGB", (W, H), (0, 255, 0))
    else:
        canvas = _gradient(W, H, c1, c2)
        gw, gh = W // 4, H // 4
        glow = Image.new("RGB", (gw, gh), (0, 0, 0))
        ImageDraw.Draw(glow).ellipse([gw * 0.15, gh * 0.10, gw * 0.85, gh * 0.80],
                                     fill=_shade(accent, 0.24))
        glow = glow.filter(ImageFilter.GaussianBlur(30)).resize((W, H), _res())
        canvas = ImageChops.add(canvas, glow)

    geo = {}
    x0 = (W - cw) // 2
    if L:
        geo["laptop"] = draw_laptop(canvas, desk, x0, (H - L["h"]) // 2, desk.width)
    if P:
        px = x0 if layout == "phone" else x0 + L["w"] + gap
        geo["phone"] = draw_phone(canvas, phone, px, (H - P["h"]) // 2, phone.height)
    return canvas, geo


def compose_any(desk, phone, layout, theme, zoom, ld, pd):
    if not zoom:
        return compose_mockup(desk, phone, layout, theme)[0]
    if layout == "both":               # keep both screens inside one reasonable frame
        if desk is not None and ld > 1.5:
            desk = desk.resize((int(1440 * 1.5), int(900 * 1.5)), _res())
        if phone is not None and pd > 2.0:
            phone = phone.resize((int(390 * 2), int(844 * 2)), _res())
    return compose_native(desk, phone, layout, theme)[0]


def capture_view(c, url, prof, dpr, mobile, wait):
    """One clean above-the-fold screenshot, taken after a fresh reload."""
    from PIL import Image
    prepare(c, url, prof, dpr, mobile, 0.4)            # warms images/lazy content
    go(c, url)
    time.sleep(max(1.0, wait))                         # let the intro animation finish
    res = c.send("Page.captureScreenshot", {"format": "png", "fromSurface": True})
    return Image.open(io.BytesIO(base64.b64decode(res["data"]))).convert("RGB")


def make_mockups(c, url, layout, theme, quality, fmt, base, wait, zoom=False):
    layouts = LAYOUTS[layout]
    if theme == "greenscreen":
        fmt = "png"
    need_desk = any(l in ("both", "laptop") for l in layouts)
    need_phone = any(l in ("both", "phone") for l in layouts)
    d_dpr, p_dpr = ZOOM_DPR[quality] if zoom else MOCK_DPR[quality]
    desk = phone = None
    if need_desk:
        desk = capture_view(c, url, MOCK_DESKTOP, d_dpr, False, wait)
        progress(45, "laptop screen captured")
    if need_phone:
        phone = capture_view(c, url, MOBILE, p_dpr, True, wait)
        progress(75, "phone screen captured")
    paths = []
    for i, l in enumerate(layouts):
        progress(80 + 18 * i / len(layouts), f"building the {l} mockup...")
        img = compose_any(desk, phone, l, theme, zoom, d_dpr, p_dpr)
        name = {"both": "laptop_phone", "laptop": "laptop", "phone": "phone"}[l]
        paths.append(save_image(img, f"{base}_mockup_{name}", fmt))
    return paths


def _shrink_image(data, size):
    from PIL import Image
    return Image.open(io.BytesIO(data)).convert("RGB").resize(size, _res())


def _shrink_jpeg(data, size, quality=96):
    buf = io.BytesIO()
    _shrink_image(data, size).save(buf, "JPEG", quality=quality, subsampling=0)
    return buf.getvalue()


def make_mockup_video(c, url, layout, theme, speed, intro, vq, out_path, zoom=False):
    """The page scrolls inside the laptop and/or phone screen.

    One device is streamed straight into ffmpeg; with laptop + phone only the
    (small) phone frames are kept in memory, so long videos stay possible."""
    from PIL import Image
    global PROGRESS_SPAN
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg missing. Run: pkg install ffmpeg")

    gs = theme == "greenscreen"
    crf = min(vq["crf"], 14) if gs else vq["crf"]     # clean green edges
    use_png = vq["fmt"] == "png" or gs                # no JPEG loss in the output
    lap_scale, ph_scale, lap_dpr, ph_dpr = vq["mock"]
    scale = ph_scale if layout == "phone" else lap_scale
    shot = (vq["fmt"], vq["q"])

    if zoom:
        lap_dpr, ph_dpr = vq["zoom"]
        if layout == "both":
            lap_dpr, ph_dpr = min(lap_dpr, 1.5), min(ph_dpr, 2.0)
        blank_d = Image.new("RGB", (int(round(MOCK_DESKTOP["width"] * lap_dpr)),
                                    int(round(MOCK_DESKTOP["height"] * lap_dpr))))
        blank_p = Image.new("RGB", (int(round(MOBILE["width"] * ph_dpr)),
                                    int(round(MOBILE["height"] * ph_dpr))))
        base, geo = compose_native(blank_d, blank_p, layout, theme)
    else:
        blank_d = Image.new("RGB", (MOCK_DESKTOP["width"], MOCK_DESKTOP["height"]))
        blank_p = Image.new("RGB", (MOBILE["width"], MOBILE["height"]))
        base, geo = compose_mockup(blank_d, blank_p, layout, theme, scale, overlap=False)
    for g in geo.values():
        g["mask"] = _mask(g["sw"], g["sh"], g["sr"])
    if "phone" in geo:
        g = geo["phone"]
        g["island"] = Image.new("RGB", (g["iw"], g["ih"]), (3, 3, 5))
        g["imask"] = _mask(g["iw"], g["ih"], g["ih"] // 2)

    sizes = {n: (g["sw"], g["sh"]) for n, g in geo.items()}
    devs = {"laptop": (MOCK_DESKTOP, lap_dpr, False), "phone": (MOBILE, ph_dpr, True)}
    order = [n for n in ("phone", "laptop") if n in geo]   # first one is kept

    def decode(data):
        return Image.open(io.BytesIO(data)).convert("RGB")

    def render(imgs):
        canvas = base.copy()
        for name, g in geo.items():
            canvas.paste(imgs[name], (g["sx"], g["sy"]), g["mask"])
            if name == "phone":
                canvas.paste(g["island"], (g["ix"], g["iy"]), g["imask"])
        buf = io.BytesIO()
        if use_png:
            canvas.save(buf, "PNG", compress_level=1)
        else:
            canvas.save(buf, "JPEG", quality=97, subsampling=0)
        return buf.getvalue()

    def open_out():
        return open_ffmpeg(out_path, VIDEO_FPS, crf, vq["preset"],
                           "png" if use_png else "mjpeg")

    written = [0]
    proc = None
    try:
        if len(order) == 1:
            name = order[0]
            prof, dpr, mob = devs[name]
            proc = open_out()

            def sink(data, n):
                frame = render({name: _shrink_image(data, sizes[name])})
                pipe_write(proc, frame, n)
                written[0] += n

            PROGRESS_SPAN = (0.0, 97.0)
            film_page(c, url, prof, dpr, mob, speed, intro, sink, shot=shot)
        else:
            first, second = order
            stored = []

            def sink1(data, n):
                stored.extend([_shrink_jpeg(data, sizes[first])] * n)

            PROGRESS_SPAN = (0.0, 40.0)
            prof, dpr, mob = devs[first]
            film_page(c, url, prof, dpr, mob, speed, intro, sink1, shot=shot)

            proc = open_out()
            last = [None]

            def sink2(data, n):
                last[0] = _shrink_image(data, sizes[second])
                for _ in range(n):
                    k = written[0]
                    other = decode(stored[min(k, len(stored) - 1)])
                    pipe_write(proc, render({first: other, second: last[0]}))
                    written[0] += 1

            PROGRESS_SPAN = (40.0, 97.0)
            prof, dpr, mob = devs[second]
            film_page(c, url, prof, dpr, mob, speed, intro, sink2, shot=shot)
            while written[0] < len(stored):       # phone page was longer: laptop holds
                other = decode(stored[written[0]])
                pipe_write(proc, render({first: other, second: last[0]}))
                written[0] += 1
        PROGRESS_SPAN = (0.0, 100.0)
        progress(98, "finishing video...")
        close_ffmpeg(proc)
    except BaseException:
        if proc:
            kill_ffmpeg(proc)
        raise
    finally:
        PROGRESS_SPAN = (0.0, 100.0)
    return written[0] / VIDEO_FPS


# ----------------------------------------------------------------------
# Job runner
# ----------------------------------------------------------------------
def process(c, url, kind, o):
    d_dpr, m_dpr = QUALITY[o["quality"]]
    vq = VIDEO_Q[o["quality"]]
    vd_dpr, vm_dpr = vq["dpr"]
    host = urlparse(url).netloc.replace(":", "_") or "site"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = output_dir()
    if not enough_space(folder):
        return
    base = os.path.join(folder, f"{host}_{stamp}")
    shoot = capture_smart if o["anim"] == "smart" else capture_fast
    saved = []

    if kind == "mockup":
        names = {"both": "laptop_phone", "laptop": "laptop", "phone": "phone"}
        if o["media"] in ("photo", "both"):
            heading("Laptop & phone mockups (photo)")
            talk("work", "Setting up the studio...", YELLOW)
            t0 = time.time()
            try:
                paths = run_job(make_mockups, c, url, o["layout"], o["theme"],
                                o["quality"], o["fmt"], base, o["intro"], o["zoom"])
                say(f"   {paint('✔', GREEN)} {len(paths)} mockup photo(s), "
                    f"{time.time() - t0:.0f}s")
                for pth in paths:
                    saved.append((pth, os.path.getsize(pth) / 1024 / 1024))
            except Exception as e:
                talk("sad", f"Failed: {e}", RED)
        if o["media"] in ("video", "both"):
            for l in LAYOUTS[o["layout"]]:
                heading(f"Mockup video: {names[l].replace('_', ' + ')}")
                talk("work", "Rolling camera on the mockup...", YELLOW)
                out = f"{base}_mockup_{names[l]}.mp4"
                t0 = time.time()
                try:
                    secs = run_job(make_mockup_video, c, url, l, o["theme"],
                                   o["speed"], o["intro"], vq, out, o["zoom"])
                    mb = os.path.getsize(out) / 1024 / 1024
                    say(f"   {paint('✔', GREEN)} {secs:.0f}s video, {mb:.1f} MB, "
                        f"{time.time() - t0:.0f}s to make")
                    saved.append((out, mb))
                except Exception as e:
                    talk("sad", f"Failed: {e}", RED)
    else:
        devices = []
        if o["modes"] in ("both", "desktop"):
            devices.append(("desktop", DESKTOP, d_dpr, vd_dpr, False))
        if o["modes"] in ("both", "mobile"):
            devices.append(("mobile", MOBILE, m_dpr, vm_dpr, True))

        for name, prof, dpr, vdpr, is_mobile in devices:
            if kind in ("shot", "both"):
                heading(f"{name.upper()} screenshot")
                talk("work", "Say cheese!", YELLOW)
                t0 = time.time()
                try:
                    w, h, path = run_job(shoot, c, url, prof, dpr, is_mobile,
                                         f"{base}_{name}", o["settle"], o["fmt"],
                                         o["intro"])
                    mb = os.path.getsize(path) / 1024 / 1024
                    say(f"   {paint('✔', GREEN)} {w} x {h} px, {mb:.1f} MB, "
                        f"{time.time() - t0:.0f}s")
                    saved.append((path, mb))
                except Exception as e:
                    talk("sad", f"Failed: {e}", RED)
            if kind in ("video", "both"):
                heading(f"{name.upper()} scrolling video")
                talk("work", "Rolling camera...", YELLOW)
                out = f"{base}_{name}.mp4"
                t0 = time.time()
                try:
                    secs = run_job(record, c, url, prof, vdpr, is_mobile,
                                   o["speed"], out, o["intro"], vq)
                    mb = os.path.getsize(out) / 1024 / 1024
                    say(f"   {paint('✔', GREEN)} {secs:.0f}s video, {mb:.1f} MB, "
                        f"{time.time() - t0:.0f}s to make")
                    saved.append((out, mb))
                except Exception as e:
                    talk("sad", f"Failed: {e}", RED)

    say()
    if saved:
        talk("happy", f"All done! Saved in {where_saved(folder)}:", GREEN)
        for path, mb in saved:
            say(f"   {paint('•', GREEN)} {os.path.basename(path)} "
                + paint(f"({mb:.1f} MB)", DIM))
        storage_hint(folder)
    else:
        talk("sad", "Nothing was saved this time.", RED)


# ----------------------------------------------------------------------
# Instagram reel frames
# ----------------------------------------------------------------------
REEL_W, REEL_H = 1080, 1920
PLANT_PX_W = 1000
PLANT_X, PLANT_Y = 40, 70

SANS_FONTS = [
    "/system/fonts/Roboto-Light.ttf", "/system/fonts/Roboto-Regular.ttf",
    "/system/fonts/RobotoStatic-Regular.ttf", "/system/fonts/NotoSans-Regular.ttf",
    "/system/fonts/DroidSans.ttf",
    "/usr/share/fonts/truetype/google-fonts/Poppins-Light.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def load_font(size):
    from PIL import ImageFont
    prefix = os.environ.get("PREFIX", "")
    cands = SANS_FONTS + [prefix + "/share/fonts/TTF/DejaVuSans.ttf"]
    for pth in cands:
        if os.path.exists(pth):
            try:
                return ImageFont.truetype(pth, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def spaced_text(draw, cx, y, text, font, fill, spacing=0):
    widths = [draw.textlength(c, font=font) for c in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x = cx - total / 2
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=font, fill=fill)
        x += w + spacing


REEL_PALETTES = {
    "burgundy": {"top": (16, 6, 22), "bot": (52, 10, 30), "light": (74, 16, 40),
                 "glow": (255, 54, 96),
                 "bokeh": [(255, 150, 175), (255, 214, 160), (255, 255, 255)]},
    "greenscreen": {"top": (0, 255, 0), "bot": (0, 255, 0), "light": (0, 255, 0),
                    "glow": (0, 255, 0), "bokeh": [(255, 255, 255)]},
}


class ReelStyle:
    """Pre-renders the background, glow and bokeh once, then composes frames."""

    def __init__(self, ss=2, palette="burgundy"):
        from PIL import Image, ImageDraw, ImageFilter, ImageChops
        W, H = REEL_W, REEL_H
        self.ss = ss
        bg = Image.new("RGB", (W, H))
        d = ImageDraw.Draw(bg)
        pal = REEL_PALETTES[palette]
        if palette == "greenscreen":              # flat green, nothing to key badly
            self.bg = Image.new("RGB", (W, H), (0, 255, 0))
            self.glow = None
            self.bokeh = []
            self.f_big = load_font(190)
            self.f_small = load_font(40)
            return
        top, bot = pal["top"], pal["bot"]
        for y in range(H):
            d.line([(0, y), (W, y)], fill=_mix(top, bot, (y / H) ** 1.2))
        lw, lh = W // 4, H // 4
        light = Image.new("RGB", (lw, lh), (0, 0, 0))
        ImageDraw.Draw(light).ellipse([lw * 0.05, lh * 0.04, lw * 0.95, lh * 0.60],
                                      fill=pal["light"])
        light = light.filter(ImageFilter.GaussianBlur(36)).resize((W, H))
        bg = ImageChops.add(bg, light)
        vw, vh = W // 8, H // 8
        vm = Image.new("L", (vw, vh), 120)
        ImageDraw.Draw(vm).ellipse([-vw * 0.2, -vh * 0.12, vw * 1.2, vh * 1.12],
                                   fill=255)
        vm = vm.filter(ImageFilter.GaussianBlur(14)).resize((W, H))
        self.bg = Image.composite(bg, Image.new("RGB", (W, H), (0, 0, 0)), vm)

        gs = 900
        glow = Image.new("RGBA", (gs, gs), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse([gs * 0.2, gs * 0.2, gs * 0.8, gs * 0.8],
                                     fill=pal["glow"] + (150,))
        self.glow = glow.filter(ImageFilter.GaussianBlur(95))

        rnd = random.Random(7)
        self.bokeh = []
        for k in range(20):
            r = rnd.randint(8, 34)
            col = rnd.choice(pal["bokeh"])
            sz = r * 4
            sp = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
            ImageDraw.Draw(sp).ellipse([r, r, 3 * r, 3 * r],
                                       fill=col + (rnd.randint(34, 78),))
            sp = sp.filter(ImageFilter.GaussianBlur(r * 0.4))
            self.bokeh.append((sp, rnd.uniform(0, W), rnd.uniform(0, H + 300),
                               rnd.uniform(22, 70), rnd.uniform(0, 6.28)))
        self.f_big = load_font(190)
        self.f_small = load_font(40)

    def frame(self, p, t, fall=0.0, sparkle=False, label=""):
        from PIL import Image, ImageDraw
        W, H = REEL_W, REEL_H
        im = self.bg.copy()

        for sp, x0, y0, spd, ph in self.bokeh:
            x = x0 + 26 * math.sin(t * 0.6 + ph)
            y = (y0 - spd * t) % (H + 300) - 150
            im.paste(sp, (int(x - sp.width / 2), int(y - sp.height / 2)), sp)

        sc = PLANT_PX_W / D_W
        bx, by, R, q = rose_geometry(p, t)
        if q > 0 and self.glow is not None:
            k = 0.95 * _smooth(q) * (0.92 + 0.08 * math.sin(t * 2.0))
            g2 = self.glow.copy()
            g2.putalpha(g2.getchannel("A").point(lambda v: int(v * k)))
            im.paste(g2, (int(PLANT_X + bx * sc - g2.width / 2),
                          int(PLANT_Y + by * sc - g2.height / 2)), g2)

        plant = render_rose(p, t, width=PLANT_PX_W, ss=self.ss, fall=fall,
                            sparkle=sparkle, star=1.0, detail=True)
        im.paste(plant, (PLANT_X, PLANT_Y), plant)

        d = ImageDraw.Draw(im)
        pct = int(round(p * 100))
        spaced_text(d, W / 2, 1345, f"{pct}%", self.f_big, (255, 238, 242), 6)
        x0, x1, y = 360, 720, 1585
        d.line([(x0, y), (x1, y)], fill=(86, 42, 60), width=8)
        d.ellipse([x0 - 4, y - 4, x0 + 4, y + 4], fill=(86, 42, 60))
        d.ellipse([x1 - 4, y - 4, x1 + 4, y + 4], fill=(86, 42, 60))
        xf = x0 + (x1 - x0) * p
        if p > 0:
            d.line([(x0, y), (xf, y)], fill=(255, 122, 154), width=8)
            d.ellipse([x0 - 4, y - 4, x0 + 4, y + 4], fill=(255, 122, 154))
            d.ellipse([xf - 11, y - 11, xf + 11, y + 11], fill=(255, 226, 232))
        spaced_text(d, W / 2, 1625, label.upper(), self.f_small, (236, 164, 184), 10)
        return im


def stage_label(p):
    if p >= 1.0:
        return "in full bloom"
    if p < 0.12:
        return "planting"
    if p < 0.55:
        return "growing"
    if p < 0.8:
        return "budding"
    return "blooming"


# ----------------------------------------------------------------------
# Rose reel for Instagram (1080x1920 video + PNG)
# ----------------------------------------------------------------------
REEL_CFG = {
    "fast": {"fps": 24, "grow": 5.0, "hold": 2.0, "ss": 1},
    "high": {"fps": 30, "grow": 7.0, "hold": 3.0, "ss": 2},
}


def make_reel(quality, mp4_path, png_path, theme="burgundy"):
    from PIL import Image
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg missing. Run: pkg install ffmpeg")

    cfg = REEL_CFG[quality]
    fps, grow, hold = cfg["fps"], cfg["grow"], cfg["hold"]
    total = int((grow + hold) * fps)

    progress(1, "preparing the scene...")
    style = ReelStyle(cfg["ss"], theme)
    gs = theme == "greenscreen"
    proc = open_ffmpeg(mp4_path, fps, 14 if gs else 16, "fast")
    last = None
    try:
        for i in range(total):
            ts = i / fps
            if ts < grow:
                p, fall, spark = _smooth(ts / grow), 0.0, False
            else:
                p, fall, spark = 1.0, max(0.0, ts - grow - 0.5), True
            im = style.frame(p, ts, fall, spark, stage_label(p))
            last = im
            if ts < 0.5 and not gs:                       # gentle fade-in
                im = Image.blend(Image.new("RGB", im.size, (0, 0, 0)), im, ts / 0.5)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=98 if gs else 97, subsampling=0)
            pipe_write(proc, buf.getvalue())
            if i % 2 == 0 or i == total - 1:
                progress(2 + 90 * (i + 1) / total, f"drawing frame {i + 1}/{total}")
        last.save(png_path, "PNG")
        progress(95, "finishing video...")
        close_ffmpeg(proc)
    except BaseException:
        kill_ffmpeg(proc)
        raise
    return total / fps


def run_rose(quality, theme="burgundy"):
    folder = output_dir()
    if not enough_space(folder):
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mp4 = os.path.join(folder, f"rose_{stamp}.mp4")
    png = os.path.join(folder, f"rose_{stamp}.png")
    heading("Rose growth reel")
    talk("work", "Planting your rose...", YELLOW)
    t0 = time.time()
    try:
        secs = run_job(make_reel, quality, mp4, png, theme)
        say(f"   {paint('✔', GREEN)} {secs:.0f}s reel, 1080 x 1920, "
            f"{time.time() - t0:.0f}s to make")
        say()
        talk("happy", f"Ready to post on Reels and Stories! Saved in "
                      f"{where_saved(folder)}:", GREEN)
        for path in (mp4, png):
            mb = os.path.getsize(path) / 1024 / 1024
            say(f"   {paint('•', GREEN)} {os.path.basename(path)} "
                + paint(f"({mb:.1f} MB)", DIM))
        storage_hint(folder)
    except Exception as e:
        talk("sad", f"Failed: {e}", RED)


# ----------------------------------------------------------------------
# Menu (selector)
# ----------------------------------------------------------------------
def choose(title, options, default=0):
    heading(title)
    for i, (_, label) in enumerate(options, 1):
        mark = paint("  ← default", DIM) if i - 1 == default else ""
        say(f"  {paint(str(i), BOLD, CYAN)}  {label}{mark}")
    while True:
        s = ask("❯ ").strip()
        if not s:
            return options[default][0]
        if s.isdigit() and 1 <= int(s) <= len(options):
            return options[int(s) - 1][0]
        say(paint("   Please type one of the numbers.", RED))


def menu_kind():
    return choose("What do you want to make?", [
        ("shot", "📸 Screenshot (long, full page)"),
        ("video", "🎬 Scrolling video (MP4)"),
        ("both", "✨ Screenshot + video"),
        ("mockup", "💻📱 Laptop & phone mockups"),
        ("rose", "🌹 Rose growth reel (for Instagram)")])


def menu_rose_theme():
    return choose("Background colour?", [
        ("burgundy", "🍷 Burgundy"),
        ("greenscreen", "🟩 Green screen (remove it in your editor)")])


def menu_rose():
    return choose("Reel quality?", [
        ("fast", "⚡ Fast  (24 fps, quick preview)"),
        ("high", "💎 High  (30 fps, sharper, takes longer)")], default=1)


def ask_quality(title, video=False):
    if video:
        opts = [("standard", "Standard: 1080p desktop, 780-wide phone, small files"),
                ("high", "High: 1080p desktop, 1080-wide phone (recommended)"),
                ("ultra", "Ultra: 1620p desktop, 1170-wide phone, lossless, slow")]
    else:
        opts = [("standard", "Standard: smallest files"),
                ("high", "High: sharp (recommended)"),
                ("ultra", "Ultra: sharpest, big files")]
    return choose(title, opts, default=1)


def ask_wait():
    """How long the page sits at the top before scrolling starts."""
    s = choose("Pause at the top before scrolling?", [
        ("0", "⏩ No pause"),
        ("2", "⏱️  2 seconds"),
        ("4", "⏱️  4 seconds (lets intro animations play)"),
        ("8", "⏱️  8 seconds"),
        ("custom", "✏️  Custom seconds")], default=2)
    if s != "custom":
        return float(s)
    while True:
        v = ask("Seconds to wait (e.g. 6) ❯ ").strip()
        try:
            if 0 <= float(v) <= 120:
                return float(v)
        except ValueError:
            pass
        say(paint("   Please type a number from 0 to 120.", RED))


def ask_speed():
    """Scroll speed menu (with a custom number), used by every video option."""
    s = choose("Scroll speed?", [
        ("slow", "🐢 Slow      150 px/s"),
        ("standard", "🚶 Standard  400 px/s"),
        ("fast", "🐇 Fast      800 px/s"),
        ("custom", "✏️  Custom number")], default=1)
    if s != "custom":
        return SPEEDS[s]
    while True:
        v = ask("Pixels per second (e.g. 300) ❯ ").strip()
        try:
            if float(v) > 0:
                return float(v)
        except ValueError:
            pass
        say(paint("   Please type a number above 0.", RED))


def menu_rest(kind):
    o = dict(modes="both", quality="high", speed=SPEEDS[DEFAULT_SPEED],
             anim="smart", layout="both", theme="midnight", fmt="jpg",
             media="photo", intro=4.0, zoom=False)
    if kind == "mockup":
        o["media"] = choose("Photo or video?", [
            ("photo", "📸 Photo"),
            ("video", "🎬 Scrolling video (page scrolls inside the screens)"),
            ("both", "✨ Both")])
        o["layout"] = choose("Which mockup?", [
            ("both", "💻📱 Laptop + phone together"),
            ("laptop", "💻 Laptop only"),
            ("phone", "📱 Phone only"),
            ("all", "🎁 All three")])
        o["theme"] = choose("Background style?", [
            ("midnight", "🌌 Midnight"),
            ("rose", "🌹 Rose"),
            ("ocean", "🌊 Ocean"),
            ("light", "☁️  Light"),
            ("greenscreen", "🟩 Green screen (remove it in your editor)")])
        o["zoom"] = choose("Size?", [
            ("fit", "📱 Social size (smaller files)"),
            ("zoom", "🔍 Zoom-ready: native pixels, tight frame (big, slow)")],
            default=1 if o["theme"] == "greenscreen" else 0) == "zoom"
        o["quality"] = ask_quality("Quality?", video=(o["media"] in ("video", "both")))
    else:
        o["modes"] = choose("Which device mode?", [
            ("both", "🖥️📱 Desktop + Mobile"),
            ("desktop", "🖥️  Desktop only"),
            ("mobile", "📱 Mobile only")])
        if kind in ("shot", "both"):
            o["quality"] = ask_quality("Quality?", video=(kind == "both"))
            o["anim"] = choose("Animations?", [
                ("smart", "Smart: scrolls through so animations play"),
                ("fast", "Fast: instant snapshot")], default=0)
        else:
            o["quality"] = ask_quality("Video quality?", video=True)
        if kind in ("video", "both"):
            o["speed"] = ask_speed()
    if kind == "mockup" and o["media"] in ("video", "both"):
        o["speed"] = ask_speed()
    if kind in ("video", "both", "mockup") or (kind == "shot" and o["anim"] == "smart"):
        o["intro"] = ask_wait()
    if kind in ("shot", "both") or (kind == "mockup" and o["media"] in ("photo", "both")):
        o["fmt"] = choose("Image format?", [
            ("jpg", "JPG: much smaller, saves storage"),
            ("png", "PNG: sharpest, but big files")], default=0)
    return o


def parse_speed(s):
    if s in SPEEDS:
        return SPEEDS[s]
    try:
        v = float(s)
        if v > 0:
            return v
    except ValueError:
        pass
    raise SystemExit("Speed must be slow, standard, fast or a number.")


def main():
    ap = argparse.ArgumentParser(description="SnapForge website shots and videos")
    ap.add_argument("url", nargs="?", help="website address")
    ap.add_argument("-t", "--type",
                    choices=["shot", "video", "both", "mockup", "rose"],
                    default=None, help="what to make")
    ap.add_argument("-m", "--mode", choices=["both", "desktop", "mobile"],
                    default="both")
    ap.add_argument("-q", "--quality", choices=list(QUALITY), default="high")
    ap.add_argument("-s", "--speed", default=DEFAULT_SPEED,
                    help="slow, standard, fast, or px per second")
    ap.add_argument("-a", "--anim", choices=["smart", "fast"], default="smart",
                    help="smart = let animations play (default)")
    ap.add_argument("-w", "--wait", type=float, default=DEFAULT_SETTLE,
                    help="seconds to wait per section for animations")
    ap.add_argument("--format", choices=["jpg", "png"], default="jpg",
                    help="image format (jpg is much smaller)")
    ap.add_argument("--intro", "--pause", dest="intro", type=float, default=4.0,
                    help="seconds to pause at the top before scrolling, so intro "
                         "animations play (videos film it, shots wait for it)")
    ap.add_argument("--media", choices=["photo", "video", "both"], default="photo",
                    help="mockup output: photo, video or both")
    ap.add_argument("--zoom", action="store_true",
                    help="mockups at native pixels with a tight frame (sharp when zoomed)")
    ap.add_argument("--layout", choices=list(LAYOUTS), default="both",
                    help="mockup layout")
    ap.add_argument("--theme", choices=list(THEMES), default="midnight",
                    help="mockup background")
    ap.add_argument("--rose-quality", choices=list(REEL_CFG), default="high",
                    help="quality of the rose reel")
    ap.add_argument("--rose-theme", choices=list(REEL_PALETTES), default="burgundy",
                    help="background colour of the rose reel")
    ap.add_argument("--clean", action="store_true",
                    help="free up storage used by leftovers and caches")
    ap.add_argument("--setup", action="store_true",
                    help="install everything needed in Termux")
    args = ap.parse_args()

    if args.setup:
        run_setup()
        return
    if args.clean:
        run_clean()
        return

    try:
        import PIL  # noqa: F401
    except ImportError:
        talk("sad", "Pillow missing. Run: pkg install python-pillow", RED)
        sys.exit(1)

    clean_stale()                       # silently remove old leftovers
    banner()
    interactive = args.url is None and args.type is None
    kind = menu_kind() if interactive else (args.type or "shot")

    if kind == "rose":
        if interactive:
            q = menu_rose()
            run_rose(q, menu_rose_theme())
        else:
            run_rose(args.rose_quality, args.rose_theme)
        say()
        talk("ready", "See you next time!")
        return

    if args.url is None:
        url = ask_url("Website URL ❯ ")
    else:
        url = normalize_url(args.url)
        problem = url_problem(url) if url else "No link given."
        if problem:
            talk("sad", problem, RED)
            return
    if not url:
        talk("sad", "No URL given.", RED)
        return
    if interactive:
        opts = menu_rest(kind)
    else:
        opts = dict(modes=args.mode, quality=args.quality,
                    speed=parse_speed(args.speed), anim=args.anim,
                    layout=args.layout, theme=args.theme, fmt=args.format,
                    media=args.media, intro=max(0.0, args.intro),
                    zoom=args.zoom)
    opts["settle"] = max(0.2, args.wait)

    say()
    talk("work", "Warming up the browser...", YELLOW)
    chrome = Chrome()
    try:
        while url:
            process(chrome, url, kind, opts)
            if not interactive:
                break
            say()
            url = ask_url("Another URL? (Enter to quit) ❯ ")
    finally:
        chrome.close()
        say()
        talk("ready", "See you next time!")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        sys.stdout.write("\033[?25h\n")
        talk("ready", "Stopped. Bye!")
