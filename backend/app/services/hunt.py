import asyncio
import logging
from urllib.parse import urlparse

from ..config import settings
from ..collectors.onion.queue_worker import (
    PRIORITY_HUNT_MIN,
    PRIORITY_SEARCH_HIT,
    onion_worker,
)
from ..database import (
    add_url,
    add_watch_alias,
    claim_pending_urls,
    requeue_url,
    search_pages,
)
from .matching import mentions_alias
from .onion_search import ahmia_search


log = logging.getLogger("tracepoint.hunt")

# Crawls still running when a hunt's time budget ends keep going in the
# background; hold references so they are not garbage-collected.
_background: set[asyncio.Task] = set()


async def hunt(alias: str) -> dict:
    """
    Actively look for an alias on onion services:

    1. Put the alias on the watchlist, so every crawler follows links
       from any page that mentions it.
    2. Queue onion pages that a search engine (Ahmia) associates with it.
    3. If the alias is new, re-crawl already-indexed pages mentioning it
       so their links get followed too.
    4. Crawl the high-priority part of the queue for up to
       `settings.hunt_seconds`. Whatever is left continues in the
       background worker.
    """

    alias = alias.strip()

    is_new = add_watch_alias(alias)

    search_hits = await ahmia_search(alias) if settings.ahmia_enabled else []

    for url in search_hits:
        add_url(
            url=url,
            host=(urlparse(url).hostname or "").lower(),
            depth=0,
            priority=PRIORITY_SEARCH_HIT,
        )

    if is_new:
        for page in search_pages(alias):
            if mentions_alias(f"{page['title'] or ''}\n{page['content'] or ''}", alias):
                requeue_url(page["url_id"], PRIORITY_SEARCH_HIT)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + settings.hunt_seconds

    running: set[asyncio.Task] = set()
    crawled = 0

    while True:

        remaining = deadline - loop.time()

        if remaining <= 0:
            break

        free = settings.hunt_concurrency - len(running)

        if free > 0:
            for item in claim_pending_urls(free, PRIORITY_HUNT_MIN):
                running.add(asyncio.create_task(onion_worker.process_item(item)))

        if not running:
            break

        done, running = await asyncio.wait(
            running,
            timeout=remaining,
            return_when=asyncio.FIRST_COMPLETED,
        )

        crawled += len(done)

    for task in running:
        _background.add(task)
        task.add_done_callback(_background.discard)

    log.info(
        "Hunt for %r: %d search hits, %d pages crawled, %d still running",
        alias,
        len(search_hits),
        crawled,
        len(running),
    )

    return {
        "search_engine_hits": len(search_hits),
        "pages_crawled": crawled,
        "still_crawling": len(running),
    }
