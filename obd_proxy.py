#!/usr/bin/env python3
"""
OBD-II ELM327 WiFi Proxy

The Pi connects to the real OBD-II WiFi adapter, then re-serves the
ELM327 interface over its own hotspot so multiple devices (phone + Pi)
can use the data simultaneously.

Phone OBD apps (Torque, Car Scanner, etc.) connect to:
  IP:   192.168.4.1
  Port: 35000
"""

import socket
import threading
import time
import queue

OBD_IP   = "192.168.0.10"
OBD_PORT = 35000
PROXY_IP = "0.0.0.0"
PROXY_PORT = 35000

# Lock so only one command goes to the OBD adapter at a time
obd_lock = threading.Lock()
obd_sock = None
obd_connected = False


def connect_obd():
    """Connect to the real OBD-II WiFi adapter."""
    global obd_sock, obd_connected
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((OBD_IP, OBD_PORT))
            obd_sock = s
            obd_connected = True
            print(f"[PROXY] Connected to OBD adapter at {OBD_IP}:{OBD_PORT}")
            return
        except Exception as e:
            obd_connected = False
            print(f"[PROXY] OBD connection failed: {e}, retrying in 3s...")
            time.sleep(3)


def send_to_obd(cmd):
    """Send a command to the real OBD adapter and return the response."""
    global obd_sock, obd_connected
    with obd_lock:
        try:
            obd_sock.sendall((cmd.strip() + "\r").encode())
            time.sleep(0.1)
            buf = b""
            while True:
                try:
                    chunk = obd_sock.recv(4096)
                    if not chunk:
                        raise ConnectionError("OBD closed")
                    buf += chunk
                    if b">" in buf:
                        break
                except socket.timeout:
                    break
            return buf
        except Exception as e:
            print(f"[PROXY] OBD send error: {e}")
            obd_connected = False
            # Try to reconnect
            try:
                obd_sock.close()
            except Exception:
                pass
            connect_obd()
            return b"?\r\n>"


def handle_client(conn, addr):
    """Handle a phone/app connecting to the proxy."""
    print(f"[PROXY] Client connected: {addr}")
    conn.settimeout(30)
    try:
        while True:
            try:
                data = conn.recv(1024)
                if not data:
                    break
                cmd = data.decode(errors="ignore").strip()
                if not cmd:
                    continue
                print(f"[PROXY] {addr} -> OBD: {cmd}")
                response = send_to_obd(cmd)
                conn.sendall(response)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[PROXY] Client error: {e}")
                break
    finally:
        print(f"[PROXY] Client disconnected: {addr}")
        conn.close()


def main():
    print("[PROXY] Starting OBD-II ELM327 Proxy...")
    print(f"[PROXY] Real OBD adapter: {OBD_IP}:{OBD_PORT}")
    print(f"[PROXY] Proxy listening on: {PROXY_IP}:{PROXY_PORT}")

    # Connect to the real OBD adapter
    connect_obd()

    # Start proxy server
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((PROXY_IP, PROXY_PORT))
    server.listen(5)
    print(f"[PROXY] Proxy ready — phones can connect to 192.168.4.1:{PROXY_PORT}")

    while True:
        try:
            conn, addr = server.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
        except KeyboardInterrupt:
            break

    server.close()
    if obd_sock:
        obd_sock.close()
    print("[PROXY] Proxy stopped.")


if __name__ == "__main__":
    main()
