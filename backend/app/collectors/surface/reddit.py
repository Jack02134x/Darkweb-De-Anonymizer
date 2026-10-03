import httpx

from ...config import settings
from ...extractors.ioc import extract_entities
from ...models import (
    Evidence,
    EvidenceType,
    SourceKind,
)

from ..base import Collector


class RedditCollector(Collector):

    name = "reddit"

    async def search(
        self,
        query: str,
        max_results: int = 20,
    ) -> list[Evidence]:

        headers = {
            "User-Agent": settings.user_agent,
            "Accept": "application/json",
        }

        url = (
            "https://www.reddit.com/search.json"
        )

        params = {
            "q": query,
            "limit": min(max_results, 100),
            "type": "link",
        }

        async with httpx.AsyncClient(
            timeout=settings.request_timeout,
            headers=headers,
        ) as client:

            response = await client.get(
                url,
                params=params,
            )

            response.raise_for_status()

            payload = response.json()

        results = []

        children = (
            payload
            .get("data", {})
            .get("children", [])
        )

        for child in children:

            data = child.get("data", {})

            title = data.get("title", "")
            selftext = data.get("selftext", "")
            author = data.get("author")

            content = f"{title}\n{selftext}".strip()

            results.append(
                Evidence(
                    id=f"reddit:{data.get('id', '')}",
                    source="Reddit",
                    source_kind=SourceKind.reddit,
                    evidence_type=EvidenceType.post,
                    url=(
                        f"https://www.reddit.com"
                        f"{data.get('permalink', '')}"
                    ),
                    title=title,
                    author=author,
                    excerpt=selftext[:500],
                    content=content,
                    entities=extract_entities(content),
                    metadata={
                        "subreddit": data.get(
                            "subreddit"
                        ),
                        "score": data.get(
                            "score"
                        ),
                        "num_comments": data.get(
                            "num_comments"
                        ),
                    },
                )
            )

        return results