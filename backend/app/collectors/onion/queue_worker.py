import asyncio
import logging
from urllib.parse import urlparse

from ...config import settings
from ...database import (
    add_url,
    claim_pending_urls,
    get_watch_aliases,
    mark_done,
    mark_failed,
    save_page,
)
from ...intel.ingest import ingest_page
from ...services.matching import mentions_alias
from .crawler import OnionCrawler


log = logging.getLogger("tracepoint.onion")


# Queue priorities. Higher is crawled first.
PRIORITY_SEARCH_HIT = 100   # onion search engine result for an alias
PRIORITY_ALIAS_TRAIL = 60   # linked from a page that mentions an alias
PRIORITY_HUNT_MIN = 50      # live hunts only crawl at or above this
PRIORITY_NORMAL = 0         # general background discovery


class OnionQueueWorker:

    def __init__(self, crawler, max_depth: int = settings.onion_max_depth):
        self.crawler = crawler
        self.max_depth = max_depth
        self.running = False

    async def process_item(self, item: dict) -> bool:
        """
        Crawl one claimed queue item, index it, and queue its links.

        `depth` counts hops since a seed or since the last page that
        mentioned a watched alias. Pages mentioning an alias reset it,
        so the crawl follows an actor's trail as deep as it leads,
        while unrelated branches stop at `max_depth`.
        """

        url = item["url"]

        log.info("Crawling #%s %s", item["id"], url)

        try:

            result = await self.crawler.crawl_page(
                url,
                depth=item["depth"],
                source_url=item["source_url"],
            )

            evidence = result["evidence"]

            mentioned = []

            if evidence:
                save_page(item["id"], evidence)

                page_text = f"{evidence.title or ''}\n{evidence.content or ''}"

                mentioned = [
                    alias
                    for alias in get_watch_aliases()
                    if mentions_alias(page_text, alias)
                ]

                log.info(
                    "Indexed %r (%d entities)%s",
                    evidence.title,
                    len(evidence.entities),
                    f" — mentions {', '.join(mentioned)}" if mentioned else "",
                )

                # Persist identifiers tied to each mentioned alias as
                # durable actor intelligence.
                for alias in mentioned:
                    try:
                        ingest_page(alias, evidence)
                    except Exception:
                        log.exception("Intel ingest failed for %r", alias)

            links = result["links"]

            if mentioned:
                child_depth = 1
                child_priority = PRIORITY_ALIAS_TRAIL
            else:
                child_depth = item["depth"] + 1
                # Near a hit, keep some priority for a hop or two
                # (50 → 40 → …), then fall back to normal discovery.
                child_priority = (
                    PRIORITY_ALIAS_TRAIL - 10 * child_depth
                    if item["priority"] >= PRIORITY_HUNT_MIN
                    else PRIORITY_NORMAL
                )

            if child_depth <= self.max_depth:

                for child_url in links:

                    add_url(
                        url=child_url,
                        host=(urlparse(child_url).hostname or "").lower(),
                        depth=child_depth,
                        source_url=url,
                        discovered_from=item["id"],
                        priority=max(child_priority, PRIORITY_NORMAL),
                    )

            mark_done(item["id"])

            log.info("Done #%s (%d links)", item["id"], len(links))

            return True

        except Exception as exc:

            error = f"{type(exc).__name__}: {exc}"

            log.warning("Failed #%s %s: %s", item["id"], url, error)

            mark_failed(item["id"], error)

            return False

    async def run_once(self, batch_size=5, min_priority=PRIORITY_NORMAL):

        items = claim_pending_urls(batch_size, min_priority)

        results = await asyncio.gather(
            *(self.process_item(item) for item in items)
        )

        return {
            "processed": len(items),
            "successful": sum(results),
            "failed": len(items) - sum(results),
        }

    async def run_forever(
        self,
        interval=2,
    ):

        self.running = True

        log.info("Queue worker started.")

        while self.running:

            try:
                result = await self.run_once(batch_size=5)
            except Exception:
                # Never let a database hiccup kill the worker task.
                log.exception("Queue worker iteration failed.")
                result = {"processed": 0}

            if result["processed"] == 0:
                await asyncio.sleep(interval)

    def stop(self):

        self.running = False

        log.info("Queue worker stopping.")


# Shared by the background loop and live hunts.
onion_worker = OnionQueueWorker(OnionCrawler())
