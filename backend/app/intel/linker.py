"""
Link actors that share strong identifiers, and score attribution
confidence.

This is the graph-building core of SIH26151 capability 2: two handles
that sign with the same PGP key, cash out to the same wallet, or share
an email are very likely the same operator or closely tied. Each link
records why it was made, and nothing is ever asserted as certain — the
confidence is capped below 1.0 because these are investigative leads.
"""

from ..database import connect, utc_now
from .store import STRONG_IDENTIFIERS, set_attribution_confidence


# How much each shared identifier type contributes to a link's
# confidence. A shared PGP key is the strongest single signal.
LINK_WEIGHTS = {
    "pgp_fingerprint": 0.6,
    "btc_wallet": 0.45,
    "monero_wallet": 0.45,
    "email": 0.4,
}


def relink_actor(actor_id: int) -> None:
    """Rebuild this actor's links to others, then rescore both ends."""

    affected = {actor_id}

    with connect() as conn:

        strong = conn.execute(
            """
            SELECT identifier_type, identifier_norm, identifier_value
            FROM actor_identifiers
            WHERE actor_id = ? AND identifier_type IN ({})
            """.format(
                ",".join("?" * len(STRONG_IDENTIFIERS))
            ),
            (actor_id, *sorted(STRONG_IDENTIFIERS)),
        ).fetchall()

        for ident in strong:

            others = conn.execute(
                """
                SELECT DISTINCT actor_id
                FROM actor_identifiers
                WHERE identifier_type = ?
                  AND identifier_norm = ?
                  AND actor_id != ?
                """,
                (
                    ident["identifier_type"],
                    ident["identifier_norm"],
                    actor_id,
                ),
            ).fetchall()

            for other in others:

                affected.add(other["actor_id"])

                a, b = sorted((actor_id, other["actor_id"]))

                link_type = f"shared_{ident['identifier_type']}"
                confidence = LINK_WEIGHTS.get(ident["identifier_type"], 0.3)
                evidence = (
                    f"shared {ident['identifier_type']} "
                    f"{ident['identifier_value']}"
                )

                conn.execute(
                    """
                    INSERT INTO actor_links (
                        actor_a, actor_b, link_type,
                        confidence, evidence, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(actor_a, actor_b, link_type) DO UPDATE SET
                        confidence = MAX(confidence, excluded.confidence),
                        evidence = excluded.evidence
                    """,
                    (a, b, link_type, confidence, evidence, utc_now()),
                )

    # Rescore this actor and everyone a link was formed with, so both
    # ends of a newly discovered link reflect it.
    for affected_id in affected:
        _rescore(affected_id)


def _rescore(actor_id: int) -> None:
    """
    Attribution confidence from corroborating evidence:

      + distinct sources the actor was seen on (more sightings = firmer)
      + holding any strong identifier (PGP/wallet/email)
      + strongest cross-actor link (shared key/wallet across markets)

    Capped at 0.95: a lead for human review, never a certainty.
    """

    with connect() as conn:

        sources = conn.execute(
            """
            SELECT COUNT(DISTINCT source_url)
            FROM observations o
            JOIN actors a ON a.handle = o.actor_handle COLLATE NOCASE
            WHERE a.id = ?
            """,
            (actor_id,),
        ).fetchone()[0]

        has_strong = conn.execute(
            """
            SELECT COUNT(*)
            FROM actor_identifiers
            WHERE actor_id = ? AND identifier_type IN ({})
            """.format(
                ",".join("?" * len(STRONG_IDENTIFIERS))
            ),
            (actor_id, *sorted(STRONG_IDENTIFIERS)),
        ).fetchone()[0] > 0

        best_link = conn.execute(
            """
            SELECT COALESCE(MAX(confidence), 0)
            FROM actor_links
            WHERE actor_a = ? OR actor_b = ?
            """,
            (actor_id, actor_id),
        ).fetchone()[0]

    score = 0.0
    score += min(sources, 5) * 0.08    # up to 0.40 from breadth of sources
    score += 0.30 if has_strong else 0.0
    score += best_link * 0.30          # up to ~0.18 from a shared key

    set_attribution_confidence(actor_id, min(score, 0.95))
