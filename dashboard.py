#!/usr/bin/env python3
"""
Digital Car Dashboard for Raspberry Pi 3
Connects to a WiFi OBD-II (ELM327) adapter and displays live car data.

Setup:
  1. Configure Pi to connect to your OBD adapter's WiFi (see README)
  2. Install: sudo apt install python3-pygame
  3. Edit OBD_IP / OBD_PORT below to match your adapter
  4. Run: python3 dashboard.py

Common WiFi OBD-II adapter defaults:
  - IP:   192.168.0.10
  - Port: 35000
"""

import os
import sys
import time
import math
import socket
import threading

os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

import pygame

# ===================== CONFIGURATION =====================
OBD_IP       = "192.168.0.10"    # Your OBD adapter's IP
OBD_PORT     = 35000             # Your OBD adapter's port
DEMO_MODE    = True              # True = fake data (test without car)
MAX_RPM      = 8000              # Max RPM on tachometer
MAX_SPEED    = 260               # Max speed (km/h) on speedometer
# =========================================================


# ----- Colors -----
BG         = (15, 15, 25)
WHITE      = (255, 255, 255)
GRAY       = (100, 100, 120)
DARK_GRAY  = (40, 40, 55)
CYAN       = (0, 200, 255)
GREEN      = (0, 230, 100)
YELLOW     = (255, 220, 0)
RED        = (255, 50, 50)
ORANGE     = (255, 150, 0)


# ==================== OBD CONNECTION ====================

class OBDConnection:
    """Communicates with a WiFi ELM327 OBD-II adapter over TCP."""

    PIDS = [
        ("010C", "0C", 2),   # RPM
        ("010D", "0D", 1),   # Speed
        ("0105", "05", 1),   # Coolant temp
        ("010F", "0F", 1),   # Intake temp
        ("0111", "11", 1),   # Throttle
        ("0104", "04", 1),   # Engine load
        ("012F", "2F", 1),   # Fuel level
    ]

    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.sock = None
        self.connected = False
        self.lock = threading.Lock()
        self.running = False
        self.data = self._empty_data()

    @staticmethod
    def _empty_data():
        return {
            "rpm": 0, "speed": 0, "coolant_temp": 0,
            "intake_temp": 0, "throttle": 0,
            "engine_load": 0, "fuel_level": 0,
        }

    # ---- low-level ----

    def _send(self, cmd, wait=0.15):
        try:
            self.sock.sendall((cmd + "\r").encode())
            time.sleep(wait)
            buf = b""
            while True:
                try:
                    chunk = self.sock.recv(1024)
                    if not chunk:
                        break
                    buf += chunk
                    if b">" in buf:
                        break
                except socket.timeout:
                    break
            return buf.decode(errors="ignore").strip()
        except Exception:
            self.connected = False
            return ""

    def _init_elm(self):
        self._send("ATZ", wait=1.0)
        self._send("ATE0")
        self._send("ATL0")
        self._send("ATS1")
        self._send("ATH0")
        self._send("ATSP0")
        self._send("0100", wait=3.0)   # trigger protocol detection

    def _parse(self, raw, pid_code, num_bytes):
        raw = raw.replace("\r", " ").replace("\n", " ").replace(">", "")
        tag = f"41 {pid_code}"
        idx = raw.find(tag)
        if idx == -1:
            return None
        parts = raw[idx + len(tag):].strip().split()
        try:
            return [int(b, 16) for b in parts[:num_bytes]]
        except ValueError:
            return None

    # ---- public ----

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((self.ip, self.port))
            self.connected = True
            self._init_elm()
            return True
        except Exception:
            self.connected = False
            return False

    def poll_loop(self):
        """Run in a background thread."""
        self.running = True
        while self.running:
            if not self.connected:
                time.sleep(3)
                self.connect()
                continue
            try:
                new = self._empty_data()
                for cmd, code, nb in self.PIDS:
                    if not self.running:
                        break
                    vals = self._parse(self._send(cmd), code, nb)
                    if vals is None:
                        continue
                    if code == "0C" and len(vals) >= 2:
                        new["rpm"] = (vals[0] * 256 + vals[1]) / 4.0
                    elif code == "0D":
                        new["speed"] = vals[0]
                    elif code == "05":
                        new["coolant_temp"] = vals[0] - 40
                    elif code == "0F":
                        new["intake_temp"] = vals[0] - 40
                    elif code == "11":
                        new["throttle"] = vals[0] * 100.0 / 255
                    elif code == "04":
                        new["engine_load"] = vals[0] * 100.0 / 255
                    elif code == "2F":
                        new["fuel_level"] = vals[0] * 100.0 / 255
                with self.lock:
                    self.data = new
            except Exception:
                self.connected = False
                time.sleep(3)

    def get_data(self):
        with self.lock:
            return dict(self.data)

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except Exception:
            pass


class DemoOBD:
    """Generates fake data so you can test the dashboard without a car."""

    def __init__(self):
        self.connected = True
        self._t0 = time.time()

    def connect(self):
        return True

    def poll_loop(self):
        pass

    def get_data(self):
        t = time.time() - self._t0
        rpm = 850 + 3200 * (0.5 + 0.5 * math.sin(t * 0.4))
        speed = max(0, 65 + 55 * math.sin(t * 0.25))
        return {
            "rpm": rpm,
            "speed": speed,
            "coolant_temp": 87 + 6 * math.sin(t * 0.08),
            "intake_temp": 33 + 4 * math.sin(t * 0.12),
            "throttle": max(0, 30 + 28 * math.sin(t * 0.7)),
            "engine_load": max(0, 42 + 22 * math.sin(t * 0.35)),
            "fuel_level": 60 + 12 * math.sin(t * 0.04),
        }

    def stop(self):
        pass


# ==================== DRAWING HELPERS ====================

def draw_thick_arc(surf, color, center, radius, thickness,
                   start_deg, end_deg, segments=60):
    """Render a thick arc as a filled polygon (inner + outer radius)."""
    if abs(end_deg - start_deg) < 0.3:
        return
    s = math.radians(start_deg)
    e = math.radians(end_deg)
    ro = radius + thickness / 2
    ri = radius - thickness / 2
    outer, inner = [], []
    for i in range(segments + 1):
        a = s + (e - s) * i / segments
        c_, si = math.cos(a), math.sin(a)
        outer.append((center[0] + ro * c_, center[1] - ro * si))
        inner.append((center[0] + ri * c_, center[1] - ri * si))
    pts = outer + inner[::-1]
    if len(pts) >= 3:
        pygame.draw.polygon(surf, color, pts)


def lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def rpm_color(frac):
    """Green → yellow → red for RPM."""
    if frac < 0.55:
        return GREEN
    if frac < 0.75:
        return lerp_color(GREEN, YELLOW, (frac - 0.55) / 0.20)
    return lerp_color(YELLOW, RED, (frac - 0.75) / 0.25)


def fuel_color(frac):
    """Red (empty) → yellow → green (full)."""
    if frac < 0.15:
        return RED
    if frac < 0.30:
        return lerp_color(RED, YELLOW, (frac - 0.15) / 0.15)
    return GREEN


def temp_color(val):
    """Blue (cold) → green (normal) → red (hot) for coolant."""
    if val < 60:
        return lerp_color(CYAN, GREEN, val / 60)
    if val < 100:
        return GREEN
    return lerp_color(YELLOW, RED, min(1, (val - 100) / 20))


# ==================== GAUGE DRAWING ====================

# Gauge arc sweeps from 225° (lower-left) to -45° (lower-right) = 270°
ARC_START = 225
ARC_END   = -45
ARC_SWEEP = ARC_START - ARC_END   # 270


def draw_gauge(surf, center, radius, value, max_val,
               label, unit, fonts, tick_step,
               color_func=None, label_div=1):
    """Draw a semicircular gauge with ticks, value, and label."""
    thickness = max(8, int(radius * 0.09))
    frac = max(0.0, min(1.0, value / max_val)) if max_val else 0
    val_angle = ARC_START - ARC_SWEEP * frac

    # --- background arc ---
    draw_thick_arc(surf, DARK_GRAY, center, radius, thickness,
                   ARC_END, ARC_START)

    # --- coloured value arc (drawn in small segments for gradient) ---
    if frac > 0.002:
        n = max(2, int(frac * 40))
        for i in range(n):
            f0 = i / n * frac
            f1 = (i + 1) / n * frac
            a0 = ARC_START - ARC_SWEEP * f0
            a1 = ARC_START - ARC_SWEEP * f1
            c = color_func(f1) if color_func else CYAN
            draw_thick_arc(surf, c, center, radius, thickness, a1, a0, segments=4)

    # --- tick marks & labels ---
    num_ticks = int(max_val / tick_step)
    for i in range(num_ticks + 1):
        tf = i * tick_step / max_val
        ang = math.radians(ARC_START - ARC_SWEEP * tf)
        ca, sa = math.cos(ang), math.sin(ang)
        major = True  # all ticks at tick_step are "major"

        t_len = radius * 0.13
        r_out = radius - thickness / 2 - 4
        p1 = (center[0] + r_out * ca, center[1] - r_out * sa)
        p2 = (center[0] + (r_out - t_len) * ca,
              center[1] - (r_out - t_len) * sa)
        pygame.draw.line(surf, GRAY, p1, p2, 2)

        # label
        tv = i * tick_step / label_div
        txt = f"{int(tv)}"
        ts = fonts["tick"].render(txt, True, GRAY)
        lx = center[0] + (r_out - t_len - 14) * ca - ts.get_width() / 2
        ly = center[1] - (r_out - t_len - 14) * sa - ts.get_height() / 2
        surf.blit(ts, (int(lx), int(ly)))

    # --- central value ---
    val_str = f"{int(value)}"
    vs = fonts["big"].render(val_str, True, WHITE)
    surf.blit(vs, (center[0] - vs.get_width() // 2,
                   center[1] - vs.get_height() // 2))

    # --- unit ---
    us = fonts["unit"].render(unit, True, GRAY)
    surf.blit(us, (center[0] - us.get_width() // 2,
                   center[1] + vs.get_height() // 2 + 1))

    # --- label ---
    ls = fonts["label"].render(label, True, GRAY)
    surf.blit(ls, (center[0] - ls.get_width() // 2,
                   center[1] + int(radius * 0.52)))


def draw_info_box(surf, rect, value, label, unit, color, fonts,
                  max_val=None, color_func=None):
    """Draw a small info box with a value, label, and progress bar."""
    x, y, w, h = rect

    # background
    pygame.draw.rect(surf, (25, 25, 40), rect, border_radius=8)
    pygame.draw.rect(surf, (50, 50, 70), rect, 1, border_radius=8)

    # label
    ls = fonts["ib_label"].render(label, True, GRAY)
    surf.blit(ls, (x + w // 2 - ls.get_width() // 2, y + 5))

    # value color
    vc = color
    if color_func:
        frac = value / max_val if max_val else 0
        vc = color_func(frac) if callable(color_func) else color

    # value text
    fmt = f"{value:.1f}" if isinstance(value, float) and value < 100 else f"{int(value)}"
    vs = fonts["ib_val"].render(f"{fmt}{unit}", True, vc)
    surf.blit(vs, (x + w // 2 - vs.get_width() // 2, y + 24))

    # bar
    if max_val and max_val > 0:
        bx, by, bw, bh = x + 8, y + h - 16, w - 16, 6
        pygame.draw.rect(surf, DARK_GRAY, (bx, by, bw, bh), border_radius=3)
        fw = int(bw * max(0, min(1, value / max_val)))
        if fw > 0:
            pygame.draw.rect(surf, vc, (bx, by, fw, bh), border_radius=3)


# ==================== MAIN ====================

def main():
    pygame.init()
    info = pygame.display.Info()
    W, H = info.current_w, info.current_h
    screen = pygame.display.set_mode((W, H), pygame.FULLSCREEN)
    pygame.display.set_caption("Digital Dash")
    pygame.mouse.set_visible(False)

    clock = pygame.time.Clock()

    # Font sizes tuned for 1024x600
    s = H / 600.0
    fonts = {
        "big":      pygame.font.SysFont("monospace", int(44 * s), bold=True),
        "unit":     pygame.font.SysFont("monospace", int(15 * s)),
        "label":    pygame.font.SysFont("monospace", int(15 * s), bold=True),
        "tick":     pygame.font.SysFont("monospace", int(11 * s)),
        "ib_label": pygame.font.SysFont("monospace", int(12 * s)),
        "ib_val":   pygame.font.SysFont("monospace", int(20 * s), bold=True),
        "status":   pygame.font.SysFont("monospace", int(12 * s)),
        "header":   pygame.font.SysFont("monospace", int(13 * s), bold=True),
    }

    # --- OBD connection ---
    if DEMO_MODE:
        obd = DemoOBD()
    else:
        obd = OBDConnection(OBD_IP, OBD_PORT)
        threading.Thread(target=obd.poll_loop, daemon=True).start()

    # --- layout tuned for 1024x600 ---
    gauge_r  = int(min(W * 0.19, H * 0.34))
    rpm_cx   = int(W * 0.25)
    speed_cx = int(W * 0.75)
    gauge_cy = int(H * 0.38)

    # info boxes
    box_labels = ["COOLANT", "INTAKE", "THROTTLE", "LOAD", "FUEL"]
    n_boxes = len(box_labels)
    box_w = int(W * 0.17)
    box_h = int(H * 0.15)
    total_w = n_boxes * box_w
    box_gap = int((W - total_w) / (n_boxes + 1))
    box_y = int(H * 0.82)

    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False

        data = obd.get_data()
        screen.fill(BG)

        # ---- tachometer (left) ----
        draw_gauge(screen, (rpm_cx, gauge_cy), gauge_r,
                   data["rpm"], MAX_RPM,
                   "TACHOMETER", "RPM", fonts,
                   tick_step=1000, color_func=rpm_color, label_div=1000)

        # ---- speedometer (right) ----
        draw_gauge(screen, (speed_cx, gauge_cy), gauge_r,
                   data["speed"], MAX_SPEED,
                   "SPEEDOMETER", "KM/H", fonts,
                   tick_step=40, color_func=None)

        # ---- info boxes (bottom) ----
        box_cfgs = [
            (data["coolant_temp"], "COOLANT",  "°C", 130,
             lambda f: temp_color(data["coolant_temp"])),
            (data["intake_temp"],  "INTAKE",   "°C", 80,  None),
            (data["throttle"],     "THROTTLE", "%",  100, None),
            (data["engine_load"],  "LOAD",     "%",  100, None),
            (data["fuel_level"],   "FUEL",     "%",  100,
             lambda f: fuel_color(f)),
        ]
        for i, (val, lbl, unit, mx, cfn) in enumerate(box_cfgs):
            bx = box_gap + i * (box_w + box_gap)
            c = CYAN
            if cfn:
                frac = val / mx if mx else 0
                c = cfn(frac)
            draw_info_box(screen, (bx, box_y, box_w, box_h),
                          val, lbl, unit, c, fonts, max_val=mx,
                          color_func=cfn)

        # ---- status bar ----
        if DEMO_MODE:
            st_text, st_col = "DEMO MODE", YELLOW
        elif obd.connected:
            st_text, st_col = "OBD CONNECTED", GREEN
        else:
            st_text, st_col = "OBD DISCONNECTED", RED
        st = fonts["status"].render(st_text, True, st_col)
        screen.blit(st, (W - st.get_width() - 12, 8))

        hdr = fonts["header"].render("DIGITAL DASH", True, GRAY)
        screen.blit(hdr, (12, 8))

        pygame.display.flip()
        clock.tick(30)

    obd.stop()
    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
