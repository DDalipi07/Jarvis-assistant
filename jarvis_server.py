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
import mimetypes
import os
import re
import secrets
import time
import urllib.parse
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
    "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdn.jsdelivr.net https://accounts.google.com/gsi/client",
    "connect-src 'self' https://api.anthropic.com https://api.openai.com https://accounts.spotify.com "
    "https://api.spotify.com https://cdn.jsdelivr.net https://storage.googleapis.com "
    "https://docs.googleapis.com https://slides.googleapis.com https://www.googleapis.com https://accounts.google.com/gsi/",
    "frame-src https://docs.google.com https://accounts.google.com https://www.youtube-nocookie.com https://www.youtube.com",
    "img-src 'self' data: blob: https://*.scdn.co https://*.spotifycdn.com https://*.googleusercontent.com https://i.ytimg.com",
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


def write_config(cfg):
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    try:
        os.chmod(tmp, 0o600)
    except Exception:
        pass
    os.replace(tmp, CONFIG)


def save_config(address, app_password, school_address):
    try:
        stored = protect_secret(app_password, address)
    except Exception:
        stored = {"app_password": app_password}
    cfg = {k: v for k, v in load_config_raw().items() if not k.startswith("app_password")}
    cfg.update({"address": address, "school_address": school_address, **stored})
    write_config(cfg)


def load_config_raw():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ---------------- stock prices (Yahoo Finance's public chart feed, no key needed) ----------------
_stock_cache = {}


def fetch_stock(symbol):
    import urllib.request
    hit = _stock_cache.get(symbol)
    if hit and time.time() - hit[0] < 55:
        return hit[1]
    out = None
    for rng, iv in (("1d", "5m"), ("5d", "30m")):
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range={rng}&interval={iv}&includePrePost=false"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Jarvis personal dashboard)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        res = (data.get("chart") or {}).get("result") or []
        if not res:
            continue
        res = res[0]
        meta = res.get("meta", {})
        closes = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        pts = [[t * 1000, round(c, 4)] for t, c in zip(res.get("timestamp") or [], closes) if c is not None]
        if len(pts) < 2:
            continue
        prev = meta.get("chartPreviousClose") if rng == "1d" else pts[0][1]
        price = meta.get("regularMarketPrice") or pts[-1][1]
        out = {"symbol": symbol, "price": price, "prev": prev, "currency": meta.get("currency", "USD"),
               "change": round((price - prev) / prev * 100, 2) if prev else None, "points": pts[-160:], "range": rng,
               "time": (meta.get("regularMarketTime") or 0) * 1000}
        break
    if out:
        _stock_cache[symbol] = (time.time(), out)
    return out


# ---------------- your folders (read-only browsing, open on this computer) ----------------
FILE_TOKEN = secrets.token_urlsafe(24)  # changes every time the server starts; lets the page open previews
BLOCK_OPEN = {".exe", ".bat", ".cmd", ".com", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".msi", ".msp",
              ".scr", ".lnk", ".reg", ".hta", ".jar", ".cpl", ".pif", ".url", ".sh", ".app", ".command", ".py", ".pyw"}
ACTIVE_TYPES = {".html", ".htm", ".svg", ".xml", ".xhtml", ".js", ".mjs", ".css"}  # shown as plain text, never run
SKIP_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}


def folder_roots():
    return [r for r in load_config_raw().get("folders", []) if os.path.isdir(r)]


def resolve_inside(root_index, rel):
    """Turn (root, relative path) into a real path, refusing anything outside the shared folder."""
    roots = folder_roots()
    if not (0 <= root_index < len(roots)):
        raise PermissionError("unknown folder")
    root = os.path.realpath(roots[root_index])
    full = os.path.realpath(os.path.join(root, *[p for p in str(rel).replace("\\", "/").split("/") if p not in ("", ".")]))
    if os.path.commonpath([root, full]) != root:
        raise PermissionError("outside the shared folder")
    return root, full


def entry_info(root, full):
    st = os.stat(full)
    rel = os.path.relpath(full, root).replace("\\", "/")
    return {"name": os.path.basename(full), "path": "" if rel == "." else rel, "dir": os.path.isdir(full),
            "size": st.st_size, "modified": int(st.st_mtime * 1000)}


def list_folder(root_index, rel):
    root, full = resolve_inside(root_index, rel)
    out = []
    with os.scandir(full) as it:
        for e in it:
            if e.name.lower() in SKIP_NAMES or e.name.startswith(("~$", ".")):
                continue
            try:
                out.append(entry_info(root, e.path))
            except OSError:
                pass
    out.sort(key=lambda x: (not x["dir"], x["name"].lower()))
    return out[:500]


def search_folder(root_index, query, limit=40):
    root, _ = resolve_inside(root_index, "")
    words = [w for w in query.lower().split() if w]
    hits, started = [], time.time()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in dirnames + filenames:
            if name.lower() in SKIP_NAMES or name.startswith("~$"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root).lower()
            if all(w in rel for w in words):
                try:
                    hits.append(entry_info(root, os.path.join(dirpath, name)))
                except OSError:
                    pass
                if len(hits) >= limit:
                    return hits
        if time.time() - started > 4:
            break
    return hits


def find_named_folders(name):
    """Look for a folder with this name in the usual places (Desktop, Documents, Downloads, OneDrive)."""
    home = os.path.expanduser("~")
    bases = [home] + [os.path.join(home, d) for d in ("Desktop", "Documents", "Downloads", "Pictures")]
    for od in [os.path.join(home, d) for d in os.listdir(home) if d.lower().startswith("onedrive")] if os.path.isdir(home) else []:
        bases += [od] + [os.path.join(od, d) for d in ("Desktop", "Documents", "Dokumente", "Dokumentet")]
    target, found, seen = name.strip().lower(), [], set()
    for base in bases:
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, _ in os.walk(base):
            depth = dirpath[len(base):].count(os.sep)
            dirnames[:] = [d for d in dirnames if not d.startswith((".", "$")) and d.lower() not in ("appdata", "node_modules")]
            for d in dirnames:
                if d.lower() == target:
                    real = os.path.realpath(os.path.join(dirpath, d))
                    if real not in seen:
                        seen.add(real); found.append(real)
            if depth >= 2:
                dirnames[:] = []
            if len(found) >= 10:
                return found
    return found


def open_on_computer(full):
    """Open a file with its normal app (Word, PDF reader...). Programs and scripts are only shown in the folder."""
    ext = os.path.splitext(full)[1].lower()
    if sys.platform == "win32":
        if os.path.isdir(full):
            os.startfile(full)
        elif ext in BLOCK_OPEN:
            subprocess.Popen(["explorer", "/select,", full])
        else:
            os.startfile(full)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", full] if ext in BLOCK_OPEN else ["open", full])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(full) if ext in BLOCK_OPEN else full])


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
            if self.path.startswith("/api/stocks"):
                syms = [x.strip().upper() for x in self.query().get("symbols", "").split(",") if x.strip()][:8]
                syms = [x for x in syms if re.fullmatch(r"[A-Z0-9.^=-]{1,12}", x)]
                out, errors = [], []
                for sym in syms:
                    try:
                        q = fetch_stock(sym)
                        out.append(q) if q else errors.append(sym)
                    except Exception:
                        errors.append(sym)
                return self.send_json(200, {"ok": True, "quotes": out, "failed": errors})
            if self.path.startswith("/api/files/"):
                return self.files_get()
            return self.send_json(404, {"ok": False})
        if self.path.startswith("/files/raw?"):
            return self.files_raw()
        if not self.host_ok():
            return self.send_error(403)
        if not self.path.split("?")[0].endswith((".html", "/")) or "config" in self.path.lower():
            return self.send_error(404)  # never serve the config file or the Python code
        return super().do_GET()

    # ----- folders -----
    def query(self):
        return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).items()}

    def files_get(self):
        q, route = self.query(), urllib.parse.urlsplit(self.path).path
        try:
            if route == "/api/files/roots":
                return self.send_json(200, {"ok": True, "token": FILE_TOKEN,
                                            "roots": [{"index": i, "name": os.path.basename(r) or r, "path": r} for i, r in enumerate(folder_roots())]})
            if route == "/api/files/find":
                return self.send_json(200, {"ok": True, "found": find_named_folders(q.get("name", ""))[:10]})
            if route == "/api/files/list":
                return self.send_json(200, {"ok": True, "items": list_folder(int(q.get("root", 0)), q.get("path", ""))})
            if route == "/api/files/search":
                return self.send_json(200, {"ok": True, "items": search_folder(int(q.get("root", 0)), q.get("q", ""))})
        except PermissionError as e:
            return self.send_json(403, {"ok": False, "error": str(e)})
        except FileNotFoundError:
            return self.send_json(404, {"ok": False, "error": "That file or folder no longer exists."})
        except Exception as e:
            return self.send_json(500, {"ok": False, "error": str(e)})
        return self.send_json(404, {"ok": False})

    def files_raw(self):
        """Preview a file in the browser. Needs the secret token, so other websites can't read your files."""
        q = self.query()
        if not self.host_ok() or not secrets.compare_digest(q.get("t", ""), FILE_TOKEN):
            return self.send_error(403)
        try:
            _, full = resolve_inside(int(q.get("root", 0)), q.get("path", ""))
        except Exception:
            return self.send_error(404)
        if not os.path.isfile(full):
            return self.send_error(404)
        ext = os.path.splitext(full)[1].lower()
        ctype = "text/plain; charset=utf-8" if ext in ACTIVE_TYPES else (mimetypes.guess_type(full)[0] or "application/octet-stream")
        size = os.path.getsize(full)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        name = urllib.parse.quote(os.path.basename(full))
        self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{name}")
        self.send_header("Cache-Control", "no-store")
        if not ctype.startswith(("application/pdf", "image/", "audio/", "video/")):
            self.send_header("Content-Security-Policy", "sandbox; default-src 'none'; style-src 'unsafe-inline'")
        self.end_headers()
        with open(full, "rb") as f:
            while True:
                chunk = f.read(1 << 16)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break

    def do_HEAD(self):
        return self.send_error(405)  # only GET and POST are used; keeps every check in one place

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

        if self.path == "/api/files/add":
            path = os.path.realpath(os.path.expanduser(str(data.get("path", "")).strip().strip('"')))
            if not os.path.isdir(path):
                return self.send_json(404, {"ok": False, "error": "Couldn't find that folder on this computer."})
            home = os.path.realpath(os.path.expanduser("~"))
            if path in (home, os.path.realpath(os.sep), os.path.realpath(os.path.splitdrive(home)[0] + os.sep)):
                return self.send_json(400, {"ok": False, "error": "Pick a specific folder, not your whole drive or home folder."})
            cfg = load_config_raw()
            folders = [f for f in cfg.get("folders", []) if f != path] + [path]
            cfg["folders"] = folders[-8:]
            write_config(cfg)
            return self.send_json(200, {"ok": True})

        if self.path == "/api/files/remove":
            cfg = load_config_raw()
            roots = cfg.get("folders", [])
            i = int(data.get("root", -1))
            if 0 <= i < len(roots):
                roots.pop(i)
            cfg["folders"] = roots
            write_config(cfg)
            return self.send_json(200, {"ok": True})

        if self.path == "/api/files/open":
            try:
                _, full = resolve_inside(int(data.get("root", 0)), data.get("path", ""))
                if not os.path.exists(full):
                    return self.send_json(404, {"ok": False, "error": "That file no longer exists."})
                open_on_computer(full)
                return self.send_json(200, {"ok": True})
            except PermissionError as e:
                return self.send_json(403, {"ok": False, "error": str(e)})
            except Exception as e:
                return self.send_json(500, {"ok": False, "error": str(e)})

        if self.path == "/api/school/forget":
            if sys.platform == "darwin":
                subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE], capture_output=True)
            cfg = {k: v for k, v in load_config_raw().items() if not k.startswith("app_password") and k not in ("address", "school_address")}
            write_config(cfg)
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
