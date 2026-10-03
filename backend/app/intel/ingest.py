"""
Turn crawled pages into durable actor intelligence.

Called whenever an onion page that mentions a watched alias is
indexed. Every identifier on the page becomes an observation; the
alias becomes (or updates) an actor; and the identifiers are attached
to that actor. Linking across actors runs afterwards.
"""

import logging

from ..services.matching import context_windows, find_mentions
from .linker import relink_actor
from .store import (
    STRONG_IDENTIFIERS,
    record_observation,
    upsert_actor,
    upsert_actor_identifier,
)


log = logging.getLogger("tracepoint.intel")

# EntityType values worth storing as actor identifiers.
IDENTIFIER_TYPES = {
    "pgp_fingerprint",
    "btc_wallet",
    "monero_wallet",
    "email",
    "telegram",
    "domain",
    "ipv4",
    "ipv6",
}


def ingest_page(alias: str, evidence) -> int:
    """
    Record observations and actor identifiers from one page.

    `evidence` is the onion Evidence object (url, title, host,
    entities, collected_at). Only identifiers found near a mention
    of the alias are tied to the actor, so a directory page that
    merely lists the alias does not attribute every key on it.

    Returns the number of new observations recorded.
    """

    alias = alias.strip()

    observed_at = (
        evidence.collected_at.isoformat()
        if hasattr(evidence.collected_at, "isoformat")
        else str(evidence.collected_at)
    )

    host = evidence.metadata.get("host") if evidence.metadata else None
    content = evidence.content or ""

    # Identifiers within ~300 chars of a mention are "near" the alias.
    spans = find_mentions(content, alias)
    windows = context_windows(content, spans, radius=300)
    near_text = "\n".join(windows)

    actor_id = upsert_actor(alias, observed_at)

    new_count = 0

    for entity in evidence.entities:

        etype = (
            entity.type.value
            if hasattr(entity.type, "value")
            else str(entity.type)
        )

        if etype not in IDENTIFIER_TYPES:
            continue

        is_new = record_observation(
            identifier_type=etype,
            identifier_value=entity.value,
            identifier_norm=entity.normalized,
            source_url=evidence.url,
            observed_at=observed_at,
            actor_handle=alias,
            host=host,
            title=evidence.title,
            snippet=_snippet(near_text or content, entity.value),
        )

        new_count += int(is_new)

        # Attribute an identifier to the actor when:
        #  - it is a strong identifier (PGP key, wallet, email) on a
        #    page that already names the actor — a pasted key's real
        #    fingerprint and UID email are never literal text near the
        #    handle, yet they are unambiguously the actor's; or
        #  - it is a weaker identifier (domain, IP) found right next to
        #    a mention, which keeps directory noise out.
        near = (
            entity.value in near_text
            or entity.normalized in near_text.lower()
        )

        if etype in STRONG_IDENTIFIERS or near:
            upsert_actor_identifier(
                actor_id=actor_id,
                identifier_type=etype,
                identifier_norm=entity.normalized,
                identifier_value=entity.value,
                seen_at=observed_at,
                reason=(
                    f"pasted key / strong identifier on page naming "
                    f"“{alias}” ({host or evidence.url})"
                    if etype in STRONG_IDENTIFIERS
                    else f"co-located with “{alias}” on {host or evidence.url}"
                ),
            )

    # Re-evaluate links and confidence for this actor.
    relink_actor(actor_id)

    if new_count:
        log.info(
            "Ingested %d new observations for %r from %s",
            new_count,
            alias,
            evidence.url,
        )

    return new_count


def _snippet(text: str, value: str, width: int = 160) -> str | None:
    if not text:
        return None

    index = text.find(value)

    if index < 0:
        return text[:width]

    start = max(0, index - width // 2)

    return text[start:start + width].strip()
