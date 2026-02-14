#!/usr/bin/env python3
"""
Simple fullscreen display for Raspberry Pi OS Lite (no desktop needed).
Uses pygame with the framebuffer so it renders directly via HDMI.

Install: sudo apt install python3-pygame
Run:     python3 display.py
Exit:    Press ESC or Q
"""

import os
import sys
import time
import math

# Use the framebuffer driver (no X11 required)
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

import pygame

def main():
    pygame.init()

    # Fullscreen on the framebuffer
    info = pygame.display.Info()
    width, height = info.current_w, info.current_h
    screen = pygame.display.set_mode((width, height), pygame.FULLSCREEN)
    pygame.display.set_caption("Raspberry Pi Display")
    pygame.mouse.set_visible(False)

    clock = pygame.time.Clock()
    font_big = pygame.font.SysFont("monospace", 72, bold=True)
    font_small = pygame.font.SysFont("monospace", 32)

    # Colors
    BG = (20, 20, 30)
    WHITE = (255, 255, 255)
    CYAN = (0, 220, 255)
    MAGENTA = (255, 50, 180)
    GREEN = (0, 255, 120)

    running = True
    start = time.time()

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False

        t = time.time() - start
        screen.fill(BG)

        # Pulsing circle
        pulse = int(80 + 40 * math.sin(t * 2))
        cx, cy = width // 2, height // 2 - 40
        pygame.draw.circle(screen, CYAN, (cx, cy), pulse, 4)
        pygame.draw.circle(screen, MAGENTA, (cx, cy), pulse // 2, 3)

        # Rotating dots around the circle
        for i in range(8):
            angle = t * 1.5 + i * (math.pi / 4)
            dx = int(cx + (pulse + 30) * math.cos(angle))
            dy = int(cy + (pulse + 30) * math.sin(angle))
            pygame.draw.circle(screen, GREEN, (dx, dy), 6)

        # Title text
        title = font_big.render("Raspberry Pi", True, WHITE)
        screen.blit(title, (cx - title.get_width() // 2, cy + pulse + 50))

        # Clock
        now = time.strftime("%H:%M:%S")
        clock_text = font_small.render(now, True, CYAN)
        screen.blit(clock_text, (cx - clock_text.get_width() // 2, cy + pulse + 130))

        # FPS counter (top-left)
        fps_text = font_small.render(f"FPS: {int(clock.get_fps())}", True, GREEN)
        screen.blit(fps_text, (20, 20))

        pygame.display.flip()
        clock.tick(30)

    pygame.quit()
    sys.exit(0)

if __name__ == "__main__":
    main()
