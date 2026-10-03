import httpx

from ...config import settings
from ...extractors.ioc import extract_entities
from ...models import (
    Evidence,
    EvidenceType,
    SourceKind,
)

from ..base import Collector


class GitLabCollector(Collector):

    name = "gitlab"

    API = "https://gitlab.com/api/v4"

    async def search(
        self,
        query: str,
        max_results: int = 20,
    ) -> list[Evidence]:

        headers = {
            "User-Agent": settings.user_agent,
            "Accept": "application/json",
        }

        # GitLab only allows fuzzy user search for authenticated
        # requests; without a token fall back to exact username lookup.
        if settings.gitlab_token:
            headers["PRIVATE-TOKEN"] = settings.gitlab_token

            params = {
                "search": query,
                "per_page": min(max_results, 100),
                "page": 1,
            }
        else:
            params = {
                "username": query,
            }

        async with httpx.AsyncClient(
            timeout=settings.request_timeout,
            headers=headers,
            follow_redirects=True,
        ) as client:

            response = await client.get(
                f"{self.API}/users",
                params=params,
            )

            response.raise_for_status()

            users = response.json()

            results = []

            for user in users:

                username = user.get("username")

                if not username:
                    continue

                profile = await self._get_user(
                    client,
                    username,
                )

                name = profile.get(
                    "name",
                    user.get("name"),
                )

                bio = profile.get(
                    "bio",
                    "",
                )

                web_url = profile.get(
                    "web_url",
                    user.get("web_url"),
                )

                text = " ".join(
                    [
                        username or "",
                        name or "",
                        bio or "",
                        web_url or "",
                    ]
                ).strip()

                results.append(
                    Evidence(
                        id=f"gitlab:user:{username.lower()}",
                        source="GitLab",
                        source_kind=SourceKind.gitlab,
                        evidence_type=EvidenceType.profile,
                        url=web_url,
                        title=f"GitLab profile: {username}",
                        author=username,
                        excerpt=bio,
                        content=text,
                        entities=extract_entities(text),
                        metadata={
                            "username": username,
                            "name": name,
                            "state": profile.get(
                                "state"
                            ),
                            "web_url": web_url,
                            "avatar_url": profile.get(
                                "avatar_url"
                            ),
                        },
                    )
                )

        return results

    async def _get_user(
        self,
        client: httpx.AsyncClient,
        username: str,
    ) -> dict:

        response = await client.get(
            f"{self.API}/users",
            params={
                "username": username,
            },
        )

        if response.status_code != 200:
            return {}

        users = response.json()

        return users[0] if users else {}
