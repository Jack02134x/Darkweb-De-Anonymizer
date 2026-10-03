from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from ...config import settings
from ...extractors.ioc import extract_entities
from ...models import (
    Evidence,
    EvidenceType,
    SourceKind,
)

from ..base import Collector


class WebCollector(Collector):

    name = "web"

    async def search(
        self,
        query: str,
        max_results: int = 20,
    ) -> list[Evidence]:

        # Search engines will be added as dedicated adapters.
        # For now, this collector treats query as a URL.
        if not query.startswith(
            ("http://", "https://")
        ):
            return []

        return await self.fetch_url(query)

    async def fetch_url(
        self,
        url: str,
    ) -> list[Evidence]:

        headers = {
            "User-Agent": settings.user_agent,
        }

        async with httpx.AsyncClient(
            timeout=settings.request_timeout,
            headers=headers,
            follow_redirects=True,
        ) as client:

            response = await client.get(url)

            response.raise_for_status()

            content_type = response.headers.get(
                "content-type",
                "",
            ).lower()

            if "text/html" not in content_type:
                return []

            if len(response.content) > settings.max_page_size:
                raise ValueError(
                    "Page exceeds configured size limit."
                )

            html = response.text

        soup = BeautifulSoup(
            html,
            "lxml",
        )

        for element in soup(
            ["script", "style", "noscript"]
        ):
            element.decompose()

        title = (
            soup.title.get_text(strip=True)
            if soup.title
            else None
        )

        text = soup.get_text(
            " ",
            strip=True,
        )

        parsed = urlparse(url)

        return [
            Evidence(
                id=f"web:{url}",
                source=parsed.netloc,
                source_kind=SourceKind.webpage,
                evidence_type=EvidenceType.webpage,
                url=url,
                title=title,
                excerpt=text[:1000],
                content=text,
                entities=extract_entities(text),
                metadata={
                    "domain": parsed.netloc,
                    "status_code": response.status_code,
                    "content_type": content_type,
                },
            )
        ]