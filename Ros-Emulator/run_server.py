#!/usr/bin/env python3
"""
Rules of Survival (RoS) Offline Emulator Server
Unified Master Server Runner
"""

import argparse
import os
import signal
import sys
import time

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config.settings import (
    HTTP_PORT, HTTPS_PORT, LOGINAPP_PORT, BASEAPP_PORT,
    BIND_HOST, PUBLIC_HOST, CLIENT_DIR
)
from common.logger import ServerLogger
from services.web_stub import WebStubServer
from services.loginapp import LoginAppServer
from services.baseapp import BaseAppServer

logger = ServerLogger("MAIN")

BANNER = r"""
======================================================================
  ____  _   _ _     _____ ____     ___  _____   ______  ______ _____  
 |  _ \| | | | |   | ____/ ___|   / _ \|  ___| / ___\ \/ / ___| ____| 
 | |_) | | | | |   |  _| \___ \  | | | | |_   | |    \  /\___ \  _|   
 |  _ <| |_| | |___| |___ ___) | | |_| |  _|  | |___ /  \ ___) | |___ 
 |_| \_\\___/|_____|_____|____/   \___/|_|     \____/_/\_\____/|_____|
                        EMULATOR SERVER
======================================================================
"""

def print_status():
    print(BANNER)
    print(f" [*] Client Directory : {CLIENT_DIR}")
    print(f" [*] Bind Host        : {BIND_HOST}")
    print(f" [*] Public Host      : {PUBLIC_HOST}")
    print(f" [*] WebStub Ports    : HTTP {HTTP_PORT} | HTTPS {HTTPS_PORT}")
    print(f" [*] LoginApp Port    : UDP {LOGINAPP_PORT}")
    print(f" [*] BaseApp Port     : UDP {BASEAPP_PORT}")
    print(f" [*] IDA Pro MCP      : CONNECTED (ros_dump new.exe)")
    print("=" * 70)
    print(" [i] Press Ctrl+C to stop all servers gracefully.\n", flush=True)

def main():
    parser = argparse.ArgumentParser(description="Rules of Survival Emulator Server")
    parser.add_argument("--stub-only", action="store_true", help="Run only WebStub HTTP/HTTPS")
    parser.add_argument("--login-only", action="store_true", help="Run only LoginApp UDP")
    parser.add_argument("--base-only", action="store_true", help="Run only BaseApp UDP")
    args = parser.parse_args()

    print_status()

    servers = []

    run_all = not (args.stub_only or args.login_only or args.base_only)

    if run_all or args.stub_only:
        web_server = WebStubServer(http_port=HTTP_PORT, https_port=HTTPS_PORT)
        web_server.start()
        servers.append(web_server)

    if run_all or args.login_only:
        login_server = LoginAppServer(host=BIND_HOST, port=LOGINAPP_PORT, baseapp_port=BASEAPP_PORT)
        login_server.start()
        servers.append(login_server)

    if run_all or args.base_only:
        base_server = BaseAppServer(host=BIND_HOST, port=BASEAPP_PORT)
        base_server.start()
        servers.append(base_server)

    logger.info("All selected services are UP and running.")

    stop_event = False

    def handle_signal(sig, frame):
        nonlocal stop_event
        print("\n[*] Shutting down servers...", flush=True)
        stop_event = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        while not stop_event:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for s in servers:
            s.stop()
        logger.info("Server terminated cleanly. Goodbye!")

if __name__ == "__main__":
    main()
