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
CONFIG = os.path.join(HERE, "jarvis_config.json")  # your Gmail app password is stored here, on this computer only

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


# ---------------- school email (Gmail over IMAP) ----------------
def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    try:
        os.chmod(CONFIG, 0o600)
    except Exception:
        pass


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
    m = gmail_login(cfg["address"], cfg["app_password"])
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

    def from_jarvis(self):
        # Only the Jarvis page sends this header; other websites can't, so they can't use these endpoints.
        if self.headers.get("X-Jarvis") == "1":
            return True
        self.send_json(403, {"ok": False, "error": "forbidden"})
        return False

    def do_GET(self):
        if self.path.startswith("/api/"):
            if not self.from_jarvis():
                return
            if self.path == "/api/school/status":
                cfg = load_config()
                return self.send_json(200, {"configured": bool(cfg.get("app_password")), "address": cfg.get("address", ""),
                                            "school_address": cfg.get("school_address", "")})
            if self.path == "/api/school/emails":
                cfg = load_config()
                if not cfg.get("app_password"):
                    return self.send_json(409, {"ok": False, "error": "not_configured"})
                try:
                    return self.send_json(200, {"ok": True, "emails": fetch_school_emails(cfg)})
                except imaplib.IMAP4.error as e:
                    return self.send_json(401, {"ok": False, "error": "Gmail refused the login: " + str(e)})
                except Exception as e:
                    return self.send_json(502, {"ok": False, "error": "Couldn't reach Gmail: " + str(e)})
            return self.send_json(404, {"ok": False})
        if not self.path.split("?")[0].endswith((".html", "/")):
            return self.send_error(404)  # never serve the config file or the Python code
        return super().do_GET()

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
            save_config({"address": address, "app_password": app_password, "school_address": school_address})
            return self.send_json(200, {"ok": True})

        if self.path == "/api/school/forget":
            try:
                os.remove(CONFIG)
            except FileNotFoundError:
                pass
            return self.send_json(200, {"ok": True})

        return self.send_json(404, {"ok": False})

    def end_headers(self):
        if self.path.endswith(".html") or self.path == "/":
            self.send_header("Cache-Control", "no-cache")
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
