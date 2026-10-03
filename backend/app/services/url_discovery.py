import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ..config import settings
from ..database import add_url


ONION_HOST_RE = re.compile(
    r"^[a-z2-7]{16,56}\.onion$",
    re.IGNORECASE,
)


def is_onion_url(url: str) -> bool:
    try:
        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"}:
            return False

        host = (parsed.hostname or "").lower()

        return bool(ONION_HOST_RE.fullmatch(host))

    except Exception:
        return False


def normalize_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)

        if parsed.scheme not in {"http", "https"}:
            return None

        host = (parsed.hostname or "").lower()

        if not ONION_HOST_RE.fullmatch(host):
            return None

        return url.split("#", 1)[0]

    except Exception:
        return None


async def discover_from_url(url: str, max_links: int = 100):
    url = normalize_url(url)

    if not url:
        raise ValueError("Only valid .onion URLs are accepted.")

    timeout = httpx.Timeout(
        settings.request_timeout,
        connect=settings.request_timeout,
    )

    async with httpx.AsyncClient(
        proxy=settings.tor_proxy,
        timeout=timeout,
        follow_redirects=True,
        headers={
            "User-Agent": settings.user_agent,
        },
    ) as client:

        response = await client.get(url)

        response.raise_for_status()

        if len(response.content) > settings.max_page_size:
            raise ValueError("Page exceeds configured size limit.")

        content_type = response.headers.get(
            "content-type",
            "",
        ).lower()

        if "text/html" not in content_type:
            raise ValueError(
                f"Unsupported content type: {content_type}"
            )

        html = response.text

    soup = BeautifulSoup(html, "lxml")

    discovered = []

    for anchor in soup.find_all("a", href=True):

        href = anchor.get("href")

        if not href:
            continue

        absolute = urljoin(url, href)

        normalized = normalize_url(absolute)

        if not normalized:
            continue

        discovered.append(normalized)

        if len(discovered) >= max_links:
            break

    # Remove duplicates while preserving order
    discovered = list(dict.fromkeys(discovered))

    inserted = 0

    for discovered_url in discovered:

        host = (urlparse(discovered_url).hostname or "").lower()

        result = add_url(
            url=discovered_url,
            host=host,
            depth=1,
            source_url=url,
        )

        if result:
            inserted += 1

    return {
        "source": url,
        "links_found": len(discovered),
        "links_inserted": inserted,
        "links": discovered,
    }