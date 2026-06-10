"""
播主档案数据库（PostgreSQL / SQLite）
通过 .env 中 DATABASE_URL 配置
"""

import sqlite3
import uuid
import json
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
                voice_type INTEGER DEFAULT 1,
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
                voice_type INTEGER DEFAULT 1,
                avatar TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
    conn.commit()

    # 视频元数据表
    if config.DATABASE_URL.startswith("postgres"):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id VARCHAR(32) PRIMARY KEY,
                filename VARCHAR(500) NOT NULL UNIQUE,
                type VARCHAR(30) NOT NULL,
                title VARCHAR(500) DEFAULT '',
                topic TEXT DEFAULT '',
                content TEXT DEFAULT '',
                profile_id VARCHAR(32) DEFAULT '',
                narrator_name VARCHAR(100) DEFAULT '',
                narrator_avatar VARCHAR(500) DEFAULT '',
                company VARCHAR(200) DEFAULT '',
                slogan VARCHAR(200) DEFAULT '',
                voice_id VARCHAR(100) DEFAULT '',
                voice_type INTEGER DEFAULT 1,
                background VARCHAR(500) DEFAULT '',
                theme VARCHAR(100) DEFAULT '',
                script_json TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                title TEXT DEFAULT '',
                topic TEXT DEFAULT '',
                content TEXT DEFAULT '',
                profile_id TEXT DEFAULT '',
                narrator_name TEXT DEFAULT '',
                narrator_avatar TEXT DEFAULT '',
                company TEXT DEFAULT '',
                slogan TEXT DEFAULT '',
                voice_id TEXT DEFAULT '',
                voice_type INTEGER DEFAULT 1,
                background TEXT DEFAULT '',
                theme TEXT DEFAULT '',
                script_json TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
    conn.commit()
    try:
        if config.DATABASE_URL.startswith("postgres"):
            cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS avatar VARCHAR(500) DEFAULT ''")
            cur.execute("ALTER TABLE profiles ADD COLUMN IF NOT EXISTS voice_type INTEGER DEFAULT 1")
            cur.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS voice_type INTEGER DEFAULT 1")
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
                voice_id VARCHAR(100) NOT NULL UNIQUE,
                type INTEGER DEFAULT 1
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS voices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                voice_id TEXT NOT NULL UNIQUE,
                type INTEGER DEFAULT 1
            )
        """)
    conn.commit()
    for table, column in (("profiles", "voice_type"), ("voices", "type"), ("videos", "voice_type")):
        try:
            if config.DATABASE_URL.startswith("postgres"):
                cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} INTEGER DEFAULT 1")
            else:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER DEFAULT 1")
            conn.commit()
        except Exception:
            conn.rollback()


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
            "UPDATE profiles SET name=%s, company=%s, slogan=%s, voice_id=%s, voice_type=%s, avatar=%s WHERE id=%s" if pg else
            "UPDATE profiles SET name=?, company=?, slogan=?, voice_id=?, voice_type=?, avatar=? WHERE id=?",
            (data["name"], data.get("company",""), data.get("slogan",""), data.get("voice_id",""),
             int(data.get("voice_type", 1)), data.get("avatar",""), pid)
        )
    else:
        if not pid:
            pid = uuid.uuid4().hex[:12]
        cur.execute(
            "INSERT INTO profiles (id,name,company,slogan,voice_id,voice_type,avatar) VALUES (%s,%s,%s,%s,%s,%s,%s)" if pg else
            "INSERT INTO profiles (id,name,company,slogan,voice_id,voice_type,avatar) VALUES (?,?,?,?,?,?,?)",
            (pid, data["name"], data.get("company",""), data.get("slogan",""), data.get("voice_id",""),
             int(data.get("voice_type", 1)), data.get("avatar",""))
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
        cur.execute("UPDATE voices SET name=%s, voice_id=%s, type=%s WHERE id=%s" if pg else "UPDATE voices SET name=?, voice_id=?, type=? WHERE id=?",
                   (data["name"], data["voice_id"], int(data.get("type", 1)), data["id"]))
    else:
        cur.execute("INSERT INTO voices (name,voice_id,type) VALUES (%s,%s,%s)" if pg else "INSERT INTO voices (name,voice_id,type) VALUES (?,?,?)",
                   (data["name"], data["voice_id"], int(data.get("type", 1))))
    cur.execute(
        "UPDATE profiles SET voice_type=%s WHERE voice_id=%s" if pg else
        "UPDATE profiles SET voice_type=? WHERE voice_id=?",
        (int(data.get("type", 1)), data["voice_id"]),
    )
    conn.commit()
    conn.close()


def delete_voice(vid):
    conn = _get_conn()
    _init_table(conn)
    cur = conn.cursor()
    cur.execute("DELETE FROM voices WHERE id=%s" if config.DATABASE_URL.startswith("postgres") else "DELETE FROM voices WHERE id=?", (vid,))
    conn.commit()
    conn.close()


def save_video(data):
    conn = _get_conn()
    _init_table(conn)
    cur = conn.cursor()
    pg = config.DATABASE_URL.startswith("postgres")
    video_id = data.get("id") or uuid.uuid4().hex[:16]
    values = (
        video_id, data["filename"], data.get("type", "science"),
        data.get("title", ""), data.get("topic", ""), data.get("content", ""),
        data.get("profile_id", ""), data.get("narrator_name", ""),
        data.get("narrator_avatar", ""), data.get("company", ""),
        data.get("slogan", ""), data.get("voice_id", ""), int(data.get("voice_type", 1)),
        data.get("background", ""), data.get("theme", ""),
        json.dumps(data.get("script", {}), ensure_ascii=False),
    )
    if pg:
        cur.execute("""
            INSERT INTO videos (
                id, filename, type, title, topic, content, profile_id,
                narrator_name, narrator_avatar, company, slogan, voice_id, voice_type,
                background, theme, script_json
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (filename) DO UPDATE SET
                type=EXCLUDED.type, title=EXCLUDED.title, topic=EXCLUDED.topic,
                content=EXCLUDED.content, profile_id=EXCLUDED.profile_id,
                narrator_name=EXCLUDED.narrator_name,
                narrator_avatar=EXCLUDED.narrator_avatar, company=EXCLUDED.company,
                slogan=EXCLUDED.slogan, voice_id=EXCLUDED.voice_id, voice_type=EXCLUDED.voice_type,
                background=EXCLUDED.background, theme=EXCLUDED.theme,
                script_json=EXCLUDED.script_json
        """, values)
    else:
        cur.execute("""
            INSERT INTO videos (
                id, filename, type, title, topic, content, profile_id,
                narrator_name, narrator_avatar, company, slogan, voice_id, voice_type,
                background, theme, script_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(filename) DO UPDATE SET
                type=excluded.type, title=excluded.title, topic=excluded.topic,
                content=excluded.content, profile_id=excluded.profile_id,
                narrator_name=excluded.narrator_name,
                narrator_avatar=excluded.narrator_avatar, company=excluded.company,
                slogan=excluded.slogan, voice_id=excluded.voice_id, voice_type=excluded.voice_type,
                background=excluded.background, theme=excluded.theme,
                script_json=excluded.script_json
        """, values)
    conn.commit()
    conn.close()
    return video_id


def list_videos():
    conn = _get_conn()
    _init_table(conn)
    cur = conn.cursor()
    cur.execute("SELECT * FROM videos ORDER BY created_at DESC")
    rows = cur.fetchall()
    result = [_row_to_dict(r, cur) for r in rows]
    conn.close()
    for item in result:
        try:
            item["script"] = json.loads(item.pop("script_json", "") or "{}")
        except (TypeError, json.JSONDecodeError):
            item["script"] = {}
    return result
