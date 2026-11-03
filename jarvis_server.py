"""
JARVIS local server.
Serves jarvis_vision.html, lets the page change your computer's volume,
and reads your school emails (Google Classroom + university mail) from Gmail.

Run it from the jarvis folder:   python jarvis_server.py
Then open:                       http://127.0.0.1:8000/jarvis_vision.html
Stop it with Ctrl + C.
"""

import email
import email.header
import email.utils
import http.server
import imaplib
import json
import os
import re
import socketserver
import subprocess
import sys
from html import unescape

PORT = 8000
HOST = "127.0.0.1"  # only this computer can reach it
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "jarvis_config.json")  # Gmail settings; the app password inside is encrypted (Windows/macOS)
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}  # blocks "DNS rebinding" tricks from other websites

# Only these sites may be contacted by the page. Even if a library were ever tampered with,
# it couldn't send your keys anywhere else.
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdn.jsdelivr.net",
    "connect-src 'self' https://api.anthropic.com https://api.openai.com https://accounts.spotify.com "
    "https://api.spotify.com https://cdn.jsdelivr.net https://storage.googleapis.com",
    "img-src 'self' data: blob: https://*.scdn.co https://*.spotifycdn.com",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "media-src 'self' blob: mediastream:",
    "worker-src 'self' blob: https://cdn.jsdelivr.net",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'none'",
])

# Windows virtual key codes for the media volume keys
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
KEYEVENTF_KEYUP = 0x0002


# ---------------- volume ----------------
def press_volume_key(action, steps):
    """Press the system volume key `steps` times. Each step is about 2% on Windows."""
    if sys.platform == "win32":
        import ctypes
        vk = {"up": VK_VOLUME_UP, "down": VK_VOLUME_DOWN, "mute": VK_VOLUME_MUTE}[action]
        for _ in range(1 if action == "mute" else steps):
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        return True
    if sys.platform == "darwin":
        if action == "mute":
            script = "set volume output muted not (output muted of (get volume settings))"
        else:
            sign = "+" if action == "up" else "-"
            script = f"set volume output volume ((output volume of (get volume settings)) {sign} {2 * steps})"
        subprocess.run(["osascript", "-e", script], check=False)
        return True
    return False


# ---------------- secret storage ----------------
# Windows: encrypted with DPAPI (only your Windows user account can decrypt it).
# macOS: stored in the Keychain. Elsewhere: a file only you can read.
KEYCHAIN_SERVICE = "jarvis-gmail-app-password"


def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise OSError("Windows could not encrypt/decrypt the password")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def protect_secret(secret, account):
    if sys.platform == "win32":
        import base64
        return {"app_password_dpapi": base64.b64encode(_dpapi(secret.encode(), True)).decode()}
    if sys.platform == "darwin":
        r = subprocess.run(["security", "add-generic-password", "-U", "-a", account, "-s", KEYCHAIN_SERVICE, "-w", secret],
                           capture_output=True)
        if r.returncode == 0:
            return {"app_password_keychain": True}
    return {"app_password": secret}  # fallback: plain, but the file is made private below


def reveal_secret(cfg):
    if cfg.get("app_password_dpapi"):
        import base64
        return _dpapi(base64.b64decode(cfg["app_password_dpapi"]), False).decode()
    if cfg.get("app_password_keychain"):
        r = subprocess.run(["security", "find-generic-password", "-a", cfg.get("address", ""), "-s", KEYCHAIN_SERVICE, "-w"],
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    return cfg.get("app_password", "")


def has_secret(cfg):
    return bool(cfg.get("app_password_dpapi") or cfg.get("app_password_keychain") or cfg.get("app_password"))


# ---------------- school email (Gmail over IMAP) ----------------
def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return {}
    if cfg.get("app_password") and sys.platform in ("win32", "darwin"):
        try:  # upgrade an older plain-text config to encrypted storage
            save_config(cfg["address"], cfg["app_password"], cfg.get("school_address", ""))
            return load_config()
        except Exception:
            pass
    return cfg


def save_config(address, app_password, school_address):
    try:
        stored = protect_secret(app_password, address)
    except Exception:
        stored = {"app_password": app_password}
    cfg = {"address": address, "school_address": school_address, **stored}
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    try:
        os.chmod(tmp, 0o600)
    except Exception:
        pass
    os.replace(tmp, CONFIG)


def gmail_login(address, app_password):
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=30)
    m.login(address, app_password.replace(" ", ""))
    return m


def decode_header(value):
    parts = []
    for text, enc in email.header.decode_header(value or ""):
        if isinstance(text, bytes):
            try:
                text = text.decode(enc or "utf-8", errors="replace")
            except LookupError:
                text = text.decode("utf-8", errors="replace")
        parts.append(text)
    return "".join(parts).strip()


def body_text(msg):
    """Plain-text body (falls back to stripped HTML), shortened."""
    plain, html = None, None
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() != "text" or part.get("Content-Disposition", "").startswith("attachment"):
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        if part.get_content_subtype() == "plain" and plain is None:
            plain = text
        elif part.get_content_subtype() == "html" and html is None:
            html = text
    if plain is None and html:
        plain = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        plain = unescape(re.sub(r"<[^>]+>", " ", plain))
    links = re.findall(r"https://classroom\.google\.com/[^\s\"'<>)]+", (html or "") + " " + (plain or ""))
    text = re.sub(r"\s+", " ", plain or "").strip()
    return text[:1800], (links[0] if links else "")


def fetch_school_emails(cfg, days=21, limit=40):
    school = cfg.get("school_address", "")
    query = f"(from:classroom.google.com OR to:{school} OR deliveredto:{school}) newer_than:{days}d" if school \
        else f"from:classroom.google.com newer_than:{days}d"
    m = gmail_login(cfg["address"], reveal_secret(cfg))
    try:
        folder = '"[Gmail]/All Mail"'
        typ, boxes = m.list()
        for line in boxes or []:  # find "All Mail" even when Gmail's language isn't English
            line = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
            if "\\All" in line:
                folder = line[line.rfind(' "/" ') + 5:].strip() if ' "/" ' in line else folder
                break
        m.select(folder, readonly=True)
        typ, data = m.uid("SEARCH", "X-GM-RAW", '"' + query.replace('"', "") + '"')
        uids = (data[0] or b"").split()[-limit:]
        out = []
        for uid in reversed(uids):
            typ, msgdata = m.uid("FETCH", uid, "(X-GM-THRID BODY.PEEK[])")
            raw, thrid = None, ""
            for item in msgdata:
                if isinstance(item, tuple):
                    raw = item[1]
                    found = re.search(rb"X-GM-THRID (\d+)", item[0])
                    if found:
                        thrid = found.group(1).decode()
            if not raw:
                continue
            msg = email.message_from_bytes(raw)
            text, link = body_text(msg)
            try:
                date = email.utils.parsedate_to_datetime(msg.get("Date")).isoformat()
            except Exception:
                date = msg.get("Date", "")
            out.append({"id": f"{thrid or uid.decode()}-{uid.decode()}", "thread": thrid, "from": decode_header(msg.get("From")),
                        "subject": decode_header(msg.get("Subject")), "date": date, "text": text, "link": link})
        return out
    finally:
        try:
            m.logout()
        except Exception:
            pass


# ---------------- web server ----------------
class JarvisHandler(http.server.SimpleHTTPRequestHandler):
    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def host_ok(self):
        return self.headers.get("Host", "") in ALLOWED_HOSTS

    def from_jarvis(self):
        # Only the Jarvis page, opened at 127.0.0.1, sends this header from the right address.
        # Other websites can't, so they can't use these endpoints.
        if self.headers.get("X-Jarvis") == "1" and self.host_ok() and \
                self.headers.get("Origin", f"http://127.0.0.1:{PORT}") in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return True
        self.send_json(403, {"ok": False, "error": "forbidden"})
        return False

    def do_GET(self):
        if self.path.startswith("/api/"):
            if not self.from_jarvis():
                return
            if self.path == "/api/school/status":
                cfg = load_config()
                return self.send_json(200, {"configured": has_secret(cfg), "address": cfg.get("address", ""),
                                            "school_address": cfg.get("school_address", "")})
            if self.path == "/api/school/emails":
                cfg = load_config()
                if not has_secret(cfg):
                    return self.send_json(409, {"ok": False, "error": "not_configured"})
                try:
                    return self.send_json(200, {"ok": True, "emails": fetch_school_emails(cfg)})
                except imaplib.IMAP4.error as e:
                    return self.send_json(401, {"ok": False, "error": "Gmail refused the login: " + str(e)})
                except Exception as e:
                    return self.send_json(502, {"ok": False, "error": "Couldn't reach Gmail: " + str(e)})
            return self.send_json(404, {"ok": False})
        if not self.host_ok():
            return self.send_error(403)
        if not self.path.split("?")[0].endswith((".html", "/")) or "config" in self.path.lower():
            return self.send_error(404)  # never serve the config file or the Python code
        return super().do_GET()

    def list_directory(self, path):
        return self.send_error(404)  # no folder listings

    def do_POST(self):
        if not self.from_jarvis():
            return
        try:
            data = self.read_json()
        except Exception:
            return self.send_json(400, {"ok": False, "error": "bad request"})

        if self.path == "/api/volume":
            action = str(data.get("action", ""))
            if action not in ("up", "down", "mute"):
                return self.send_json(400, {"ok": False, "error": "action must be up, down or mute"})
            try:
                steps = max(1, min(25, int(data.get("steps", 1))))
            except Exception:
                steps = 1
            ok = press_volume_key(action, steps)
            return self.send_json(200 if ok else 501, {"ok": ok})

        if self.path == "/api/school/config":
            address = str(data.get("address", "")).strip()
            app_password = str(data.get("app_password", "")).strip()
            school_address = str(data.get("school_address", "")).strip()
            if "@" not in address or len(app_password.replace(" ", "")) < 16:
                return self.send_json(400, {"ok": False, "error": "Enter your Gmail address and the 16-letter app password."})
            try:
                gmail_login(address, app_password).logout()
            except imaplib.IMAP4.error:
                return self.send_json(401, {"ok": False, "error": "Gmail rejected that address or app password."})
            except Exception as e:
                return self.send_json(502, {"ok": False, "error": "Couldn't reach Gmail: " + str(e)})
            save_config(address, app_password, school_address)
            return self.send_json(200, {"ok": True})

        if self.path == "/api/school/forget":
            if sys.platform == "darwin":
                subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE], capture_output=True)
            try:
                os.remove(CONFIG)
            except FileNotFoundError:
                pass
            return self.send_json(200, {"ok": True})

        return self.send_json(404, {"ok": False})

    def end_headers(self):
        if self.path.split("?")[0].endswith(".html") or self.path == "/":
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def log_message(self, fmt, *args):
        # Keep the window quiet: only show page loads
        if "/api/" not in (str(args[0]) if args else ""):
            super().log_message(fmt, *args)


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    os.chdir(HERE)  # serve the jarvis folder
    try:
        with Server((HOST, PORT), JarvisHandler) as httpd:
            print("JARVIS server online.")
            print(f"Open http://{HOST}:{PORT}/jarvis_vision.html in Chrome.")
            print("Keep this window open. Press Ctrl + C to stop.")
            httpd.serve_forever()
    except OSError:
        print(f"Port {PORT} is already in use. Close the other CMD window running Jarvis, then try again.")
    except KeyboardInterrupt:
        print("\nJARVIS server offline.")
