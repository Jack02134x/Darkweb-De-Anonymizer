import hashlib

from ...database import search_pages
from ...extractors.ioc import extract_entities
from ...models import (
    Evidence,
    EvidenceType,
    SourceKind,
)
from ...services.matching import (
    context_windows,
    find_mentions,
)

from ..base import Collector


class OnionCollector(Collector):
    """
    Finds onion pages on which the alias actually appears.

    Each search first runs a live hunt (search engine lookup plus a
    time-boxed Tor crawl that follows the alias's trail), then returns
    indexed pages containing a whole-word mention of the alias. Only
    indicators found near a mention are attached, so a directory page
    that happens to list the alias does not pull in every link on it.
    """

    name = "onion"

    async def search(
        self,
        query: str,
        max_results: int = 20,
    ) -> list[Evidence]:

        # Imported here: services.hunt depends on this package.
        from ...services.hunt import hunt

        alias = query.strip()

        hunt_stats = await hunt(alias)

        # Group identical pages (mirrors of the same service) together.
        by_content: dict[str, dict] = {}

        for page in search_pages(alias):

            title = page["title"] or ""
            content = page["content"] or ""

            spans = find_mentions(content, alias)
            in_title = bool(find_mentions(title, alias))
            in_url = bool(find_mentions(page["url"], alias))

            if not (spans or in_title or in_url):
                continue

            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

            if digest in by_content:
                by_content[digest]["mirrors"].append(page["url"])
                continue

            by_content[digest] = {
                "page": page,
                "spans": spans,
                "in_title": in_title,
                "mirrors": [],
            }

        # Most mentions first; a mention in the title counts extra.
        ranked = sorted(
            by_content.values(),
            key=lambda hit: len(hit["spans"]) + 5 * hit["in_title"],
            reverse=True,
        )

        results = []

        for hit in ranked[:max_results]:

            page = hit["page"]
            content = page["content"] or ""

            windows = context_windows(content, hit["spans"])

            results.append(
                Evidence(
                    id=f"onion:{page['url_id']}",
                    source="Tor / Onion",
                    source_kind=SourceKind.onion,
                    evidence_type=EvidenceType.webpage,
                    url=page["url"],
                    title=page["title"],
                    collected_at=page["crawled_at"],
                    excerpt=_excerpt(content, hit["spans"]),
                    content=content,
                    entities=extract_entities("\n".join(windows)),
                    metadata={
                        **page["metadata"],
                        "alias": alias,
                        "mentions": len(hit["spans"]),
                        "mirrors": hit["mirrors"],
                        "hunt": hunt_stats,
                    },
                )
            )

        return results


def _excerpt(text: str, spans: list[tuple[int, int]], width: int = 500) -> str | None:
    """Return a window of text around the first mention."""

    if not text:
        return None

    if not spans:
        return text[:width]

    start = max(0, spans[0][0] - width // 3)

    prefix = "…" if start else ""

    return prefix + text[start:start + width]
