#!/usr/bin/env python3
"""
Ultra-wide digital dashboard for Raspberry Pi.

Designed for 11.26" bar displays around 1920x440 (or 440x1920 with auto-rotate).
Reads data from local OBD proxy (obd_proxy.py) or demo generator.
"""

import math
import os
import socket
import sys
import threading
import time

os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")

import pygame


# ===================== CONFIGURATION =====================
OBD_IP = os.getenv("OBD_IP", "127.0.0.1")
OBD_PORT = int(os.getenv("OBD_PORT", "35000"))
DEMO_MODE = os.getenv("DEMO_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}
MAX_RPM = int(os.getenv("MAX_RPM", "8000"))
# =========================================================


COL_BG = (7, 10, 18)
COL_BG_2 = (10, 16, 28)
COL_PANEL = (16, 24, 38)
COL_BORDER = (52, 73, 110)
COL_GRID = (18, 33, 50)
COL_TEXT = (214, 236, 255)
COL_SUB = (107, 145, 185)
COL_CYAN = (0, 210, 255)
COL_GREEN = (70, 225, 120)
COL_YELLOW = (255, 211, 78)
COL_RED = (255, 76, 76)
COL_ORANGE = (255, 143, 65)


def clamp(value, low, high):
    return max(low, min(high, value))


def lerp_color(c1, c2, t):
    t = clamp(t, 0.0, 1.0)
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def rpm_color(frac):
    if frac < 0.60:
        return COL_GREEN
    if frac < 0.80:
        return lerp_color(COL_GREEN, COL_YELLOW, (frac - 0.60) / 0.20)
    return lerp_color(COL_YELLOW, COL_RED, (frac - 0.80) / 0.20)


def temp_color(temp_c):
    if temp_c <= 70:
        return lerp_color(COL_CYAN, COL_GREEN, temp_c / 70.0)
    if temp_c <= 104:
        return COL_GREEN
    if temp_c <= 120:
        return lerp_color(COL_YELLOW, COL_RED, (temp_c - 104) / 16.0)
    return COL_RED


class OBDConnection:
    """ELM327 TCP client for live OBD data polling."""

    PIDS = [
        ("010C", "0C", 2),   # RPM
        ("010D", "0D", 1),   # Speed km/h
        ("0105", "05", 1),   # Coolant temp C
        ("010F", "0F", 1),   # Intake temp C
        ("0111", "11", 1),   # Throttle %
        ("0104", "04", 1),   # Engine load %
        ("012F", "2F", 1),   # Fuel level %
        ("010B", "0B", 1),   # MAP kPa
    ]

    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.sock = None
        self.connected = False
        self.running = False
        self.lock = threading.Lock()
        self.data = self._empty_data()

    @staticmethod
    def _empty_data():
        return {
            "rpm": 0.0,
            "speed_kmh": 0.0,
            "coolant_temp": 0.0,
            "intake_temp": 0.0,
            "throttle": 0.0,
            "engine_load": 0.0,
            "fuel_level": 0.0,
            "map_kpa": 0.0,
        }

    def _send(self, cmd, wait=0.12):
        try:
            self.sock.sendall((cmd + "\r").encode("ascii"))
            time.sleep(wait)
            buffer = b""
            while True:
                try:
                    chunk = self.sock.recv(1024)
                    if not chunk:
                        break
                    buffer += chunk
                    if b">" in buffer:
                        break
                except socket.timeout:
                    break
            return buffer.decode("ascii", errors="ignore")
        except Exception:
            self.connected = False
            return ""

    def _init_elm(self):
        self._send("ATZ", wait=0.8)
        self._send("ATE0")
        self._send("ATL0")
        self._send("ATS1")
        self._send("ATH0")
        self._send("ATSP0")
        self._send("0100", wait=2.0)

    @staticmethod
    def _parse_pid(raw, pid_code, num_bytes):
        raw = raw.replace("\r", " ").replace("\n", " ").replace(">", "")
        tag = f"41 {pid_code}"
        idx = raw.find(tag)
        if idx < 0:
            return None
        tokens = raw[idx + len(tag):].strip().split()
        try:
            return [int(x, 16) for x in tokens[:num_bytes]]
        except ValueError:
            return None

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(4.0)
            self.sock.connect((self.ip, self.port))
            self.connected = True
            self._init_elm()
            return True
        except Exception:
            self.connected = False
            return False

    def poll_loop(self):
        self.running = True
        while self.running:
            if not self.connected:
                time.sleep(2.5)
                self.connect()
                continue

            try:
                fresh = self._empty_data()
                for cmd, code, nbytes in self.PIDS:
                    if not self.running:
                        break
                    raw = self._send(cmd)
                    vals = self._parse_pid(raw, code, nbytes)
                    if vals is None:
                        continue

                    if code == "0C" and len(vals) >= 2:
                        fresh["rpm"] = (vals[0] * 256 + vals[1]) / 4.0
                    elif code == "0D":
                        fresh["speed_kmh"] = float(vals[0])
                    elif code == "05":
                        fresh["coolant_temp"] = float(vals[0] - 40)
                    elif code == "0F":
                        fresh["intake_temp"] = float(vals[0] - 40)
                    elif code == "11":
                        fresh["throttle"] = vals[0] * 100.0 / 255.0
                    elif code == "04":
                        fresh["engine_load"] = vals[0] * 100.0 / 255.0
                    elif code == "2F":
                        fresh["fuel_level"] = vals[0] * 100.0 / 255.0
                    elif code == "0B":
                        fresh["map_kpa"] = float(vals[0])

                with self.lock:
                    self.data = fresh
            except Exception:
                self.connected = False
                time.sleep(2.0)

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
    """Fake telemetry for testing layout and rendering."""

    def __init__(self):
        self.connected = True
        self.t0 = time.time()

    def get_data(self):
        t = time.time() - self.t0
        speed = max(0.0, 72 + 54 * math.sin(t * 0.42))
        rpm = 900 + speed * 33 + 520 * math.sin(t * 0.8)
        map_kpa = 34 + (rpm / MAX_RPM) * 125 + 8 * math.sin(t * 0.6)
        return {
            "rpm": clamp(rpm, 750, 7600),
            "speed_kmh": clamp(speed, 0, 250),
            "coolant_temp": 88 + 6 * math.sin(t * 0.12),
            "intake_temp": 31 + 5 * math.sin(t * 0.18),
            "throttle": clamp(26 + 34 * math.sin(t * 1.2), 0, 100),
            "engine_load": clamp(44 + 27 * math.sin(t * 0.5), 0, 100),
            "fuel_level": clamp(68 + 13 * math.sin(t * 0.05), 0, 100),
            "map_kpa": clamp(map_kpa, 20, 240),
        }

    def stop(self):
        return


def draw_panel(surface, rect, border_color=COL_BORDER, fill_color=COL_PANEL, radius=8):
    pygame.draw.rect(surface, fill_color, rect, border_radius=radius)
    pygame.draw.rect(surface, border_color, rect, width=1, border_radius=radius)


def draw_text_center(surface, font, text, color, cx, cy):
    text_s = font.render(text, True, color)
    surface.blit(text_s, (int(cx - text_s.get_width() / 2), int(cy - text_s.get_height() / 2)))


def format_num(value, decimals=1):
    if decimals <= 0:
        return str(int(round(value)))
    return f"{value:.{decimals}f}"


def draw_value_tile(surface, rect, title, value, unit, fonts, accent=COL_CYAN, decimals=1):
    draw_panel(surface, rect, border_color=(59, 86, 124), fill_color=(20, 30, 46), radius=7)
    header_h = max(14, int(rect.height * 0.24))
    pygame.draw.rect(
        surface,
        (29, 42, 64),
        (rect.x + 1, rect.y + 1, rect.width - 2, header_h),
        border_top_left_radius=7,
        border_top_right_radius=7,
    )
    pygame.draw.rect(surface, accent, (rect.x + 1, rect.y + header_h - 1, rect.width - 2, 2))

    draw_text_center(surface, fonts["tile_label"], title, COL_SUB, rect.centerx, rect.y + header_h * 0.53)

    value_str = format_num(value, decimals=decimals)
    draw_text_center(surface, fonts["tile_value"], value_str, accent, rect.centerx, rect.centery + rect.height * 0.02)
    draw_text_center(surface, fonts["tile_unit"], unit, COL_SUB, rect.centerx, rect.bottom - rect.height * 0.15)


def draw_left_ramp(surface, rect, rpm, map_kpa, boost_psi, fonts):
    draw_panel(surface, rect, border_color=(76, 106, 151), fill_color=(17, 27, 40), radius=7)

    title_rect = pygame.Rect(rect.x + 1, rect.y + 1, rect.width - 2, max(16, int(rect.height * 0.16)))
    pygame.draw.rect(surface, (30, 43, 64), title_rect, border_top_left_radius=7, border_top_right_radius=7)
    draw_text_center(surface, fonts["box_label"], "BOOST RAMP", COL_SUB, title_rect.centerx, title_rect.centery)

    pad = max(8, int(rect.height * 0.10))
    inner = pygame.Rect(rect.x + pad, rect.y + title_rect.height + 4, rect.width - pad * 2, rect.height - title_rect.height - pad - 4)

    lx = inner.left + 2
    rx = inner.right - 2
    top_l = inner.top + int(inner.height * 0.42)
    top_r = inner.top + int(inner.height * 0.08)
    bot_l = inner.bottom - int(inner.height * 0.05)
    bot_r = inner.bottom - int(inner.height * 0.30)

    def y_top(x):
        t = (x - lx) / float(max(1, rx - lx))
        return top_l + (top_r - top_l) * t

    def y_bot(x):
        t = (x - lx) / float(max(1, rx - lx))
        return bot_l + (bot_r - bot_l) * t

    base_poly = [(lx, bot_l), (lx, top_l), (rx, top_r), (rx, bot_r)]
    pygame.draw.polygon(surface, (26, 41, 59), base_poly)
    pygame.draw.polygon(surface, (80, 117, 166), base_poly, width=2)

    # grid slices and labels
    steps = 8
    for i in range(1, steps):
        x = lx + (rx - lx) * i / steps
        yt = y_top(x)
        yb = y_bot(x)
        pygame.draw.line(surface, COL_GRID, (x, yt), (x, yb), 1)
        draw_text_center(surface, fonts["tick"], str(i), COL_SUB, x, yt - 9)

    frac = clamp(rpm / float(MAX_RPM), 0.0, 1.0)
    px = lx + (rx - lx) * frac
    prog_poly = [(lx, bot_l), (lx, top_l), (px, y_top(px)), (px, y_bot(px))]
    pygame.draw.polygon(surface, (58, 84, 122), prog_poly)
    pygame.draw.line(surface, COL_CYAN, (px, y_top(px)), (px, y_bot(px)), 2)

    # red marker on lower-left like reference
    pygame.draw.circle(surface, COL_RED, (int(lx), int(bot_l)), 4)

    draw_text_center(surface, fonts["ramp_value"], format_num(boost_psi, 1), COL_ORANGE, rect.centerx, rect.centery + 8)
    draw_text_center(surface, fonts["box_label"], "Boost (psi)", COL_SUB, rect.centerx, rect.centery + 32)
    draw_text_center(surface, fonts["small"], f"MAP {format_num(map_kpa, 1)} kPa", COL_CYAN, rect.centerx, rect.bottom - 14)


def draw_metric_card(surface, rect, label, value, unit, fonts, color, ratio):
    draw_panel(surface, rect, border_color=(70, 95, 130), fill_color=(18, 28, 42), radius=6)

    header_h = max(13, int(rect.height * 0.27))
    pygame.draw.rect(
        surface,
        (27, 41, 62),
        (rect.x + 1, rect.y + 1, rect.width - 2, header_h),
        border_top_left_radius=6,
        border_top_right_radius=6,
    )
    draw_text_center(surface, fonts["box_label"], label, COL_SUB, rect.centerx, rect.y + header_h * 0.52)

    value_text = format_num(value, 2 if abs(value) < 20 else 1)
    draw_text_center(surface, fonts["box_value"], value_text, color, rect.centerx, rect.centery + rect.height * 0.03)
    draw_text_center(surface, fonts["box_unit"], unit, COL_SUB, rect.centerx, rect.bottom - rect.height * 0.19)

    bx = rect.x + 8
    by = rect.bottom - 8
    bw = rect.width - 16
    bh = 4
    pygame.draw.rect(surface, (38, 56, 80), (bx, by, bw, bh), border_radius=2)
    fill = int(bw * clamp(ratio, 0.0, 1.0))
    if fill > 0:
        pygame.draw.rect(surface, color, (bx, by, fill, bh), border_radius=2)


def draw_dashboard(surface, data, connected, fonts, fps):
    width, height = surface.get_size()
    surface.fill(COL_BG)

    # subtle scan lines
    line_step = max(6, int(height * 0.04))
    for y in range(0, height, line_step):
        pygame.draw.line(surface, COL_BG_2, (0, y), (width, y), 1)

    pad = max(10, int(height * 0.04))
    gap = max(8, int(height * 0.025))
    top_h = int(height * 0.23)
    body_h = height - (pad * 2) - top_h - gap

    top_rect = pygame.Rect(pad, pad, width - 2 * pad, top_h)
    body_rect = pygame.Rect(pad, pad + top_h + gap, width - 2 * pad, body_h)

    tile_gap = gap
    tile_w = int((top_rect.width - tile_gap * 2) / 3)
    tile_h = top_rect.height
    tile1 = pygame.Rect(top_rect.x, top_rect.y, tile_w, tile_h)
    tile2 = pygame.Rect(top_rect.x + tile_w + tile_gap, top_rect.y, tile_w, tile_h)
    tile3 = pygame.Rect(top_rect.x + (tile_w + tile_gap) * 2, top_rect.y, tile_w, tile_h)

    mph = data["speed_kmh"] * 0.621371
    draw_value_tile(surface, tile1, "MAP", data["map_kpa"], "kPa", fonts, accent=COL_CYAN, decimals=1)
    draw_value_tile(surface, tile2, "SPEED", mph, "MPH", fonts, accent=COL_CYAN, decimals=0)
    draw_value_tile(surface, tile3, "RPM", data["rpm"], "rpm", fonts, accent=rpm_color(clamp(data["rpm"] / MAX_RPM, 0, 1)), decimals=0)

    left_w = int(body_rect.width * 0.41)
    left_rect = pygame.Rect(body_rect.x, body_rect.y, left_w, body_rect.height)
    right_rect = pygame.Rect(body_rect.x + left_w + gap, body_rect.y, body_rect.width - left_w - gap, body_rect.height)

    boost_psi = (data["map_kpa"] - 101.3) * 0.145038
    draw_left_ramp(surface, left_rect, data["rpm"], data["map_kpa"], boost_psi, fonts)

    cols, rows = 3, 2
    card_gap = gap
    card_w = int((right_rect.width - card_gap * (cols - 1)) / cols)
    card_h = int((right_rect.height - card_gap * (rows - 1)) / rows)

    cards = [
        ("Injector Duty", data["engine_load"], "%", COL_RED, data["engine_load"] / 100.0),
        ("Intake Air Temp", data["intake_temp"], "C", temp_color(data["intake_temp"]), data["intake_temp"] / 80.0),
        ("Coolant Temp", data["coolant_temp"], "C", temp_color(data["coolant_temp"]), data["coolant_temp"] / 120.0),
        ("Throttle", data["throttle"], "%", COL_CYAN, data["throttle"] / 100.0),
        ("Boost Target", boost_psi, "psi", COL_CYAN, clamp((boost_psi + 10.0) / 25.0, 0, 1)),
        ("Fuel Level", data["fuel_level"], "%", COL_GREEN if data["fuel_level"] > 20 else COL_RED, data["fuel_level"] / 100.0),
    ]

    idx = 0
    for r in range(rows):
        for c in range(cols):
            card = pygame.Rect(
                right_rect.x + c * (card_w + card_gap),
                right_rect.y + r * (card_h + card_gap),
                card_w,
                card_h,
            )
            label, value, unit, color, ratio = cards[idx]
            draw_metric_card(surface, card, label, value, unit, fonts, color, ratio)
            idx += 1

    status = "DEMO" if DEMO_MODE else ("OBD ONLINE" if connected else "OBD OFFLINE")
    status_color = COL_YELLOW if DEMO_MODE else (COL_GREEN if connected else COL_RED)
    draw_text_center(surface, fonts["small"], status, status_color, width - 90, 14)
    draw_text_center(surface, fonts["small"], f"{width}x{height}  FPS {int(fps)}", COL_SUB, width - 88, 30)


def main():
    pygame.init()
    info = pygame.display.Info()
    screen_w = info.current_w
    screen_h = info.current_h
    screen = pygame.display.set_mode((screen_w, screen_h), pygame.FULLSCREEN)
    pygame.display.set_caption("Digital Dashboard")
    pygame.mouse.set_visible(False)

    # If display is reported portrait (e.g., 440x1920), draw on a landscape canvas
    # and rotate it so layout still matches a bar-style dashboard.
    rotate_output = screen_w < screen_h
    if rotate_output:
        canvas_w, canvas_h = screen_h, screen_w
    else:
        canvas_w, canvas_h = screen_w, screen_h
    canvas = pygame.Surface((canvas_w, canvas_h))

    scale = canvas_h / 440.0
    fonts = {
        "tile_label": pygame.font.SysFont("dejavusansmono", max(10, int(13 * scale)), bold=True),
        "tile_value": pygame.font.SysFont("dejavusansmono", max(22, int(52 * scale)), bold=True),
        "tile_unit": pygame.font.SysFont("dejavusansmono", max(9, int(12 * scale))),
        "box_label": pygame.font.SysFont("dejavusansmono", max(9, int(11 * scale)), bold=True),
        "box_value": pygame.font.SysFont("dejavusansmono", max(13, int(32 * scale)), bold=True),
        "box_unit": pygame.font.SysFont("dejavusansmono", max(9, int(11 * scale))),
        "ramp_value": pygame.font.SysFont("dejavusansmono", max(13, int(36 * scale)), bold=True),
        "small": pygame.font.SysFont("dejavusansmono", max(9, int(11 * scale))),
        "tick": pygame.font.SysFont("dejavusansmono", max(8, int(10 * scale))),
    }

    if DEMO_MODE:
        obd = DemoOBD()
        connected = True
    else:
        obd = OBDConnection(OBD_IP, OBD_PORT)
        threading.Thread(target=obd.poll_loop, daemon=True).start()
        connected = False

    clock = pygame.time.Clock()
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False

        telemetry = obd.get_data()
        if not DEMO_MODE:
            connected = obd.connected

        draw_dashboard(canvas, telemetry, connected, fonts, clock.get_fps())

        if rotate_output:
            frame = pygame.transform.rotate(canvas, -90)
            screen.blit(frame, (0, 0))
        else:
            screen.blit(canvas, (0, 0))

        pygame.display.flip()
        clock.tick(30)

    obd.stop()
    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()
