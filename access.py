"""HTTP integration for the optional membership gate."""
import json
import os
import time
from contextlib import closing
from http.cookies import SimpleCookie, CookieError
from pathlib import Path

import membership

COOKIE = "futbol_session"
PAGES = Path(__file__).resolve().parent


def configure():
    mode = os.environ.get("MEMBERSHIP_MODE", "off")
    if mode == "off":
        return None
    if mode not in ("on", "local"):
        raise RuntimeError("MEMBERSHIP_MODE must be off, on or local")
    if mode == "local" and os.environ.get("RENDER"):
        raise RuntimeError("Local membership mode is restricted to localhost")
    database_url = os.environ.get("MEMBERSHIP_DATABASE_URL")
    if database_url:
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise RuntimeError("MEMBERSHIP_DATABASE_URL must be a PostgreSQL URI")
        db_path = database_url
    else:
        db_path = Path(os.environ["MEMBERSHIP_DB_PATH"])
        if mode == "on" and (not db_path.is_absolute() or not db_path.parent.is_mount()):
            raise RuntimeError("Place MEMBERSHIP_DB_PATH directly under a persistent disk mount")
    with closing(membership.connect(db_path)) as db, db:
        membership.initialize(db)
        if not db.execute("SELECT 1 FROM members WHERE is_admin=1 AND blocked=0").fetchone():
            if membership.create_member(db, os.environ["MEMBERSHIP_ADMIN_PHONE"],
                                        os.environ["MEMBERSHIP_ADMIN_PASSWORD"], admin=True) is None:
                raise RuntimeError("Administrator phone already belongs to an account")
    return db_path


class AccessHandler:
    membership_path = None

    def token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        return cookie[COOKIE].value if COOKIE in cookie else None

    def session_cookie(self, token="", max_age=0):
        secure = "; Secure" if os.environ.get("MEMBERSHIP_MODE") != "local" else ""
        return f"{COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict{secure}"

    def membership_gate(self, path, method):
        if not self.membership_path:
            return False
        if method == "GET" and path == "/healthz":
            self.send({"ok": True})
            return True
        if method == "POST" and self.headers.get("X-Futbol-Request") != "1":
            self.send({"error": "Geçersiz istek"}, 403)
            return True
        if method == "POST" and path in ("/auth/login", "/auth/register", "/auth/logout", "/auth/access"):
            self.membership_action(path)
            return True
        with closing(membership.connect(self.membership_path)) as db:
            try:
                member = membership.authenticate(db, self.token(), count_analysis=path.startswith("/api/analyze/"))
            except PermissionError:
                if method == "GET" and path in ("/", "/admin"):
                    self.access_page("lock.html")
                else:
                    self.send({"error": "Giriş yapmanız gerekiyor"}, 401)
                return True
            if method == "GET" and path == "/admin":
                if member["is_admin"]:
                    self.access_page("admin.html")
                else:
                    self.send({"error": "Yönetici yetkisi gerekiyor"}, 403)
                return True
            if method == "GET" and path == "/auth/members":
                if member["is_admin"]:
                    self.send({"members": membership.members(db)})
                else:
                    self.send({"error": "Yönetici yetkisi gerekiyor"}, 403)
                return True
            self.current_member = member
        return False

    def membership_action(self, path):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 <= size <= 4096:
                self.send({"error": "Geçersiz istek boyutu"}, 413)
                return
            data = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("Geçersiz istek")
            with closing(membership.connect(self.membership_path)) as db, db:
                if path == "/auth/logout":
                    membership.logout(db, self.token())
                    self.send({"ok": True}, cookie=self.session_cookie())
                    return
                if path == "/auth/access":
                    self.change_access(db, data)
                    return
                membership.limit_attempts(db)
                if path == "/auth/register":
                    membership.create_member(db, data.get("phone"), data.get("password"), pending=True)
                    self.send({"message": "Yeni hesaplar yönetici onayından sonra açılır."}, 202)
                    return
                token = membership.login(db, data.get("phone"), data.get("password"))
                self.send({"ok": True}, cookie=self.session_cookie(token, membership.SESSION_SECONDS))
        except PermissionError as exc:
            self.send({"error": str(exc)}, 403)
        except OverflowError as exc:
            self.send({"error": str(exc)}, 429)
        except (ValueError, TypeError) as exc:
            self.send({"error": str(exc)}, 400)

    def change_access(self, db, data):
        actor = membership.authenticate(db, self.token())
        if not actor["is_admin"]:
            raise PermissionError("Yönetici yetkisi gerekiyor")
        member_id = data.get("id")
        action = data.get("action")
        if type(member_id) is not int or not 0 < member_id < 2**63 or action not in ("approve", "open", "block"):
            raise ValueError("Geçersiz işlem")
        target = db.execute("SELECT is_admin,expires_at FROM members WHERE id=?", (member_id,)).fetchone()
        if not target or target["is_admin"]:
            raise ValueError("Bu hesabın durumu değiştirilemez")
        if action == "approve":
            membership.approve(db, member_id)
        elif action == "open":
            if target["expires_at"] is not None and target["expires_at"] <= int(time.time()):
                membership.set_access(db, member_id, blocked=False, days=30)
            else:
                membership.set_access(db, member_id, blocked=False)
        else:
            membership.set_access(db, member_id, blocked=True)
        self.send({"ok": True})

    def access_page(self, filename):
        body = (PAGES / filename).read_bytes()
        if filename == "index.html" and self.membership_path:
            body = body.replace(b'id="accountNav" hidden', b'id="accountNav"')
            if self.current_member["is_admin"]:
                body = body.replace(b'href="/admin" hidden', b'href="/admin"')
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.write_body(body)
