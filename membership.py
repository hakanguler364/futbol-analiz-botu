"""Phone/password membership primitives (standard library, server-side only).

Not activated until the application routes are wired and persistent storage is configured.
Render free instances have ephemeral local storage: do NOT use a local SQLite file for
production memberships without a persistent disk or external database.
"""
import datetime
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time

ITERATIONS = 600_000
SESSION_SECONDS = 12 * 3600


def normalize_phone(phone):
    value = re.sub(r"[\s()\-]", "", str(phone))
    if not re.fullmatch(r"\+?[0-9]{10,15}", value):
        raise ValueError("Geçerli telefon numarası girin")
    return value


def password_hash(password, salt=None):
    if not isinstance(password, str) or len(password) < 12:
        raise ValueError("Şifre en az 12 karakter olmalı")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        algo, iterations, salt, expected = stored.split("$")
        if algo != "pbkdf2_sha256" or not (100_000 <= int(iterations) <= 2_000_000):
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, AttributeError, TypeError):
        return False


def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    return db


def initialize(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY,
        phone TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
        blocked INTEGER NOT NULL DEFAULT 0,
        expires_at INTEGER,
        created_at INTEGER NOT NULL,
        last_seen INTEGER,
        login_count INTEGER NOT NULL DEFAULT 0,
        analysis_count INTEGER NOT NULL DEFAULT 0,
        active_seconds INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
        expires_at INTEGER NOT NULL,
        last_seen INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS sessions_member ON sessions(member_id);
    """)
    db.commit()


def create_member(db, phone, password, *, admin=False, days=30):
    phone = normalize_phone(phone)
    if not 1 <= int(days) <= 3650:
        raise ValueError("Gün sayısı 1-3650 arasında olmalı")
    now = int(time.time())
    cursor = db.execute(
        "INSERT INTO members(phone,password_hash,is_admin,expires_at,created_at) VALUES(?,?,?,?,?)",
        (phone, password_hash(password), int(admin), now + int(days)*86400, now))
    db.commit()
    return cursor.lastrowid


def login(db, phone, password):
    phone = normalize_phone(phone)
    member = db.execute("SELECT * FROM members WHERE phone=?", (phone,)).fetchone()
    # Equalize nonexistent-account work; do not reveal which phone numbers exist.
    fallback = password_hash("dummy-password-for-timing-only")
    if not verify_password(password, member["password_hash"] if member else fallback):
        raise ValueError("Telefon veya şifre hatalı")
    now = int(time.time())
    if member["blocked"] or (member["expires_at"] is not None and member["expires_at"] <= now):
        raise PermissionError("Üyelik kapalı veya süresi dolmuş")
    token = secrets.token_urlsafe(32)
    db.execute("INSERT INTO sessions VALUES(?,?,?,?)",
               (hashlib.sha256(token.encode()).hexdigest(), member["id"], now+SESSION_SECONDS, now))
    db.execute("UPDATE members SET login_count=login_count+1,last_seen=? WHERE id=?", (now,member["id"]))
    db.commit()
    return token


def authenticate(db, token, *, count_analysis=False):
    if not token:
        raise PermissionError("Giriş yapmanız gerekiyor")
    key = hashlib.sha256(token.encode()).hexdigest()
    now = int(time.time())
    row = db.execute("""SELECT m.*,s.last_seen AS session_seen,s.expires_at AS session_expiry
        FROM sessions s JOIN members m ON m.id=s.member_id WHERE s.token_hash=?""", (key,)).fetchone()
    if not row or row["blocked"] or row["session_expiry"] <= now or (
        row["expires_at"] is not None and row["expires_at"] <= now
    ):
        raise PermissionError("Oturum geçersiz veya üyelik kapalı")
    elapsed = min(max(0, now-row["session_seen"]), 300)
    db.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?", (now,key))
    db.execute("""UPDATE members SET last_seen=?,active_seconds=active_seconds+?,
        analysis_count=analysis_count+? WHERE id=?""",
        (now,elapsed,int(count_analysis),row["id"]))
    db.commit()
    return dict(row)


def set_access(db, member_id, *, blocked=None, days=None):
    member = db.execute("SELECT id FROM members WHERE id=?", (member_id,)).fetchone()
    if not member:
        raise ValueError("Kullanıcı bulunamadı")
    if blocked is not None:
        db.execute("UPDATE members SET blocked=? WHERE id=?", (int(bool(blocked)),member_id))
        if blocked:
            db.execute("DELETE FROM sessions WHERE member_id=?", (member_id,))
    if days is not None:
        if not 1 <= int(days) <= 3650:
            raise ValueError("Gün sayısı 1-3650 arasında olmalı")
        db.execute("UPDATE members SET expires_at=? WHERE id=?",
                   (int(time.time())+int(days)*86400,member_id))
    db.commit()


def members(db):
    return [dict(row) for row in db.execute("""SELECT id,phone,is_admin,blocked,
        expires_at,created_at,last_seen,login_count,analysis_count,active_seconds
        FROM members ORDER BY id""")]
