import asyncio
import uuid
from datetime import datetime, timezone

import httpx

from ..collectors import COLLECTORS
from ..models import (
    CollectorCategory,
    CollectorStatus,
    CollectionRun,
    Evidence,
    Investigation,
    Target,
)
from ..storage import store


def collector_category(source_name: str) -> CollectorCategory:
    if source_name == "onion":
        return CollectorCategory.onion

    return CollectorCategory.surface


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_investigation(
    target: Target,
) -> Investigation:

    investigation = Investigation(
        id=str(uuid.uuid4()),
        target=target,
    )

    return store.create(investigation)


async def collect(
    investigation: Investigation,
    sources: list[str],
    max_results: int,
) -> Investigation:

    investigation.status = "collecting"
    investigation.updated_at = utc_now()

    # ---------------------------------------------------------
    # Run all requested collectors concurrently
    # ---------------------------------------------------------

    jobs = []

    for source_name in sources:

        collector = COLLECTORS.get(source_name)

        if not collector:

            investigation.collection_runs.append(
                CollectionRun(
                    source=source_name,
                    category=collector_category(source_name),
                    status=CollectorStatus.skipped,
                    query=investigation.target.value,
                    error="Collector not registered.",
                )
            )

            continue

        jobs.append(
            _run_collector(
                collector,
                investigation.target.value,
                max_results,
            )
        )

    results = await asyncio.gather(
        *jobs,
        return_exceptions=True,
    )

    # ---------------------------------------------------------
    # Process collector results
    # ---------------------------------------------------------

    for result in results:

        if isinstance(result, CollectorFailure):

            investigation.collection_runs.append(
                CollectionRun(
                    source=result.source,
                    category=collector_category(result.source),
                    status=result.status,
                    query=investigation.target.value,
                    error=result.error,
                    result_count=0,
                    completed_at=utc_now(),
                )
            )

            investigation.errors.append(
                f"{result.source}: {result.error}"
            )

            continue

        source_name, evidence = result

        status = (
            CollectorStatus.success
            if evidence
            else CollectorStatus.empty
        )

        investigation.collection_runs.append(
            CollectionRun(
                source=source_name,
                category=collector_category(source_name),
                status=status,
                query=investigation.target.value,
                result_count=len(evidence),
                completed_at=utc_now(),
            )
        )

        for item in evidence:

            if not _duplicate_evidence(
                investigation.evidence,
                item,
            ):
                investigation.evidence.append(
                    item
                )

    # ---------------------------------------------------------
    # Rebuild entity index
    # ---------------------------------------------------------

    rebuild_entities(investigation)

    investigation.status = "complete"
    investigation.updated_at = utc_now()

    return store.update(investigation)


class CollectorFailure:

    def __init__(
        self,
        source: str,
        error: str,
        status: CollectorStatus = CollectorStatus.error,
    ):
        self.source = source
        self.error = error
        self.status = status


def _duplicate_evidence(
    existing: list[Evidence],
    candidate: Evidence,
) -> bool:

    # Same evidence ID
    if any(
        item.id == candidate.id
        for item in existing
    ):
        return True

    # Same URL
    if candidate.url and any(
        item.url == candidate.url
        for item in existing
        if item.url
    ):
        return True

    return False


def rebuild_entities(
    investigation: Investigation,
):

    entities = {}

    for evidence in investigation.evidence:

        for entity in evidence.entities:

            entities[entity.id] = entity

    investigation.entities = list(
        entities.values()
    )


async def _run_collector(collector, query, max_results):
    try:
        evidence = await collector.search(query, max_results)
        return collector.name, evidence

    except httpx.TimeoutException:
        return CollectorFailure(
            source=collector.name,
            error="Collector timed out.",
            status=CollectorStatus.timeout,
        )

    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403, 429):
            return CollectorFailure(
                source=collector.name,
                error=f"Source returned HTTP {exc.response.status_code}.",
                status=CollectorStatus.blocked,
            )

        return CollectorFailure(
            source=collector.name,
            error=f"Source returned HTTP {exc.response.status_code}.",
            status=CollectorStatus.error,
        )

    except Exception as exc:
        return CollectorFailure(
            source=collector.name,
            error=str(exc),
            status=CollectorStatus.error,
        )
