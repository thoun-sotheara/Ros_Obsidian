import os
import sys
import time
import subprocess
import threading
import frida

from config.settings import CLIENT_DIR, BASE_DIR, BFCTX_PATH

GAME_DIR = str(CLIENT_DIR)
TOOLS_DIR = os.path.join(GAME_DIR, "tools")
RE_DIR = os.path.join(TOOLS_DIR, "re")

def get_bfhex():
    if os.path.exists(BFCTX_PATH):
        with open(BFCTX_PATH, "rb") as f:
            return f.read().hex()
    return ""

def kill_stale_helpers():
    for img in ("frida-helper-x86_64.exe", "frida-helper-x86.exe",
                "frida-winjector-helper-64.exe", "frida-winjector-helper-32.exe"):
        try:
            subprocess.run(["taskkill", "/f", "/im", img], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

def main():
    print("=" * 60)
    print("  Rules of Survival - Client Hook & Injection Agent")
    print("=" * 60)
    bfhex = get_bfhex()
    if not bfhex:
        print("[!] ERROR: bfctx.bin not found in D:\\Server\\ROS\\crypto\\bfctx.bin!")
        return 1

    print("[*] Waiting for ros.exe process...")
    session = None
    deadline = time.time() + 180  # wait up to 3 minutes
    while session is None and time.time() < deadline:
        try:
            session = frida.attach("ros.exe")
        except Exception as e:
            msg = str(e)
            if "0x5" in msg or "ACCESS_DENIED" in msg or "VirtualAllocEx" in msg:
                kill_stale_helpers()
            time.sleep(1)

    if session is None:
        print("[!] Timed out waiting for ros.exe!")
        return 1

    print(f"[+] Successfully attached to ros.exe!")
    print("[*] Waiting 5 seconds for game engine to load login screen...")
    time.sleep(5)

    payload_file = os.path.join(RE_DIR, "login_fix_hall.py")
    if not os.path.exists(payload_file):
        print(f"[!] Payload file not found: {payload_file}")
        return 1

    import base64, json
    with open(payload_file, "r", encoding="utf-8") as f:
        code_str = f.read()
    b64_str = base64.b64encode(code_str.encode("utf-8")).decode("ascii")

    # Safe runner: executes in global namespace so all modules & functions have proper global scope
    p_tools = str(CLIENT_DIR / "tools").replace("\\", "/")
    p_re = str(CLIENT_DIR / "tools" / "re").replace("\\", "/")
    p_srv = str(CLIENT_DIR / "tools" / "servers").replace("\\", "/")
    p_fix = str(CLIENT_DIR / "tools" / "re" / "login_fix_hall.py").replace("\\", "/")
    p_err = str(CLIENT_DIR / "tools" / "servers" / "logs" / "INJECT_ERROR.txt").replace("\\", "/")

    runner_code = (
        "import sys, os, base64, traceback\n"
        f"for _p in ({p_tools!r}, {p_re!r}, {p_srv!r}):\n"
        "    if _p not in sys.path: sys.path.insert(0, _p)\n"
        f"__file__ = {p_fix!r}\n"
        "try:\n"
        f"    exec base64.b64decode({json.dumps(b64_str)}) in globals(), globals()\n"
        "except Exception:\n"
        "    try:\n"
        f"        _ef = open({p_err!r}, 'w')\n"
        "        _ef.write(traceback.format_exc())\n"
        "        _ef.close()\n"
        "    except Exception: pass\n"
        "    raise\n"
    )
    runner_json = json.dumps(runner_code)

    inject_log_path = os.path.join(TOOLS_DIR, "servers", "logs", "INJECT_OLD.txt")
    os.makedirs(os.path.dirname(inject_log_path), exist_ok=True)

    def write_inject_log(msg):
        try:
            with open(inject_log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except Exception:
            pass

    write_inject_log("--- client_injector attached to ros.exe ---")

    js = f"""
    var ros = Process.findModuleByName('ros.exe') || Process.enumerateModules()[0];
    var base = ros.base;
    function u8(h) {{
      var a = new Uint8Array(h.length / 2);
      for (var i = 0; i < a.length; i++) a[i] = parseInt(h.substr(i * 2, 2), 16);
      return a;
    }}
    var FORCED = u8('{bfhex}');
    var forced = 0;
    var announced = false;

    // 1. BaseApp decryption filter hook (0x176ce0)
    function forceFilter(ctx, tag) {{
      try {{
        var f = ctx.ecx;
        var sched = f.add(0x28).readPointer();
        f.add(0x20).writeU32(4);
        f.add(0x24).writeU8(1);
        sched.writeByteArray(FORCED.buffer);
        forced++;
        if (!announced) {{
          announced = true;
          send('[baseapp-force] BaseApp filter forced at ' + tag);
        }}
      }} catch (e) {{
        send('[baseapp-force] Filter error: ' + e);
      }}
    }}

    try {{
      Interceptor.attach(base.add(0x176ce0), {{
        onEnter: function() {{ forceFilter(this.context, 'EncryptionFilter::recv'); }},
        onLeave: function(r) {{
          var v = r.toInt32() >>> 0;
          if (v !== 0) send('[baseapp-force] EncryptionFilter::recv drop ret=0x' + v.toString(16));
        }}
      }});
      send('[baseapp-force] EncryptionFilter::recv hook armed at ' + base.add(0x176ce0));
    }} catch(e) {{
      send('[baseapp-force] Failed to hook EncryptionFilter: ' + e);
    }}

    // 2. PyRun injection via PyEval_EvalFrameEx (0xEC52B0) and PyRun_SimpleStringFlags (0xEAB280)
    var EVAL = base.add(0xEC52B0);
    var PyRun = new NativeFunction(base.add(0xEAB280), 'int', ['pointer', 'pointer'], 'mscdecl');
    var RUNNER = {runner_json};
    var fired = false;
    var inPayload = false;
    var attempts = 0;
    var lastTry = 0;

    try {{
      Interceptor.attach(EVAL, {{
        onEnter: function(args) {{
          if (fired || inPayload) return;
          var now = Date.now();
          if (now - lastTry < 800) return; // throttle retry to every 800ms
          lastTry = now;
          inPayload = true;
          attempts++;
          try {{
            var c = Memory.allocUtf8String(RUNNER);
            var r = PyRun(c, ptr(0));
            if (r === 0) {{
              fired = true;
              send('[injector] PyRun(login_fix_hall.py) SUCCESS (ret=0, attempt ' + attempts + ')');
            }} else {{
              send('[injector] PyRun attempt ' + attempts + ' waiting for login UI (ret=' + r + ')...');
            }}
          }} catch(e) {{
            send('[injector] PyRun ERROR: ' + e);
          }}
          inPayload = false;
        }}
      }});
      send('[injector] PyEval injection hook armed at ' + EVAL);
    }} catch(e) {{
      send('[injector] Failed to hook PyEval: ' + e);
    }}
    """

    def on_message(m, d):
        payload = m.get("payload", str(m))
        print("[Injector]", payload)
        write_inject_log(payload)

    script = session.create_script(js)
    script.on("message", on_message)
    script.load()
    print("\n" + "=" * 60)
    print(" [+] CLIENT READY! HOOK ATTACHED SUCCESSFULLY TO ROS.EXE!")
    print(" [+] PLAY button is now active and ready to click!")
    print("=" * 60 + "\n")

    detached = threading.Event()
    session.on("detached", lambda *a: detached.set())
    while not detached.is_set():
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            break
    print("[*] ros.exe session closed.")
    try:
        import account_manager
        sess_file = BASE_DIR / "data" / "current_session.json"
        if sess_file.exists():
            import json
            with open(sess_file, "r", encoding="utf-8") as sf:
                curr_u = json.load(sf).get("username")
            if curr_u:
                account_manager.sync_from_game(curr_u)
                print(f"[+] Account '{curr_u}' synced successfully to database.")
    except Exception as e:
        print(f"[!] Sync error: {e}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
