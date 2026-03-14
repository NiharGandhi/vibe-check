"""SQLite storage for real-time user vibe check-ins."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Default DB path in project root
DB_PATH = Path(__file__).resolve().parent.parent.parent / "vibe_reports.db"
REPORT_TTL_HOURS = 4  # Only count reports from last N hours for "real-time"


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vibe_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                place_id TEXT NOT NULL,
                lively INTEGER NOT NULL,
                fun INTEGER NOT NULL,
                good INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vibe_place ON vibe_reports(place_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vibe_created ON vibe_reports(created_at)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS besttime_venue_cache (
                place_id TEXT PRIMARY KEY,
                venue_id TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def add_report(place_id: str, lively: bool, fun: bool, good: bool) -> None:
    """Store a user vibe report (user is at the venue, reporting real experience)."""
    init_db()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO vibe_reports (place_id, lively, fun, good) VALUES (?, ?, ?, ?)",
            (place_id, 1 if lively else 0, 1 if fun else 0, 1 if good else 0),
        )


def get_recent_reports(place_id: str, hours: int = REPORT_TTL_HOURS) -> dict:
    """
    Get aggregated vibe from recent user reports.
    Returns: {count, lively_pct, fun_pct, good_pct, is_lively, is_fun, is_good}
    """
    init_db()
    since_dt = datetime.utcnow() - timedelta(hours=hours)
    since = since_dt.strftime("%Y-%m-%d %H:%M:%S")  # SQLite-compatible format
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT lively, fun, good FROM vibe_reports
            WHERE place_id = ? AND created_at >= ?
            """,
            (place_id, since),
        ).fetchall()

    if not rows:
        return {"count": 0, "lively_pct": None, "fun_pct": None, "good_pct": None, "is_lively": None, "is_fun": None, "is_good": None}

    n = len(rows)
    lively_pct = sum(r["lively"] for r in rows) / n * 100
    fun_pct = sum(r["fun"] for r in rows) / n * 100
    good_pct = sum(r["good"] for r in rows) / n * 100

    return {
        "count": n,
        "lively_pct": round(lively_pct, 1),
        "fun_pct": round(fun_pct, 1),
        "good_pct": round(good_pct, 1),
        "is_lively": lively_pct >= 50,
        "is_fun": fun_pct >= 50,
        "is_good": good_pct >= 50,
    }


def get_besttime_venue_id(place_id: str) -> str | None:
    """Get cached BestTime venue_id for a place."""
    init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT venue_id FROM besttime_venue_cache WHERE place_id = ?",
            (place_id,),
        ).fetchone()
    return row["venue_id"] if row else None


def set_besttime_venue_id(place_id: str, venue_id: str) -> None:
    """Cache BestTime venue_id for a place."""
    init_db()
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO besttime_venue_cache (place_id, venue_id, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(place_id) DO UPDATE SET venue_id = ?, updated_at = CURRENT_TIMESTAMP
            """,
            (place_id, venue_id, venue_id),
        )
