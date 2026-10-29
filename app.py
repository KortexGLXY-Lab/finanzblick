#!/usr/bin/env python3
import json
import hashlib
import mimetypes
import os
import secrets
import sqlite3
import calendar
from datetime import date
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(os.environ.get("KORTEX_ROOT", Path(__file__).parent)).resolve()
DB_PATH = Path(os.environ.get("KORTEX_DB", ROOT / "finanzen.sqlite3"))
HOST = os.environ.get("KORTEX_HOST", "0.0.0.0")
PORT = int(os.environ.get("KORTEX_PORT", "8080"))
SESSION_DAYS = 30


def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user', 'admin')),
        theme TEXT NOT NULL DEFAULT 'earth-light',
        language TEXT NOT NULL DEFAULT 'de',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )""")
    user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
    if "role" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
    if "theme" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN theme TEXT NOT NULL DEFAULT 'earth-light'")
    if "language" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN language TEXT NOT NULL DEFAULT 'de'")
    db.execute("""CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        UNIQUE(user_id, name)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        UNIQUE(user_id, name)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        amount REAL NOT NULL CHECK(amount >= 0),
        kind TEXT NOT NULL CHECK(kind IN ('income', 'expense')),
        category TEXT NOT NULL,
        entry_date TEXT NOT NULL,
        recurring INTEGER NOT NULL DEFAULT 0,
        frequency TEXT NOT NULL DEFAULT 'monthly',
        note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        recurrence_source_id INTEGER REFERENCES entries(id),
        recurrence_key TEXT UNIQUE
    )""")
    columns = {row[1] for row in db.execute("PRAGMA table_info(entries)")}
    if "user_id" not in columns:
        db.execute("ALTER TABLE entries ADD COLUMN user_id INTEGER REFERENCES users(id)")
    if "account_id" not in columns:
        db.execute("ALTER TABLE entries ADD COLUMN account_id INTEGER REFERENCES accounts(id)")
    if "recurrence_source_id" not in columns:
        db.execute("ALTER TABLE entries ADD COLUMN recurrence_source_id INTEGER REFERENCES entries(id)")
    if "recurrence_key" not in columns:
        db.execute("ALTER TABLE entries ADD COLUMN recurrence_key TEXT")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_entries_recurrence_key ON entries(recurrence_key)")
    db.execute("""CREATE TABLE IF NOT EXISTS entry_tags (
        entry_id INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
        tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
        PRIMARY KEY(entry_id, tag_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires_at TEXT NOT NULL
    )""")
    db.commit()
    return db


def add_months(value, months):
    month_index = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(month_index, 12)
    month = month_index + 1
    return value.replace(year=year, month=month, day=min(value.day, calendar.monthrange(year, month)[1]))


def materialize_due_recurring(db, user_id):
    today = date.today()
    templates = db.execute("SELECT * FROM entries WHERE user_id = ? AND recurring = 1 AND recurrence_source_id IS NULL", (user_id,)).fetchall()
    for template in templates:
        try:
            start = date.fromisoformat(template["entry_date"])
        except ValueError:
            continue
        frequency = template["frequency"] if template["frequency"] in {"monthly", "yearly"} else "monthly"
        occurrence = add_months(start, 12 if frequency == "yearly" else 1)
        while occurrence <= today:
            key = f"{template['id']}:{occurrence.isoformat()}"
            cur = db.execute("""INSERT OR IGNORE INTO entries
                (title, amount, kind, category, entry_date, recurring, frequency, note, user_id, account_id, recurrence_source_id, recurrence_key)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)""",
                (template["title"], template["amount"], template["kind"], template["category"], occurrence.isoformat(), frequency,
                 template["note"], user_id, template["account_id"], template["id"], key))
            if cur.rowcount:
                assign_tags(db, user_id, cur.lastrowid, entry_tags(db, template["id"]))
            occurrence = add_months(occurrence, 12 if frequency == "yearly" else 1)
    db.commit()


def password_hash(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 180_000)
    return f"{salt.hex()}${digest.hex()}"


def password_matches(password, stored):
    try:
        salt, expected = stored.split("$", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 180_000).hex()
        return secrets.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def request_token(handler):
    cookie = SimpleCookie(handler.headers.get("Cookie", ""))
    token = cookie.get("session")
    return token.value if token else None


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def request_user(handler):
    token = request_token(handler)
    if not token:
        return None
    db = connect()
    row = db.execute("SELECT user_id FROM sessions WHERE token_hash = ? AND expires_at > CURRENT_TIMESTAMP", (token_hash(token),)).fetchone()
    db.close()
    return row["user_id"] if row else None


def is_admin(handler):
    user_id = request_user(handler)
    if not user_id:
        return False
    db = connect()
    row = db.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    db.close()
    return bool(row and row["role"] == "admin")


def entry_tags(db, entry_id):
    return [row["name"] for row in db.execute("SELECT tags.name FROM entry_tags JOIN tags ON tags.id = entry_tags.tag_id WHERE entry_tags.entry_id = ? ORDER BY tags.name COLLATE NOCASE", (entry_id,))]


def assign_tags(db, user_id, entry_id, names):
    db.execute("DELETE FROM entry_tags WHERE entry_id = ?", (entry_id,))
    for raw_name in names or []:
        name = str(raw_name).strip()[:40]
        if not name:
            continue
        db.execute("INSERT OR IGNORE INTO tags (user_id, name) VALUES (?, ?)", (user_id, name))
        tag = db.execute("SELECT id FROM tags WHERE user_id = ? AND name = ? COLLATE NOCASE", (user_id, name)).fetchone()
        db.execute("INSERT OR IGNORE INTO entry_tags (entry_id, tag_id) VALUES (?, ?)", (entry_id, tag["id"]))


def serialize_entries(db, rows):
    result = []
    for row in rows:
        item = dict(row)
        item["tags"] = entry_tags(db, item["id"])
        result.append(item)
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send_json(self, payload, status=200):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if getattr(self, "session_cookie", None):
            self.send_header("Set-Cookie", self.session_cookie)
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/auth/status":
            db = connect()
            has_users = db.execute("SELECT EXISTS(SELECT 1 FROM users)").fetchone()[0]
            db.close()
            self.send_json({"has_users": bool(has_users)})
        elif path == "/api/me":
            user_id = request_user(self)
            if not user_id:
                self.send_json({"user": None})
                return
            db = connect()
            row = db.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,)).fetchone()
            db.close()
            self.send_json({"user": dict(row) if row else None})
        elif path == "/api/admin/users":
            if not is_admin(self):
                self.send_json({"error": "Adminrechte erforderlich"}, 403)
                return
            db = connect()
            rows = db.execute("SELECT id, username, role, created_at, (SELECT COUNT(*) FROM entries WHERE entries.user_id = users.id) AS entries FROM users ORDER BY username COLLATE NOCASE").fetchall()
            db.close()
            self.send_json([dict(row) for row in rows])
        elif path == "/api/account":
            user_id = request_user(self)
            if not user_id:
                self.send_json({"error": "Anmeldung erforderlich"}, 401)
                return
            db = connect()
            user = db.execute("SELECT id, username, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
            stats = db.execute("SELECT COUNT(*) AS count, COALESCE(SUM(CASE WHEN kind = 'income' THEN amount ELSE 0 END), 0) AS income, COALESCE(SUM(CASE WHEN kind = 'expense' THEN amount ELSE 0 END), 0) AS expense FROM entries WHERE user_id = ?", (user_id,)).fetchone()
            db.close()
            self.send_json({"user": dict(user), "stats": dict(stats)})
        elif path == "/api/preferences":
            user_id = request_user(self)
            if not user_id:
                self.send_json({"error": "Anmeldung erforderlich"}, 401)
                return
            db = connect()
            row = db.execute("SELECT theme, language FROM users WHERE id = ?", (user_id,)).fetchone()
            db.close()
            self.send_json({"theme": row["theme"] if row else "earth-light", "language": row["language"] if row else "de"})
        elif path in ("/api/accounts", "/api/tags"):
            user_id = request_user(self)
            if not user_id:
                self.send_json({"error": "Anmeldung erforderlich"}, 401)
                return
            table = "accounts" if path == "/api/accounts" else "tags"
            db = connect()
            rows = db.execute(f"SELECT id, name FROM {table} WHERE user_id = ? ORDER BY name COLLATE NOCASE", (user_id,)).fetchall()
            db.close()
            self.send_json([dict(row) for row in rows])
        elif path in ("/api/entries", "/api/summary") and not request_user(self):
            self.send_json({"error": "Anmeldung erforderlich"}, 401)
        elif path == "/api/entries":
            user_id = request_user(self)
            db = connect()
            materialize_due_recurring(db, user_id)
            rows = db.execute("SELECT * FROM entries WHERE user_id = ? ORDER BY entry_date DESC, id DESC", (user_id,)).fetchall()
            self.send_json(serialize_entries(db, rows))
            db.close()
        elif path == "/api/summary":
            user_id = request_user(self)
            db = connect()
            materialize_due_recurring(db, user_id)
            rows = db.execute("SELECT * FROM entries WHERE user_id = ? ORDER BY entry_date", (user_id,)).fetchall()
            self.send_json(summary([dict(row) for row in rows]))
            db.close()
        else:
            self.serve_file(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/logout":
            token = request_token(self)
            if token:
                db = connect()
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
                db.commit()
                db.close()
            self.session_cookie = "session=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict"
            self.send_json({"ok": True})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            item = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)
            return
        if path == "/api/account/password":
            user_id = request_user(self)
            current = str(item.get("current_password", ""))
            new_password = str(item.get("new_password", ""))
            if not user_id:
                self.send_json({"error": "Anmeldung erforderlich"}, 401)
                return
            if len(new_password) < 8:
                self.send_json({"error": "Das neue Passwort muss mindestens 8 Zeichen haben"}, 400)
                return
            db = connect()
            user = db.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
            if not user or not password_matches(current, user["password_hash"]):
                db.close()
                self.send_json({"error": "Das aktuelle Passwort ist falsch"}, 400)
                return
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash(new_password), user_id))
            db.commit()
            db.close()
            self.send_json({"ok": True})
            return
        if path == "/api/admin/users":
            if not is_admin(self):
                self.send_json({"error": "Adminrechte erforderlich"}, 403)
                return
            username = str(item.get("username", "")).strip()
            password = str(item.get("password", ""))
            if len(username) < 3 or len(password) < 8:
                self.send_json({"error": "Benutzername: mindestens 3 Zeichen, Passwort: mindestens 8 Zeichen"}, 400)
                return
            db = connect()
            try:
                cur = db.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'user')", (username, password_hash(password)))
                db.commit()
                row = db.execute("SELECT id, username, role, created_at FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
            except sqlite3.IntegrityError:
                db.close()
                self.send_json({"error": "Dieser Benutzername ist bereits vergeben"}, 409)
                return
            db.close()
            self.send_json(dict(row), 201)
            return
        if path == "/api/register":
            username = str(item.get("username", "")).strip()
            password = str(item.get("password", ""))
            password_confirmation = str(item.get("password_confirmation", ""))
            if len(username) < 3 or len(password) < 8:
                self.send_json({"error": "Benutzername: mindestens 3 Zeichen, Passwort: mindestens 8 Zeichen"}, 400)
                return
            if password != password_confirmation:
                self.send_json({"error": "Die Passwörter stimmen nicht überein"}, 400)
                return
            db = connect()
            try:
                cur = db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash(password)))
                user_id = cur.lastrowid
                if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1:
                    db.execute("UPDATE entries SET user_id = ? WHERE user_id IS NULL", (user_id,))
                db.commit()
            except sqlite3.IntegrityError:
                db.close()
                self.send_json({"error": "Dieser Benutzername ist bereits vergeben"}, 409)
                return
            db.close()
            self.start_session(user_id)
            self.send_json({"ok": True}, 201)
            return
        if path in ("/api/accounts", "/api/tags"):
            user_id = request_user(self)
            name = str(item.get("name", "")).strip()[:40]
            if not user_id:
                self.send_json({"error": "Anmeldung erforderlich"}, 401)
                return
            if not name:
                self.send_json({"error": "Bitte einen Namen eingeben"}, 400)
                return
            table = "accounts" if path == "/api/accounts" else "tags"
            db = connect()
            try:
                cur = db.execute(f"INSERT INTO {table} (user_id, name) VALUES (?, ?)", (user_id, name))
                db.commit()
            except sqlite3.IntegrityError:
                db.close()
                self.send_json({"error": "Dieser Name existiert bereits"}, 409)
                return
            db.close()
            self.send_json({"id": cur.lastrowid, "name": name}, 201)
            return
        if path == "/api/login":
            db = connect()
            row = db.execute("SELECT id, username, password_hash FROM users WHERE username = ? COLLATE NOCASE", (str(item.get("username", "")).strip(),)).fetchone()
            db.close()
            if not row or not password_matches(str(item.get("password", "")), row["password_hash"]):
                self.send_json({"error": "Benutzername oder Passwort ist falsch"}, 401)
                return
            self.start_session(row["id"])
            self.send_json({"ok": True})
            return
        user_id = request_user(self)
        if path != "/api/entries" or not user_id:
            self.send_json({"error": "Nicht gefunden"}, 404)
            return
        try:
            title = str(item.get("title", "")).strip()
            amount = float(item.get("amount", 0))
            kind = item.get("kind")
            category = str(item.get("category", "Sonstiges")).strip() or "Sonstiges"
            entry_date = item.get("entry_date") or date.today().isoformat()
            frequency = item.get("frequency", "monthly")
            if frequency not in ("monthly", "yearly"):
                raise ValueError("Ungültige Wiederholungsfrequenz")
            if not title or amount < 0 or kind not in ("income", "expense"):
                raise ValueError("Titel, Betrag und Art sind erforderlich")
            db = connect()
            cur = db.execute("INSERT INTO entries (title, amount, kind, category, entry_date, recurring, frequency, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (title, amount, kind, category, entry_date, int(bool(item.get("recurring"))), frequency, str(item.get("note", ""))))
            db.execute("UPDATE entries SET user_id = ? WHERE id = ?", (user_id, cur.lastrowid))
            account_id = item.get("account_id")
            if account_id:
                db.execute("UPDATE entries SET account_id = (SELECT id FROM accounts WHERE id = ? AND user_id = ?) WHERE id = ? AND user_id = ?", (account_id, user_id, cur.lastrowid, user_id))
            assign_tags(db, user_id, cur.lastrowid, item.get("tags", []))
            db.commit()
            row = db.execute("SELECT * FROM entries WHERE id = ?", (cur.lastrowid,)).fetchone()
            result = dict(row)
            result["tags"] = entry_tags(db, cur.lastrowid)
            db.close()
            self.send_json(result, 201)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)

    def start_session(self, user_id):
        token = secrets.token_urlsafe(32)
        db = connect()
        db.execute("DELETE FROM sessions WHERE expires_at <= CURRENT_TIMESTAMP")
        db.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, datetime('now', ?))", (token_hash(token), user_id, f"+{SESSION_DAYS} days"))
        db.commit()
        db.close()
        self.session_cookie = f"session={token}; Max-Age={SESSION_DAYS * 86400}; Path=/; HttpOnly; SameSite=Strict"

    def do_PUT(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        user_id = request_user(self)
        if urlparse(self.path).path == "/api/preferences":
            if not user_id:
                self.send_json({"error": "Anmeldung erforderlich"}, 401)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                item = json.loads(self.rfile.read(length))
                theme = str(item.get("theme", "earth-light"))
                language = str(item.get("language", "de"))
                if theme not in {"earth-light", "forest-dark", "sand-light", "slate-dark", "mono", "pink-bloom", "bioluminescent"}:
                    raise ValueError("Ungültiges Theme")
                if language not in {"de", "en"}:
                    raise ValueError("Ungültige Sprache")
                db = connect()
                db.execute("UPDATE users SET theme = ?, language = ? WHERE id = ?", (theme, language, user_id))
                db.commit()
                db.close()
                self.send_json({"theme": theme, "language": language})
            except (ValueError, json.JSONDecodeError) as exc:
                self.send_json({"error": str(exc)}, 400)
            return
        if len(parts) == 5 and parts[:3] == ["api", "admin", "users"] and parts[4] == "password":
            if not is_admin(self):
                self.send_json({"error": "Adminrechte erforderlich"}, 403)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                item = json.loads(self.rfile.read(length))
                new_password = str(item.get("password", ""))
                if len(new_password) < 8:
                    raise ValueError("Das Passwort muss mindestens 8 Zeichen haben")
                db = connect()
                db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash(new_password), parts[3]))
                db.commit()
                changed = db.total_changes
                db.close()
                if not changed:
                    self.send_json({"error": "Benutzer nicht gefunden"}, 404)
                else:
                    self.send_json({"ok": True})
            except (ValueError, json.JSONDecodeError) as exc:
                self.send_json({"error": str(exc)}, 400)
            return
        if len(parts) != 3 or parts[:2] != ["api", "entries"] or not user_id:
            self.send_json({"error": "Nicht gefunden"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            item = json.loads(self.rfile.read(length))
            title = str(item.get("title", "")).strip()
            amount = float(item.get("amount", 0))
            kind = item.get("kind")
            category = str(item.get("category", "Sonstiges")).strip() or "Sonstiges"
            entry_date = item.get("entry_date") or date.today().isoformat()
            frequency = item.get("frequency", "monthly")
            if frequency not in ("monthly", "yearly"):
                raise ValueError("Ungültige Wiederholungsfrequenz")
            if not title or amount < 0 or kind not in ("income", "expense"):
                raise ValueError("Titel, Betrag und Art sind erforderlich")
            db = connect()
            db.execute("UPDATE entries SET title = ?, amount = ?, kind = ?, category = ?, entry_date = ?, recurring = ?, frequency = ?, note = ? WHERE id = ? AND user_id = ?",
                (title, amount, kind, category, entry_date, int(bool(item.get("recurring"))), frequency, str(item.get("note", "")), parts[2], user_id))
            db.execute("UPDATE entries SET account_id = (SELECT id FROM accounts WHERE id = ? AND user_id = ?) WHERE id = ? AND user_id = ?", (item.get("account_id") or None, user_id, parts[2], user_id))
            assign_tags(db, user_id, parts[2], item.get("tags", []))
            db.commit()
            row = db.execute("SELECT * FROM entries WHERE id = ? AND user_id = ?", (parts[2], user_id)).fetchone()
            result = dict(row) if row else None
            if result:
                result["tags"] = entry_tags(db, parts[2])
            db.close()
            if row is None:
                self.send_json({"error": "Eintrag nicht gefunden"}, 404)
            else:
                self.send_json(result)
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, 400)

    def do_DELETE(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 4 and parts[:3] == ["api", "admin", "users"]:
            if not is_admin(self):
                self.send_json({"error": "Adminrechte erforderlich"}, 403)
                return
            if str(request_user(self)) == parts[3]:
                self.send_json({"error": "Der eigene Admin-Benutzer kann hier nicht gelöscht werden"}, 400)
                return
            db = connect()
            db.execute("DELETE FROM entries WHERE user_id = ?", (parts[3],))
            db.execute("DELETE FROM sessions WHERE user_id = ?", (parts[3],))
            db.execute("DELETE FROM users WHERE id = ? AND role = 'user'", (parts[3],))
            deleted = db.total_changes
            db.commit()
            db.close()
            self.send_json({"ok": bool(deleted)})
            return
        if urlparse(self.path).path == "/api/account":
            user_id = request_user(self)
            if not user_id:
                self.send_json({"error": "Anmeldung erforderlich"}, 401)
                return
            db = connect()
            db.execute("DELETE FROM entries WHERE user_id = ?", (user_id,))
            db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            db.commit()
            db.close()
            token = request_token(self)
            if token:
                session_db = connect()
                session_db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
                session_db.commit()
                session_db.close()
            self.session_cookie = "session=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict"
            self.send_json({"ok": True})
            return
        user_id = request_user(self)
        if len(parts) != 3 or parts[:2] != ["api", "entries"] or not user_id:
            self.send_json({"error": "Nicht gefunden"}, 404)
            return
        db = connect()
        db.execute("DELETE FROM entries WHERE id = ? AND user_id = ?", (parts[2], user_id))
        db.commit()
        db.close()
        self.send_json({"ok": True})

    def serve_file(self, path):
        requested = "/index.html" if path == "/" else path
        file_path = (ROOT / requested.lstrip("/")).resolve()
        if ROOT not in file_path.parents or not file_path.is_file():
            self.send_json({"error": "Nicht gefunden"}, 404)
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def summary(rows):
    income = sum(r["amount"] for r in rows if r["kind"] == "income")
    expense = sum(r["amount"] for r in rows if r["kind"] == "expense")
    fixed = sum(r["amount"] for r in rows if r["kind"] == "expense" and r["recurring"])
    categories = {}
    for row in rows:
        if row["kind"] == "expense":
            categories[row["category"]] = categories.get(row["category"], 0) + row["amount"]
    months = {}
    for row in rows:
        month = row["entry_date"][:7]
        months.setdefault(month, {"income": 0, "expense": 0})[row["kind"]] += row["amount"]
    return {"income": income, "expense": expense, "balance": income - expense, "fixed": fixed, "categories": categories, "months": months, "count": len(rows)}


def create_server():
    db = connect()
    db.close()
    return ThreadingHTTPServer((HOST, PORT), Handler)


def start_server():
    server = create_server()
    print(f"KortexFinance läuft auf http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer beendet.")


if __name__ == "__main__":
    start_server()
