"""
播主档案数据库（PostgreSQL / SQLite）
通过 .env 中 DATABASE_URL 配置
"""

import sqlite3
import uuid
from pathlib import Path
from config import config


def _get_pg_conn():
    import psycopg2
    return psycopg2.connect(config.DATABASE_URL)


def _get_sqlite_conn():
    db_path = config.DATABASE_URL.replace("sqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _get_conn():
    url = config.DATABASE_URL
    if url.startswith("postgres"):
        return _get_pg_conn()
    return _get_sqlite_conn()


def _init_table(conn):
    cur = conn.cursor()
    if config.DATABASE_URL.startswith("postgres"):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id VARCHAR(32) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                company VARCHAR(200) DEFAULT '',
                slogan VARCHAR(200) DEFAULT '',
                voice_id VARCHAR(100) DEFAULT '',
                avatar VARCHAR(500) DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                company TEXT DEFAULT '',
                slogan TEXT DEFAULT '',
                voice_id TEXT DEFAULT '',
                avatar TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
    conn.commit()
    try:
        if config.DATABASE_URL.startswith("postgres"):
            cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS avatar VARCHAR(500) DEFAULT ''")
        else:
            cur.execute("ALTER TABLE profiles ADD COLUMN avatar TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass

    # voices 表
    if config.DATABASE_URL.startswith("postgres"):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS voices (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                voice_id VARCHAR(100) NOT NULL UNIQUE
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS voices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                voice_id TEXT NOT NULL UNIQUE
            )
        """)
    conn.commit()


def _row_to_dict(row, cur):
    if config.DATABASE_URL.startswith("postgres"):
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    return dict(row)


def list_profiles():
    conn = _get_conn()
    _init_table(conn)
    cur = conn.cursor()
    cur.execute("SELECT * FROM profiles ORDER BY created_at DESC")
    rows = cur.fetchall()
    result = [_row_to_dict(r, cur) for r in rows]
    conn.close()
    return result


def get_profile(pid):
    conn = _get_conn()
    _init_table(conn)
    cur = conn.cursor()
    cur.execute("SELECT * FROM profiles WHERE id=%s" if config.DATABASE_URL.startswith("postgres") else "SELECT * FROM profiles WHERE id=?", (pid,))
    row = cur.fetchone()
    conn.close()
    return _row_to_dict(row, cur) if row else None


def save_profile(data):
    conn = _get_conn()
    _init_table(conn)
    cur = conn.cursor()
    pid = data.get("id")
    pg = config.DATABASE_URL.startswith("postgres")

    if pid and get_profile(pid):
        cur.execute(
            "UPDATE profiles SET name=%s, company=%s, slogan=%s, voice_id=%s, avatar=%s WHERE id=%s" if pg else
            "UPDATE profiles SET name=?, company=?, slogan=?, voice_id=?, avatar=? WHERE id=?",
            (data["name"], data.get("company",""), data.get("slogan",""), data.get("voice_id",""), data.get("avatar",""), pid)
        )
    else:
        if not pid:
            pid = uuid.uuid4().hex[:12]
        cur.execute(
            "INSERT INTO profiles (id,name,company,slogan,voice_id,avatar) VALUES (%s,%s,%s,%s,%s,%s)" if pg else
            "INSERT INTO profiles (id,name,company,slogan,voice_id,avatar) VALUES (?,?,?,?,?,?)",
            (pid, data["name"], data.get("company",""), data.get("slogan",""), data.get("voice_id",""), data.get("avatar",""))
        )
    conn.commit()
    conn.close()
    return pid


def delete_profile(pid):
    conn = _get_conn()
    _init_table(conn)
    cur = conn.cursor()
    cur.execute("DELETE FROM profiles WHERE id=%s" if config.DATABASE_URL.startswith("postgres") else "DELETE FROM profiles WHERE id=?", (pid,))
    conn.commit()
    conn.close()


def list_voices():
    conn = _get_conn()
    _init_table(conn)
    cur = conn.cursor()
    cur.execute("SELECT * FROM voices ORDER BY id")
    rows = cur.fetchall()
    result = [_row_to_dict(r, cur) for r in rows]
    conn.close()
    return result


def save_voice(data):
    conn = _get_conn()
    _init_table(conn)
    cur = conn.cursor()
    pg = config.DATABASE_URL.startswith("postgres")
    if data.get("id"):
        cur.execute("UPDATE voices SET name=%s, voice_id=%s WHERE id=%s" if pg else "UPDATE voices SET name=?, voice_id=? WHERE id=?",
                   (data["name"], data["voice_id"], data["id"]))
    else:
        cur.execute("INSERT INTO voices (name,voice_id) VALUES (%s,%s)" if pg else "INSERT INTO voices (name,voice_id) VALUES (?,?)",
                   (data["name"], data["voice_id"]))
    conn.commit()
    conn.close()


def delete_voice(vid):
    conn = _get_conn()
    _init_table(conn)
    cur = conn.cursor()
    cur.execute("DELETE FROM voices WHERE id=%s" if config.DATABASE_URL.startswith("postgres") else "DELETE FROM voices WHERE id=?", (vid,))
    conn.commit()
    conn.close()
