"""SQLite-backed storage and queries for actor intelligence."""

from ..database import connect, utc_now


# Identifier types that, when shared between two actors, are strong
# evidence that they are the same or related persona.
STRONG_IDENTIFIERS = {
    "pgp_fingerprint",
    "btc_wallet",
    "monero_wallet",
    "email",
}


def init_intel_db() -> None:
    """Create the intelligence tables. Safe to call repeatedly."""

    with connect() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                identifier_type TEXT NOT NULL,
                identifier_value TEXT NOT NULL,
                identifier_norm TEXT NOT NULL,

                actor_handle TEXT,

                source_url TEXT NOT NULL,
                host TEXT,
                title TEXT,
                snippet TEXT,

                observed_at TEXT NOT NULL,

                UNIQUE (identifier_type, identifier_norm, source_url)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_obs_time
            ON observations(observed_at)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_obs_identifier
            ON observations(identifier_type, identifier_norm)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_obs_handle
            ON observations(actor_handle)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS actors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                handle TEXT NOT NULL UNIQUE COLLATE NOCASE,

                category TEXT,
                attribution_confidence REAL NOT NULL DEFAULT 0,

                first_seen TEXT,
                last_seen TEXT,

                notes TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS actor_identifiers (
                actor_id INTEGER NOT NULL REFERENCES actors(id),

                identifier_type TEXT NOT NULL,
                identifier_norm TEXT NOT NULL,
                identifier_value TEXT NOT NULL,

                reason TEXT,
                first_seen TEXT,

                PRIMARY KEY (actor_id, identifier_type, identifier_norm)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_actor_ident
            ON actor_identifiers(identifier_type, identifier_norm)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS actor_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                actor_a INTEGER NOT NULL REFERENCES actors(id),
                actor_b INTEGER NOT NULL REFERENCES actors(id),

                link_type TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                evidence TEXT,

                created_at TEXT NOT NULL,

                UNIQUE (actor_a, actor_b, link_type)
            )
        """)


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def record_observation(
    identifier_type: str,
    identifier_value: str,
    identifier_norm: str,
    source_url: str,
    observed_at: str,
    actor_handle: str | None = None,
    host: str | None = None,
    title: str | None = None,
    snippet: str | None = None,
) -> bool:
    """
    Record one sighting of an identifier on a source.

    Returns True if this was a new (identifier, source) pair.
    """

    with connect() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO observations (
                identifier_type,
                identifier_value,
                identifier_norm,
                actor_handle,
                source_url,
                host,
                title,
                snippet,
                observed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier_type,
                identifier_value,
                identifier_norm,
                actor_handle,
                source_url,
                host,
                title,
                snippet,
                observed_at,
            ),
        )

        return cursor.rowcount > 0


def upsert_actor(
    handle: str,
    seen_at: str,
    category: str | None = None,
) -> int:
    """Create or update an actor by handle; returns its id."""

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO actors (handle, category, first_seen, last_seen)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(handle) DO UPDATE SET
                last_seen = MAX(last_seen, excluded.last_seen),
                first_seen = MIN(first_seen, excluded.first_seen),
                category = COALESCE(category, excluded.category)
            """,
            (handle, category, seen_at, seen_at),
        )

        row = conn.execute(
            "SELECT id FROM actors WHERE handle = ?",
            (handle,),
        ).fetchone()

        return row["id"]


def upsert_actor_identifier(
    actor_id: int,
    identifier_type: str,
    identifier_norm: str,
    identifier_value: str,
    seen_at: str,
    reason: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO actor_identifiers (
                actor_id,
                identifier_type,
                identifier_norm,
                identifier_value,
                reason,
                first_seen
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                actor_id,
                identifier_type,
                identifier_norm,
                identifier_value,
                reason,
                seen_at,
            ),
        )


def set_attribution_confidence(actor_id: int, confidence: float) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE actors SET attribution_confidence = ? WHERE id = ?",
            (round(confidence, 3), actor_id),
        )


# ---------------------------------------------------------------------------
# Reads / queries
# ---------------------------------------------------------------------------

def query_observations(
    since: str | None = None,
    until: str | None = None,
    identifier_type: str | None = None,
    actor_handle: str | None = None,
    host: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    """Timeline query over sightings. All filters are optional."""

    clauses = []
    params: list = []

    if since:
        clauses.append("observed_at >= ?")
        params.append(since)

    if until:
        clauses.append("observed_at <= ?")
        params.append(until)

    if identifier_type:
        clauses.append("identifier_type = ?")
        params.append(identifier_type)

    if actor_handle:
        clauses.append("actor_handle = ? COLLATE NOCASE")
        params.append(actor_handle)

    if host:
        clauses.append("host = ?")
        params.append(host)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    params.append(limit)

    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM observations
            {where}
            ORDER BY observed_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    return [dict(row) for row in rows]


def list_actors(
    category: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 500,
) -> list[dict]:
    clauses = ["attribution_confidence >= ?"]
    params: list = [min_confidence]

    if category:
        clauses.append("category = ?")
        params.append(category)

    where = f"WHERE {' AND '.join(clauses)}"
    params.append(limit)

    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                a.*,
                (SELECT COUNT(*) FROM actor_identifiers i
                 WHERE i.actor_id = a.id) AS identifier_count
            FROM actors a
            {where}
            ORDER BY a.attribution_confidence DESC, a.last_seen DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    return [dict(row) for row in rows]


def get_actor(handle: str) -> dict | None:
    """Full profile: actor row, its identifiers, links and sources."""

    with connect() as conn:
        actor = conn.execute(
            "SELECT * FROM actors WHERE handle = ? COLLATE NOCASE",
            (handle,),
        ).fetchone()

        if not actor:
            return None

        actor = dict(actor)

        actor["identifiers"] = [
            dict(row)
            for row in conn.execute(
                """
                SELECT identifier_type, identifier_value, reason, first_seen
                FROM actor_identifiers
                WHERE actor_id = ?
                ORDER BY identifier_type
                """,
                (actor["id"],),
            )
        ]

        actor["sources"] = [
            dict(row)
            for row in conn.execute(
                """
                SELECT DISTINCT source_url, host, title, observed_at
                FROM observations
                WHERE actor_handle = ? COLLATE NOCASE
                ORDER BY observed_at DESC
                LIMIT 200
                """,
                (handle,),
            )
        ]

        links = conn.execute(
            """
            SELECT
                l.link_type,
                l.confidence,
                l.evidence,
                CASE WHEN l.actor_a = ? THEN b.handle ELSE a.handle END
                    AS other_handle
            FROM actor_links l
            JOIN actors a ON a.id = l.actor_a
            JOIN actors b ON b.id = l.actor_b
            WHERE l.actor_a = ? OR l.actor_b = ?
            ORDER BY l.confidence DESC
            """,
            (actor["id"], actor["id"], actor["id"]),
        ).fetchall()

        actor["links"] = [dict(row) for row in links]

    return actor


def stats() -> dict:
    with connect() as conn:
        actors = conn.execute("SELECT COUNT(*) FROM actors").fetchone()[0]
        observations = conn.execute(
            "SELECT COUNT(*) FROM observations"
        ).fetchone()[0]
        identifiers = conn.execute(
            "SELECT COUNT(DISTINCT identifier_norm) FROM observations"
        ).fetchone()[0]
        links = conn.execute("SELECT COUNT(*) FROM actor_links").fetchone()[0]

        by_type = {
            row["identifier_type"]: row["n"]
            for row in conn.execute(
                """
                SELECT identifier_type, COUNT(DISTINCT identifier_norm) AS n
                FROM observations
                GROUP BY identifier_type
                """
            )
        }

    return {
        "actors": actors,
        "observations": observations,
        "unique_identifiers": identifiers,
        "links": links,
        "identifiers_by_type": by_type,
    }
