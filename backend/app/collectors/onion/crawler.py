import asyncio
import re
import uuid
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from ...config import settings
from ...extractors.ioc import extract_entities
from ...models import Evidence, EvidenceType, SourceKind


ONION_HOST_RE = re.compile(
    r"[a-z2-7]{16,56}\.onion",
    re.IGNORECASE,
)


class OnionCrawler:
    name = "onion"

    def __init__(
        self,
        socks_proxy: str = settings.tor_proxy,
    ):
        self.socks_proxy = socks_proxy

    async def crawl_page(
        self,
        url: str,
        depth: int = 0,
        source_url: str | None = None,
    ):
        """
        Crawl exactly ONE URL.

        This is the method used by queue_worker.py.

        It:
            1. Fetches the page through Tor.
            2. Parses the HTML.
            3. Extracts IOCs/entities.
            4. Creates Evidence.
            5. Discovers onion links (same-host pages and
               the roots of other onion services).
            6. Returns the evidence + discovered URLs.

        The queue worker is responsible for putting the
        discovered URLs into SQLite.
        """

        normalized = self._normalize_onion_url(
            url
        )

        if not normalized:
            raise ValueError(
                "Invalid onion URL."
            )

        timeout = httpx.Timeout(
            settings.request_timeout,
            connect=settings.request_timeout,
        )

        async with httpx.AsyncClient(
            proxy=self.socks_proxy,
            timeout=timeout,
            follow_redirects=False,
            headers={
                "User-Agent": settings.user_agent,
            },
        ) as client:

            try:
                response = await client.get(
                    normalized
                )

            except httpx.TimeoutException as exc:
                raise RuntimeError(
                    f"Tor request timed out: {normalized}"
                ) from exc

            except httpx.RequestError as exc:
                raise RuntimeError(
                    f"Tor request failed: {exc}"
                ) from exc

        # ----------------------------------------------------------
        # HTTP status
        # ----------------------------------------------------------

        if response.status_code != 200:

            raise RuntimeError(
                f"HTTP {response.status_code}"
            )

        # ----------------------------------------------------------
        # Content type
        # ----------------------------------------------------------

        content_type = response.headers.get(
            "content-type",
            "",
        ).lower()

        if "text/html" not in content_type:

            return {
                "url": normalized,
                "evidence": None,
                "links": [],
                "depth": depth,
            }

        # ----------------------------------------------------------
        # Page size protection
        # ----------------------------------------------------------

        if len(response.content) > settings.max_page_size:

            raise RuntimeError(
                "Page exceeds configured size limit."
            )

        # Parsing large pages is CPU-bound; keep it off the event loop
        # so concurrent crawls and API requests stay responsive.
        return await asyncio.to_thread(
            self._parse_page,
            normalized,
            response.text,
            depth,
            source_url,
            response.status_code,
        )

    def _parse_page(
        self,
        normalized: str,
        html: str,
        depth: int,
        source_url: str | None,
        status_code: int,
    ) -> dict:

        # ----------------------------------------------------------
        # Parse HTML
        # ----------------------------------------------------------

        soup = BeautifulSoup(
            html,
            "lxml",
        )

        # Remove noisy elements before extracting text.
        for element in soup(
            [
                "script",
                "style",
                "noscript",
            ]
        ):
            element.decompose()

        # ----------------------------------------------------------
        # Page title
        # ----------------------------------------------------------

        title = (
            soup.title.get_text(
                " ",
                strip=True,
            )
            if soup.title
            else normalized
        )

        # ----------------------------------------------------------
        # Page text
        # ----------------------------------------------------------

        text = soup.get_text(
            " ",
            strip=True,
        )

        # ----------------------------------------------------------
        # IOC / entity extraction
        # ----------------------------------------------------------

        entities = extract_entities(
            text
        )

        # ----------------------------------------------------------
        # Evidence
        # ----------------------------------------------------------

        evidence = Evidence(
            id=str(uuid.uuid4()),
            source="Tor / Onion",
            source_kind=SourceKind.onion,
            evidence_type=EvidenceType.webpage,
            url=normalized,
            title=title[:300],
            author=None,
            published_at=None,
            excerpt=(
                text[:500]
                if text
                else None
            ),
            content=text[
                :settings.max_page_size
            ],
            entities=entities,
            metadata={
                "network": "tor",
                "depth": depth,
                "source_url": source_url,
                "host": self._hostname(
                    normalized
                ),
                "status_code": status_code,
            },
        )

        # ----------------------------------------------------------
        # Discover child links
        # ----------------------------------------------------------

        discovered = []

        current_host = self._hostname(
            normalized
        )

        for anchor in soup.find_all(
            "a",
            href=True,
        ):

            href = anchor.get(
                "href"
            )

            if not href:
                continue

            next_url = urljoin(
                normalized,
                href,
            )

            next_url = (
                self._normalize_onion_url(
                    next_url
                )
            )

            if not next_url:
                continue

            # ------------------------------------------------------
            # Links inside this service are followed as-is. For
            # other onion services (e.g. entries in a directory)
            # only the service root is queued, so one listing page
            # cannot flood the queue with deep foreign URLs.
            # ------------------------------------------------------

            next_host = self._hostname(
                next_url
            )

            if next_host != current_host:
                next_url = f"http://{next_host}/"

            discovered.append(
                next_url
            )

        # ----------------------------------------------------------
        # Deduplicate
        # ----------------------------------------------------------

        discovered = list(
            dict.fromkeys(
                discovered
            )
        )

        return {
            "url": normalized,
            "evidence": evidence,
            "links": discovered,
            "depth": depth,
        }

    # ==============================================================
    # HELPERS
    # ==============================================================

    @staticmethod
    def _hostname(
        url: str,
    ) -> str:

        return (
            urlparse(url).hostname
            or ""
        ).lower()

    @staticmethod
    def _normalize_onion_url(
        url: str,
    ) -> str | None:

        try:

            parsed = urlparse(
                url
            )

            if parsed.scheme not in {
                "http",
                "https",
            }:
                return None

            hostname = (
                parsed.hostname
                or ""
            ).lower()

            # ------------------------------------------------------
            # Only accept valid onion hostnames.
            # ------------------------------------------------------

            if not ONION_HOST_RE.fullmatch(
                hostname
            ):
                return None

            # ------------------------------------------------------
            # Remove URL fragments.
            # ------------------------------------------------------

            clean = url.split(
                "#",
                1,
            )[0]

            return clean

        except Exception:
            return None
