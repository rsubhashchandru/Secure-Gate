"""
SecureGate – Entry point
Run with: python run.py   (or)   uvicorn backend.main:app --reload
"""

import os
import sys
import signal
import socket
import subprocess
import uvicorn
from backend.config import settings


def _free_port(port: int) -> None:
    """Kill any process already listening on `port` (Windows only)."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                pid = line.strip().split()[-1]
                print(f"[SecureGate] Port {port} in use by PID {pid} – killing…")
                subprocess.run(["taskkill", "/PID", pid, "/F"],
                               capture_output=True, timeout=5)
    except Exception as exc:
        print(f"[SecureGate] Could not auto-free port {port}: {exc}")


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


if __name__ == "__main__":
    # Auto-free the port so "address already in use" never blocks startup
    if not _port_available(settings.PORT):
        _free_port(settings.PORT)
        import time; time.sleep(1)

    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
