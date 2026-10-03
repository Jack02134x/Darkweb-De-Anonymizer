import logging
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import settings
from ..collectors.onion.crawler import OnionCrawler


log = logging.getLogger("tracepoint.ahmia")

AHMIA = "https://ahmia.fi"


async def ahmia_search(term: str, limit: int = 50) -> list[str]:
    """
    Ask the Ahmia onion search engine which onion pages mention the
    term. Returns onion URLs; an empty list if Ahmia is unreachable.
    The pages are only candidates: the crawler verifies each one.
    """

    try:
        async with httpx.AsyncClient(
            timeout=settings.request_timeout * 2,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        ) as client:

            # The search form carries a rotating hidden token that the
            # search endpoint requires.
            home = await client.get(f"{AHMIA}/")
            home.raise_for_status()

            form = BeautifulSoup(home.text, "lxml")

            params = {
                field["name"]: field.get("value", "")
                for field in form.select("#searchForm input[type=hidden]")
                if field.get("name")
            }
            params["q"] = term

            response = await client.get(f"{AHMIA}/search/", params=params)
            response.raise_for_status()

    except httpx.HTTPError as exc:
        log.warning("Ahmia search failed: %s", exc)
        return []

    soup = BeautifulSoup(response.text, "lxml")

    urls = []

    for anchor in soup.select("li.result h4 a[href]"):

        href = anchor["href"]

        # Result links go through /search/redirect?redirect_url=<onion>
        target = parse_qs(urlparse(href).query).get("redirect_url", [href])[0]

        normalized = OnionCrawler._normalize_onion_url(target)

        if normalized:
            urls.append(normalized)

    urls = list(dict.fromkeys(urls))[:limit]

    log.info("Ahmia returned %d onion URLs for %r", len(urls), term)

    return urls
