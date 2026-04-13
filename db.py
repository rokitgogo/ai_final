"""NCS 포트폴리오 - SQLite DB (앱 시작 시 init_db 1회 호출, check_same_thread 지원)"""
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

# Streamlit Cloud 등 읽기 전용 환경: 임시 폴더 사용 (재시작 시 데이터 초기화)
_DEFAULT_PATH = Path(__file__).resolve().parent / "data.sqlite3"
try:
    _writable = os.access(_DEFAULT_PATH.parent, os.W_OK)
except OSError:
    _writable = False
if _writable:
    DB_PATH = _DEFAULT_PATH
else:
    DB_PATH = Path(tempfile.gettempdir()) / "ncs_portfolio_data.sqlite3"
_db_initialized = False


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db() -> None:
    """앱 시작 시 한 번만 호출. 테이블 생성."""
    global _db_initialized
    if _db_initialized:
        return
    with _connect() as con:
        con.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;

            CREATE TABLE IF NOT EXISTS users (
              uid TEXT PRIMARY KEY,
              pw TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'student'
            );

            CREATE TABLE IF NOT EXISTS logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              uid TEXT NOT NULL,
              date TEXT NOT NULL,
              ncs_unit TEXT NOT NULL,
              bsr TEXT NOT NULL,
              image_note TEXT,
              audio_note TEXT,
              ncs_term_ratio REAL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              FOREIGN KEY(uid) REFERENCES users(uid)
            );

            CREATE TABLE IF NOT EXISTS progress (
              uid TEXT NOT NULL,
              ncs_unit TEXT NOT NULL,
              value INTEGER NOT NULL,
              PRIMARY KEY(uid, ncs_unit),
              FOREIGN KEY(uid) REFERENCES users(uid)
            );

            CREATE TABLE IF NOT EXISTS researcher_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              log_date TEXT NOT NULL,
              note TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS portfolio_comments (
              uid TEXT PRIMARY KEY,
              comment_text TEXT NOT NULL,
              reflection_level TEXT,
              updated_at TEXT NOT NULL DEFAULT (datetime('now')),
              is_confirmed INTEGER NOT NULL DEFAULT 0,
              FOREIGN KEY(uid) REFERENCES users(uid)
            );
            """
        )
        try:
            con.execute("SELECT ncs_term_ratio FROM logs LIMIT 1")
        except sqlite3.OperationalError:
            con.execute("ALTER TABLE logs ADD COLUMN ncs_term_ratio REAL")
        try:
            con.execute("SELECT is_confirmed FROM portfolio_comments LIMIT 1")
        except sqlite3.OperationalError:
            con.execute("ALTER TABLE portfolio_comments ADD COLUMN is_confirmed INTEGER NOT NULL DEFAULT 0")
            con.execute("UPDATE portfolio_comments SET is_confirmed=1")
    _db_initialized = True


def ensure_default_users() -> None:
    init_db()
    with _connect() as con:
        con.execute(
            "INSERT OR IGNORE INTO users(uid, pw, role) VALUES(?,?,?)",
            ("admin", "admin123", "teacher"),
        )
        for i in range(1, 12):
            con.execute(
                "INSERT OR IGNORE INTO users(uid, pw, role) VALUES(?,?,?)",
                (f"S{i:02d}", "1234", "student"),
            )


def get_user(uid: str) -> dict[str, Any] | None:
    with _connect() as con:
        row = con.execute("SELECT uid, pw, role FROM users WHERE uid=?", (uid,)).fetchone()
        return dict(row) if row else None


def list_users() -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute("SELECT uid, role FROM users ORDER BY uid").fetchall()
        return [dict(r) for r in rows]


def seed_progress_if_missing(uid: str, defaults: dict[str, int]) -> dict[str, int]:
    with _connect() as con:
        for unit, value in defaults.items():
            con.execute(
                "INSERT OR IGNORE INTO progress(uid, ncs_unit, value) VALUES(?,?,?)",
                (uid, unit, int(value)),
            )
        rows = con.execute(
            "SELECT ncs_unit, value FROM progress WHERE uid=?",
            (uid,),
        ).fetchall()
        return {r["ncs_unit"]: int(r["value"]) for r in rows}


def update_progress(uid: str, ncs_unit: str, value: int) -> None:
    with _connect() as con:
        con.execute(
            """
            INSERT INTO progress(uid, ncs_unit, value) VALUES(?,?,?)
            ON CONFLICT(uid, ncs_unit) DO UPDATE SET value=excluded.value
            """,
            (uid, ncs_unit, int(value)),
        )


def add_log(
    *,
    uid: str,
    date: str,
    ncs_unit: str,
    bsr: str,
    image_note: str | None = None,
    audio_note: str | None = None,
    ncs_term_ratio: float | None = None,
) -> int:
    with _connect() as con:
        cur = con.execute(
            """
            INSERT INTO logs(uid, date, ncs_unit, bsr, image_note, audio_note, ncs_term_ratio)
            VALUES(?,?,?,?,?,?,?)
            """,
            (uid, date, ncs_unit, bsr, image_note, audio_note, ncs_term_ratio),
        )
        return int(cur.lastrowid)


def list_logs(uid: str) -> list[dict[str, Any]]:
    with _connect() as con:
        rows = con.execute(
            "SELECT id, date, ncs_unit, bsr, image_note, audio_note, ncs_term_ratio FROM logs WHERE uid=? ORDER BY id DESC",
            (uid,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_log(uid: str, log_id: int) -> None:
    with _connect() as con:
        con.execute("DELETE FROM logs WHERE uid=? AND id=?", (uid, int(log_id)))


def clear_logs(uid: str) -> None:
    with _connect() as con:
        con.execute("DELETE FROM logs WHERE uid=?", (uid,))


def add_researcher_log(*, log_date: str, note: str) -> int:
    """연구자 성찰 로그 저장 (질적 연구 데이터용)."""
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO researcher_logs(log_date, note) VALUES(?,?)",
            (log_date, note),
        )
        return int(cur.lastrowid)


def list_researcher_logs() -> list[dict[str, Any]]:
    """연구자 성찰 로그 목록 (최신순)."""
    with _connect() as con:
        rows = con.execute(
            "SELECT id, log_date, note, created_at FROM researcher_logs ORDER BY log_date DESC, id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def save_portfolio_comment(
    uid: str, comment_text: str, reflection_level: str = "", *, confirmed: bool = True
) -> None:
    """학생 포트폴리오용 [지도교사 종합의견] 저장. confirmed=True일 때만 학생 화면에 확정 반영."""
    is_confirmed = 1 if confirmed else 0
    with _connect() as con:
        con.execute(
            """
            INSERT INTO portfolio_comments(uid, comment_text, reflection_level, updated_at, is_confirmed)
            VALUES(?,?,?,datetime('now'),?)
            ON CONFLICT(uid) DO UPDATE SET
              comment_text=excluded.comment_text,
              reflection_level=excluded.reflection_level,
              updated_at=datetime('now'),
              is_confirmed=excluded.is_confirmed
            """,
            (uid, comment_text, reflection_level, is_confirmed),
        )


def get_portfolio_comment(uid: str) -> dict[str, Any] | None:
    """학생 포트폴리오용 종합 의견 조회 (draft·확정 모두)."""
    with _connect() as con:
        row = con.execute(
            "SELECT uid, comment_text, reflection_level, updated_at, is_confirmed FROM portfolio_comments WHERE uid=?",
            (uid,),
        ).fetchone()
        return dict(row) if row else None


def get_confirmed_portfolio_comment(uid: str) -> dict[str, Any] | None:
    """학생에게 노출: 교사가 [최종 승인]으로 확정한 의견만."""
    row = get_portfolio_comment(uid)
    if not row:
        return None
    if int(row.get("is_confirmed") or 0):
        return row
    return None
