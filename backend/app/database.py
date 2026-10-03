import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "tracepoint.db"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                url TEXT NOT NULL UNIQUE,
                host TEXT NOT NULL,

                status TEXT NOT NULL DEFAULT 'pending',

                depth INTEGER NOT NULL DEFAULT 0,

                source_url TEXT,
                discovered_from INTEGER,

                discovered_at TEXT NOT NULL,
                crawled_at TEXT,

                attempts INTEGER NOT NULL DEFAULT 0,

                error TEXT
            )
        """)

        # Added after the first release; migrate older databases.
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(urls)")
        }

        if "priority" not in columns:
            conn.execute(
                "ALTER TABLE urls ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
            )

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_urls_status
            ON urls(status)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_urls_host
            ON urls(host)
        """)

        # Content of successfully crawled onion pages. This is what
        # the "onion" collector searches during an investigation.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                url_id INTEGER PRIMARY KEY REFERENCES urls(id),

                url TEXT NOT NULL,
                host TEXT NOT NULL,

                title TEXT,
                content TEXT,

                entities TEXT NOT NULL DEFAULT '[]',
                metadata TEXT NOT NULL DEFAULT '{}',

                crawled_at TEXT NOT NULL
            )
        """)

        # Aliases that investigators have searched for. The crawler
        # follows links from any page that mentions one of them.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                alias TEXT PRIMARY KEY COLLATE NOCASE,
                added_at TEXT NOT NULL
            )
        """)

        # URLs left in 'crawling' by an interrupted run would otherwise
        # never be picked up again.
        conn.execute("""
            UPDATE urls
            SET status = 'pending'
            WHERE status = 'crawling'
        """)


def add_url(
    url: str,
    host: str,
    depth: int = 0,
    source_url: str | None = None,
    discovered_from: int | None = None,
    priority: int = 0,
) -> bool:
    """
    Queue a URL. Returns True if it was not already known.

    If the URL is already queued but still pending, its priority
    is raised and its depth lowered when the new values are better.
    """

    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO urls (
                url,
                host,
                status,
                depth,
                source_url,
                discovered_from,
                discovered_at,
                priority
            )
            VALUES (?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                url,
                host,
                depth,
                source_url,
                discovered_from,
                utc_now(),
                priority,
            ),
        )

        if cursor.rowcount > 0:
            return True

        conn.execute(
            """
            UPDATE urls
            SET
                priority = MAX(priority, ?),
                depth = MIN(depth, ?)
            WHERE url = ? AND status = 'pending'
            """,
            (priority, depth, url),
        )

        return False


def claim_pending_urls(limit=5, min_priority=0) -> list[dict]:
    """
    Atomically move up to `limit` pending URLs to 'crawling' and
    return them, highest priority first. Safe to call from both the
    background worker and a live hunt at the same time.
    """

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM urls
            WHERE status = 'pending' AND priority >= ?
            ORDER BY priority DESC, depth ASC, id ASC
            LIMIT ?
            """,
            (min_priority, limit),
        ).fetchall()

        claimed = []

        for row in rows:
            cursor = conn.execute(
                """
                UPDATE urls
                SET
                    status = 'crawling',
                    attempts = attempts + 1
                WHERE id = ? AND status = 'pending'
                """,
                (row["id"],),
            )

            if cursor.rowcount:
                claimed.append(dict(row))

    return claimed


def add_watch_alias(alias: str) -> bool:
    """Returns True if the alias was not already watched."""

    with connect() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO watchlist (alias, added_at) VALUES (?, ?)",
            (alias, utc_now()),
        )

        return cursor.rowcount > 0


def get_watch_aliases() -> list[str]:
    with connect() as conn:
        rows = conn.execute("SELECT alias FROM watchlist").fetchall()

    return [row["alias"] for row in rows]


def requeue_url(url_id: int, priority: int) -> None:
    """Crawl an already-known URL again, ahead of normal discovery."""

    with connect() as conn:
        conn.execute(
            """
            UPDATE urls
            SET
                status = 'pending',
                depth = 0,
                priority = MAX(priority, ?)
            WHERE id = ? AND status != 'crawling'
            """,
            (priority, url_id),
        )


def mark_done(url_id):
    with connect() as conn:
        conn.execute(
            """
            UPDATE urls
            SET
                status = 'done',
                crawled_at = ?,
                error = NULL
            WHERE id = ?
            """,
            (utc_now(), url_id),
        )


def mark_failed(url_id, error):
    with connect() as conn:
        conn.execute(
            """
            UPDATE urls
            SET
                status = 'failed',
                crawled_at = ?,
                error = ?
            WHERE id = ?
            """,
            (utc_now(), str(error)[:1000], url_id),
        )


def save_page(url_id: int, evidence) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO pages (
                url_id,
                url,
                host,
                title,
                content,
                entities,
                metadata,
                crawled_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                url_id,
                evidence.url,
                evidence.metadata.get("host", ""),
                evidence.title,
                evidence.content,
                json.dumps(
                    [entity.model_dump(mode="json") for entity in evidence.entities]
                ),
                json.dumps(evidence.metadata, default=str),
                utc_now(),
            ),
        )


def search_pages(query: str, limit: int = 500) -> list[dict]:
    """
    Case-insensitive substring prefilter over crawled onion pages.
    Callers apply exact alias matching on the result.
    """

    pattern = "%" + (
        query.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    ) + "%"

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM pages
            WHERE url LIKE ? ESCAPE '\\'
               OR title LIKE ? ESCAPE '\\'
               OR content LIKE ? ESCAPE '\\'
            ORDER BY crawled_at DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, limit),
        ).fetchall()

    pages = []

    for row in rows:
        page = dict(row)
        page["entities"] = json.loads(page["entities"])
        page["metadata"] = json.loads(page["metadata"])
        pages.append(page)

    return pages


def get_url_stats():
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM urls
            GROUP BY status
            """
        ).fetchall()

        indexed = conn.execute(
            "SELECT COUNT(*) FROM pages"
        ).fetchone()[0]

    stats = {
        row["status"]: row["count"]
        for row in rows
    }

    stats["indexed_pages"] = indexed
    stats["watchlist"] = get_watch_aliases()

    return stats
