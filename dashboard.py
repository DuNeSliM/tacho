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
COL_BLUE_HI = (130, 170, 235)
COL_GREEN_BAND = (120, 145, 38)


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


def draw_top_tile(surface, rect, title, value, unit, fonts, accent=COL_CYAN, decimals=1):
    draw_panel(surface, rect, border_color=(63, 90, 132), fill_color=(20, 31, 48), radius=4)
    header_h = max(12, int(rect.height * 0.30))
    pygame.draw.rect(surface, (31, 45, 68), (rect.x + 1, rect.y + 1, rect.width - 2, header_h))
    pygame.draw.rect(surface, accent, (rect.x + 1, rect.y + header_h - 1, rect.width - 2, 2))
    draw_text_center(surface, fonts["tile_label"], title, COL_SUB, rect.centerx, rect.y + header_h * 0.50)
    draw_text_center(surface, fonts["tile_value"], format_num(value, decimals), accent, rect.centerx, rect.centery + rect.height * 0.05)
    draw_text_center(surface, fonts["tile_unit"], unit, COL_SUB, rect.centerx, rect.bottom - rect.height * 0.16)


def draw_rpm_band(surface, rect, rpm, fonts):
    draw_panel(surface, rect, border_color=(78, 109, 65), fill_color=(42, 58, 23), radius=2)
    segs = 8
    inner = rect.inflate(-2, -2)
    fill_frac = clamp(rpm / float(MAX_RPM), 0.0, 1.0)
    active = int(fill_frac * segs + 0.0001)
    for i in range(segs):
        x = inner.x + i * inner.width / segs
        w = inner.width / segs
        cell = pygame.Rect(int(x), inner.y, int(w) - 1, inner.height)
        if i < active:
            cell_col = lerp_color((123, 152, 44), (192, 88, 45), i / max(1, segs - 1))
        else:
            cell_col = (65, 86, 41)
        pygame.draw.rect(surface, cell_col, cell)
        draw_text_center(surface, fonts["tick"], str(i + 1), COL_TEXT, cell.centerx, cell.centery)
        pygame.draw.line(surface, (92, 118, 60), (cell.right, inner.y), (cell.right, inner.bottom), 1)


def draw_left_ramp(surface, rect, rpm, map_kpa, boost_psi, fonts):
    draw_panel(surface, rect, border_color=(85, 116, 165), fill_color=(17, 27, 42), radius=4)
    inner = rect.inflate(-8, -8)
    lx = inner.left
    rx = inner.right
    top_l = inner.top + int(inner.height * 0.42)
    top_r = inner.top + int(inner.height * 0.05)
    bot_l = inner.bottom - int(inner.height * 0.05)
    bot_r = inner.bottom - int(inner.height * 0.33)

    def y_top(x):
        return top_l + (top_r - top_l) * ((x - lx) / max(1.0, float(rx - lx)))

    def y_bot(x):
        return bot_l + (bot_r - bot_l) * ((x - lx) / max(1.0, float(rx - lx)))

    poly = [(lx, bot_l), (lx, top_l), (rx, top_r), (rx, bot_r)]
    pygame.draw.polygon(surface, (31, 45, 66), poly)
    pygame.draw.polygon(surface, COL_BLUE_HI, poly, 2)

    # section lines and labels
    sections = 8
    for i in range(1, sections):
        x = lx + (rx - lx) * i / sections
        yt = y_top(x)
        yb = y_bot(x)
        pygame.draw.line(surface, (56, 83, 120), (x, yt), (x, yb), 1)
        draw_text_center(surface, fonts["tick"], str(i), COL_SUB, x, yt - 10)

    # highlight fill from left based on rpm
    frac = clamp(rpm / float(MAX_RPM), 0.0, 1.0)
    px = lx + (rx - lx) * frac
    poly_fill = [(lx, bot_l), (lx, top_l), (px, y_top(px)), (px, y_bot(px))]
    pygame.draw.polygon(surface, (88, 118, 161), poly_fill)
    pygame.draw.line(surface, COL_CYAN, (px, y_top(px)), (px, y_bot(px)), 2)

    # center guide line like reference
    pygame.draw.line(surface, (210, 230, 255), (lx + 4, bot_l - 10), (rx - 2, top_r + 8), 2)
    pygame.draw.circle(surface, COL_RED, (int(lx + 1), int(bot_l)), 4)

    draw_text_center(surface, fonts["ramp_value"], format_num(boost_psi, 1), COL_ORANGE, rect.centerx, rect.bottom - 26)
    draw_text_center(surface, fonts["box_label"], "Boost (psi)", COL_SUB, rect.centerx, rect.bottom - 12)
    draw_text_center(surface, fonts["small"], f"MAP {format_num(map_kpa, 1)}", COL_CYAN, rect.right - 44, rect.top + 11)


def draw_data_box(surface, rect, label, value, unit, fonts, color, ratio=0.0, decimals=1, red_theme=False):
    border = (126, 44, 44) if red_theme else (67, 94, 131)
    fill = (70, 15, 15) if red_theme else (19, 29, 44)
    head = (128, 31, 31) if red_theme else (29, 43, 65)
    draw_panel(surface, rect, border_color=border, fill_color=fill, radius=4)
    header_h = max(12, int(rect.height * 0.34))
    pygame.draw.rect(surface, head, (rect.x + 1, rect.y + 1, rect.width - 2, header_h))
    draw_text_center(surface, fonts["box_label"], label, COL_SUB if not red_theme else (245, 200, 200), rect.centerx, rect.y + header_h * 0.52)
    draw_text_center(surface, fonts["box_value"], format_num(value, decimals), color, rect.centerx, rect.centery + rect.height * 0.03)
    draw_text_center(surface, fonts["box_unit"], unit, COL_SUB if not red_theme else (255, 210, 210), rect.centerx, rect.bottom - rect.height * 0.18)

    bx, by, bw, bh = rect.x + 8, rect.bottom - 8, rect.width - 16, 4
    pygame.draw.rect(surface, (42, 59, 83), (bx, by, bw, bh))
    fill_w = int(bw * clamp(ratio, 0.0, 1.0))
    if fill_w > 0:
        pygame.draw.rect(surface, color, (bx, by, fill_w, bh))


def draw_dashboard(surface, data, connected, fonts, fps):
    width, height = surface.get_size()
    surface.fill(COL_BG)

    line_step = max(6, int(height * 0.04))
    for y in range(0, height, line_step):
        pygame.draw.line(surface, COL_BG_2, (0, y), (width, y), 1)

    pad = max(8, int(height * 0.022))
    gap = max(5, int(height * 0.015))
    outer = pygame.Rect(pad, pad, width - pad * 2, height - pad * 2)
    draw_panel(surface, outer, border_color=(54, 77, 110), fill_color=(11, 17, 28), radius=4)

    # Header strip
    header_h = int(outer.height * 0.075)
    header = pygame.Rect(outer.x + 2, outer.y + 2, outer.width - 4, header_h)
    pygame.draw.rect(surface, (22, 33, 52), header)
    icon = pygame.Rect(header.x + 10, header.y + 6, header_h - 10, header_h - 10)
    pygame.draw.rect(surface, (34, 50, 80), icon, border_radius=3)
    pygame.draw.rect(surface, (78, 118, 184), icon, 1, border_radius=3)
    pygame.draw.line(surface, (78, 118, 184), (icon.x + 5, icon.centery), (icon.right - 5, icon.centery), 2)
    pygame.draw.line(surface, (78, 118, 184), (icon.centerx, icon.y + 5), (icon.centerx, icon.bottom - 5), 2)

    status = "DEMO" if DEMO_MODE else ("OBD ONLINE" if connected else "OBD OFFLINE")
    status_color = COL_YELLOW if DEMO_MODE else (COL_GREEN if connected else COL_RED)
    draw_text_center(surface, fonts["small"], status, status_color, header.right - 70, header.centery - 1)
    draw_text_center(surface, fonts["small"], f"{width}x{height}", COL_SUB, header.right - 12, header.centery - 1)

    # Top metric row
    row1_y = header.bottom + gap
    row1_h = int(outer.height * 0.19)
    row1 = pygame.Rect(outer.x + 2, row1_y, outer.width - 4, row1_h)
    tile_gap = gap
    tile_w = int((row1.width - tile_gap * 2) / 3)
    tile1 = pygame.Rect(row1.x, row1.y, tile_w, row1.height)
    tile2 = pygame.Rect(row1.x + tile_w + tile_gap, row1.y, tile_w, row1.height)
    tile3 = pygame.Rect(row1.x + (tile_w + tile_gap) * 2, row1.y, tile_w, row1.height)
    mph = data["speed_kmh"] * 0.621371
    draw_top_tile(surface, tile1, "MAP", data["map_kpa"], "(kPa)", fonts, accent=COL_CYAN, decimals=1)
    draw_top_tile(surface, tile2, "MPH", mph, "(MPH)", fonts, accent=COL_CYAN, decimals=0)
    draw_top_tile(surface, tile3, "RPM", data["rpm"], "(RPM)", fonts, accent=rpm_color(clamp(data["rpm"] / MAX_RPM, 0, 1)), decimals=0)

    # Segmented band
    band_h = int(outer.height * 0.07)
    band = pygame.Rect(outer.x + 2, row1.bottom + gap, outer.width - 4, band_h)
    draw_rpm_band(surface, band, data["rpm"], fonts)

    # Lower area
    body = pygame.Rect(outer.x + 2, band.bottom + gap, outer.width - 4, outer.bottom - (band.bottom + gap) - 2)
    left_w = int(body.width * 0.40)
    left = pygame.Rect(body.x, body.y, left_w, body.height)
    right = pygame.Rect(body.x + left_w + gap, body.y, body.width - left_w - gap, body.height)

    ramp_h = int(left.height * 0.72)
    ramp_rect = pygame.Rect(left.x, left.y, left.width, ramp_h)
    inj_rect = pygame.Rect(left.x, left.y + ramp_h + gap, left.width, left.height - ramp_h - gap)
    boost_psi = (data["map_kpa"] - 101.3) * 0.145038
    draw_left_ramp(surface, ramp_rect, data["rpm"], data["map_kpa"], boost_psi, fonts)
    draw_data_box(
        surface,
        inj_rect,
        "Injector Duty (Magneti)",
        data["engine_load"],
        "%",
        fonts,
        COL_ORANGE,
        ratio=data["engine_load"] / 100.0,
        decimals=2,
        red_theme=True,
    )

    afr_target = clamp(14.7 - (data["throttle"] / 100.0) * 2.8, 11.2, 14.7)
    afr_error = ((data["engine_load"] - 45.0) / 45.0) * 3.0
    fuel_rail = 30.0 + data["map_kpa"] * 0.12

    cols, rows = 2, 2
    card_w = int((right.width - gap) / cols)
    card_h = int((right.height - gap) / rows)
    cards = [
        ("Manifold Air Temp", data["intake_temp"], "(C)", temp_color(data["intake_temp"]), data["intake_temp"] / 80.0, 1),
        ("Coolant Temp", data["coolant_temp"], "(C)", temp_color(data["coolant_temp"]), data["coolant_temp"] / 120.0, 1),
        ("AFR 1 Target", afr_target, "", COL_CYAN, (afr_target - 10.0) / 5.0, 2),
        ("AFR 1 Error", afr_error, "", COL_CYAN, clamp((afr_error + 5.0) / 10.0, 0, 1), 2),
    ]

    idx = 0
    for row in range(rows):
        for col in range(cols):
            r = pygame.Rect(
                right.x + col * (card_w + gap),
                right.y + row * (card_h + gap),
                card_w,
                card_h,
            )
            label, value, unit, color, ratio, decimals = cards[idx]
            draw_data_box(surface, r, label, value, unit, fonts, color, ratio=ratio, decimals=decimals)
            idx += 1

    draw_text_center(surface, fonts["small"], f"Fuel Rail {format_num(fuel_rail, 2)} psi", COL_SUB, outer.right - 120, outer.bottom - 10)
    draw_text_center(surface, fonts["small"], f"FPS {int(fps)}", COL_SUB, outer.right - 28, header.centery - 1)


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
        "tile_label": pygame.font.SysFont("dejavusansmono", max(9, int(11 * scale)), bold=True),
        "tile_value": pygame.font.SysFont("dejavusansmono", max(20, int(48 * scale)), bold=True),
        "tile_unit": pygame.font.SysFont("dejavusansmono", max(9, int(12 * scale))),
        "box_label": pygame.font.SysFont("dejavusansmono", max(8, int(10 * scale)), bold=True),
        "box_value": pygame.font.SysFont("dejavusansmono", max(12, int(30 * scale)), bold=True),
        "box_unit": pygame.font.SysFont("dejavusansmono", max(9, int(11 * scale))),
        "ramp_value": pygame.font.SysFont("dejavusansmono", max(13, int(34 * scale)), bold=True),
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
