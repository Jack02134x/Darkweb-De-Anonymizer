"""
Persistent threat-actor intelligence store.

Turns crawled onion pages into durable records:

- observations: every sighting of an identifier (PGP key, wallet,
  handle, email…) on a source, with a timestamp — the timeline-
  queryable fact table.
- actors: persona clusters, with category, attribution confidence
  and first/last-seen dates.
- actor_identifiers: the identifiers that belong to each actor.
- actor_links: relationships between actors (shared key, wallet…).

Everything the SIH26151 front end queries and exports lives here.
"""

from .store import (
    get_actor,
    init_intel_db,
    list_actors,
    query_observations,
    record_observation,
    stats,
    upsert_actor,
    upsert_actor_identifier,
)

__all__ = [
    "get_actor",
    "init_intel_db",
    "list_actors",
    "query_observations",
    "record_observation",
    "stats",
    "upsert_actor",
    "upsert_actor_identifier",
]
