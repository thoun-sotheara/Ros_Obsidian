import base64
import hashlib
import json
import os
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from Crypto.Cipher import DES
from Crypto.Util.Padding import pad as pkcs7_pad

import account_manager
from common.database import DATABASE
from common.logger import ServerLogger
from config.settings import (
    CLIENT_DIR, HTTP_PORT, HTTPS_PORT, PUBLIC_HOST,
    SERVER_CRT_PATH, SERVER_KEY_PATH, DNS_RESPONSE_KEY,
    SERVER_LINE, LOGS_DIR
)

logger = ServerLogger("WEB_STUB")

MANIFEST_CACHE = LOGS_DIR / "manifest_cache.txt"
UNHANDLED_LOG = LOGS_DIR / "unhandled_requests.log"

def des_wsdns(ip: str = PUBLIC_HOST) -> bytes:
    """Build a NetEase anti-hijack HTTPDNS response: 'wsdns:' + base64(DES-ECB-PKCS5(ip))."""
    enc = DES.new(DNS_RESPONSE_KEY, DES.MODE_ECB).encrypt(pkcs7_pad(ip.encode(), 8))
    return b"wsdns:" + base64.b64encode(enc)

WHOAMI_PAYLOAD = base64.b64encode(b"{}").decode()
WHOAMI_RESPONSE = (
    f'{{"sig":"00000000000000000000000000000000","payload":"{WHOAMI_PAYLOAD}",'
    f'"code":0,"retcode":0,"result":0,"reason":""}}'
).encode("utf-8")

SDK_OK_JSON = b'{"code":0,"result":0,"retcode":0,"reason":"","data":{}}'

VERSION_PLIST = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>version</key><string>220329223258_pc</string>
<key>res_version</key><string>220329223258_pc</string>
<key>min_engine_version</key><integer>104057</integer>
<key>min_client_version</key><integer>0</integer>
<key>min_patch_engine_version</key><integer>0</integer>
<key>needUpdate</key><integer>0</integer>
<key>forceUpdate</key><integer>0</integer>
<key>updateType</key><integer>0</integer>
<key>patchUrl</key><string></string>
<key>patchMd5</key><string></string>
<key>patchSize</key><integer>0</integer>
<key>resUrl</key><string></string>
<key>resMd5</key><string></string>
<key>resSize</key><integer>0</integer>
<key>patchList</key><array/>
<key>file_list</key><array/>
<key>notice</key><string></string>
<key>noticeType</key><integer>0</integer>
</dict></plist>"""

HOTFIX_PLIST = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>version</key><string>1.610637.614222</string>
<key>res_version</key><string>220329223258_pc</string>
<key>needUpdate</key><false/>
<key>forceUpdate</key><false/>
<key>files</key><array/>
<key>patchList</key><array/>
</dict></plist>"""

class WebStubHandler(BaseHTTPRequestHandler):
    server_version = "NeoX-WebStub/1.0"

    def log_message(self, format, *args):
        logger.debug(f"{self.client_address[0]} - {format % args}")

    def _send_response(self, body: bytes, content_type: str = "text/plain", code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.lower()
        host = self.headers.get("Host", "").lower()

        if path == "/api/leaderboard":
            account_manager.initialize_storage()
            body = json.dumps(
                {"leaderboard": DATABASE.get_leaderboard(20)},
                separators=(",", ":"),
            ).encode("utf-8")
            self._send_response(body, "application/json")
            return

        # 1. Whoami policy (NATProxy: sig + payload required or KeyError crashes client)
        if "whoami" in host or "whoami" in path:
            logger.info(f"Whoami policy request from {self.client_address[0]}")
            self._send_response(WHOAMI_RESPONSE, "application/json")
            return

        # 2. HTTPDNS
        if "httpdns" in host or "hdserver" in path or "domain=" in parsed.query or "/v3/" in path:
            logger.info(f"HTTPDNS resolution request from {self.client_address[0]}: {self.path}")
            if "hdserver" in path or "dns.update" in host:
                # Easebar DES format
                self._send_response(des_wsdns(PUBLIC_HOST))
            else:
                # JSON HTTPDNS format
                body = json.dumps({
                    "clientip": PUBLIC_HOST,
                    "code": 0,
                    "ttl": 60,
                    "addrs": [PUBLIC_HOST],
                    "dns": [{"host": host, "ips": [PUBLIC_HOST], "ttl": 60}]
                }).encode("utf-8")
                self._send_response(body, "application/json")
            return

        # 3. Server Line / Server List
        if "serverline" in path or "server_list" in path or "serverlist" in path or "/servers" in path or "query_product" in path:
            logger.info(f"Serverline query from {self.client_address[0]}: {self.path}")
            body = (SERVER_LINE + "\n").encode("utf-8")
            self._send_response(body, "text/plain")
            return

        # 4. Hotfix gate (_hc endpoint must return 'ok')
        if "h45na_hc" in path or path.endswith("_hc"):
            logger.info(f"Hotfix check: {path} -> returning 'ok'")
            self._send_response(b"ok", "text/plain")
            return

        # 5. Patch Manifests & Versions
        if "npk_version" in path or "res_version" in path:
            logger.info(f"NPK version check: {path} -> returning version plist")
            self._send_response(VERSION_PLIST, "text/xml")
            return

        # 6. XML Plists (Launcher no-hotfix)
        if path.endswith(".plist"):
            self._send_response(HOTFIX_PLIST, "text/xml")
            return

        # 7. Common Config & SDK endpoints
        if "common_config" in path or "feature2" in path:
            self._send_response(SDK_OK_JSON, "application/json")
            return

        # 8. SDK & Anti-cheat
        if "acsdk" in path or "optsdk" in host or "initbox" in path or "mpsdk" in host or "unisdk" in host or "easebar" in host:
            self._send_response(SDK_OK_JSON, "application/json")
            return

        # 9. Listerr & Telemetry
        if "listerr" in host or "listerr" in path or "errcode=" in path:
            self._send_response(b'{"code":0,"msg":"ok","data":{}}', "application/json")
            return

        # 10. Notice & Status endpoints
        if "notice" in path or "pharos_isp" in path or path == "/v1":
            self._send_response(b"")
            return

        # 11. CRL
        if path.endswith(".crl"):
            self._send_response(b"", "application/pkix-crl")
            return

        # Log unhandled requests
        with open(UNHANDLED_LOG, "a", encoding="utf-8") as f:
            f.write(f"GET {host} {self.path}\n")
        self._send_response(SDK_OK_JSON, "application/json")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length > 0 else b""
        host = self.headers.get("Host", "").lower()
        path = self.path.lower()

        # Telemetry / dump upload
        if "upload" in path or "appdump" in host:
            logger.info(f"Received client dump ({len(body)}B) from {self.client_address[0]}")
            dump_file = LOGS_DIR / f"dump_{int(threading.get_ident())}.bin"
            try:
                with open(dump_file, "wb") as f:
                    f.write(body)
            except Exception:
                pass
            self._send_response(b'{"code": 200, "message": "OK"}', "application/json")
            return

        # SDK & Anti-cheat initbox POSTs
        if "acsdk" in path or "initbox" in path or "optsdk" in host or "easebar" in host or "matrix" in host:
            logger.info(f"SDK POST from {self.client_address[0]}: {host} {path}")
            self._send_response(SDK_OK_JSON, "application/json")
            return

        # Log unhandled requests
        with open(UNHANDLED_LOG, "a", encoding="utf-8") as f:
            f.write(f"POST {host} {self.path} length={length}\n")
        self._send_response(SDK_OK_JSON, "application/json")


class WebStubServer:
    def __init__(self, http_port: int = HTTP_PORT, https_port: int = HTTPS_PORT):
        self.http_port = http_port
        self.https_port = https_port
        self.running = False
        self.httpd = None
        self.httpsd = None
        self.http_thread = None
        self.https_thread = None

    def start(self):
        if self.running:
            return
        self.running = True

        # Start Plain HTTP
        try:
            self.httpd = ThreadingHTTPServer(("0.0.0.0", self.http_port), WebStubHandler)
            self.http_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.http_thread.start()
            logger.info(f"HTTP Server listening on 0.0.0.0:{self.http_port}")
        except Exception as e:
            logger.error(f"Failed to start HTTP server on :{self.http_port}: {e}")

        # Start HTTPS with TLS
        if SERVER_CRT_PATH.exists() and SERVER_KEY_PATH.exists():
            try:
                self.httpsd = ThreadingHTTPServer(("0.0.0.0", self.https_port), WebStubHandler)
                ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                ctx.load_cert_chain(certfile=str(SERVER_CRT_PATH), keyfile=str(SERVER_KEY_PATH))
                self.httpsd.socket = ctx.wrap_socket(self.httpsd.socket, server_side=True)
                self.https_thread = threading.Thread(target=self.httpsd.serve_forever, daemon=True)
                self.https_thread.start()
                logger.info(f"HTTPS Server listening on 0.0.0.0:{self.https_port} (TLS OK)")
            except Exception as e:
                logger.warn(f"Failed to start HTTPS server on :{self.https_port}: {e}")
        else:
            logger.warn(f"TLS certificates not found in {SERVER_CRT_PATH}, skipping HTTPS.")

    def stop(self):
        self.running = False
        if self.httpd:
            self.httpd.shutdown()
        if self.httpsd:
            self.httpsd.shutdown()
        logger.info("WebStub servers stopped.")
