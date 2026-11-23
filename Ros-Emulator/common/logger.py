import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from config.settings import LOGS_DIR

_lock = threading.Lock()

class ServerLogger:
    def __init__(self, tag: str, log_filename: str = None):
        self.tag = tag
        self.log_file = (LOGS_DIR / log_filename) if log_filename else (LOGS_DIR / f"{tag.lower()}.log")

    def log(self, message: str, level: str = "INFO"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        formatted = f"[{ts}] [{self.tag}] [{level}] {message}"
        with _lock:
            print(formatted, flush=True)
            try:
                with open(self.log_file, "a", encoding="utf-8", errors="replace") as f:
                    f.write(formatted + "\n")
            except Exception:
                pass

    def info(self, message: str):
        self.log(message, "INFO")

    def warn(self, message: str):
        self.log(message, "WARN")

    def error(self, message: str):
        self.log(message, "ERROR")

    def debug(self, message: str):
        self.log(message, "DEBUG")

    def hexdump(self, data: bytes, prefix: str = "    ") -> str:
        out = []
        for i in range(0, len(data), 16):
            chunk = data[i:i+16]
            hex_part = " ".join(f"{b:02x}" for b in chunk)
            ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            out.append(f"{prefix}{i:04x}  {hex_part:<47}  {ascii_part}")
        return "\n".join(out)
