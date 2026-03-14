"""User storage in SQLite."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "vibe_reports.db"

def init_users_table():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            hashed_password TEXT NOT NULL,
            avatar_seed INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.commit()
    con.close()

def create_user(email: str, name: str, hashed_password: str, avatar_seed: int = 1) -> dict | None:
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.execute(
            "INSERT INTO users (email, name, hashed_password, avatar_seed) VALUES (?,?,?,?)",
            (email.lower().strip(), name.strip(), hashed_password, avatar_seed)
        )
        user_id = cur.lastrowid
        con.commit()
        con.close()
        return {"id": user_id, "email": email.lower().strip(), "name": name.strip(), "avatar_seed": avatar_seed}
    except sqlite3.IntegrityError:
        return None

def get_user_by_email(email: str) -> dict | None:
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT id, email, name, hashed_password, avatar_seed FROM users WHERE email=?",
        (email.lower().strip(),)
    ).fetchone()
    con.close()
    if row:
        return {"id": row[0], "email": row[1], "name": row[2], "hashed_password": row[3], "avatar_seed": row[4]}
    return None

def get_user_by_id(user_id: int) -> dict | None:
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT id, email, name, avatar_seed FROM users WHERE id=?", (user_id,)
    ).fetchone()
    con.close()
    if row:
        return {"id": row[0], "email": row[1], "name": row[2], "avatar_seed": row[3]}
    return None
