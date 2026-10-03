import httpx

from ...config import settings
from ...extractors.ioc import extract_entities
from ...models import (
    Evidence,
    EvidenceType,
    SourceKind,
)

from ..base import Collector


class GitHubCollector(Collector):

    name = "github"

    API = "https://api.github.com"

    async def search(
        self,
        query: str,
        max_results: int = 20,
    ) -> list[Evidence]:

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": settings.user_agent,
        }

        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"

        async with httpx.AsyncClient(
            timeout=settings.request_timeout,
            headers=headers,
        ) as client:

            response = await client.get(
                f"{self.API}/search/users",
                params={
                    "q": f"{query} in:login",
                    "per_page": min(max_results, 100),
                },
            )

            response.raise_for_status()

            payload = response.json()

            results = []

            for item in payload.get("items", []):

                login = item.get("login")

                # Only the exact handle; "8chan" must not return
                # unrelated accounts such as "8chanho".
                if not login or login.lower() != query.strip().lower():
                    continue

                profile = await self._fetch_profile(
                    client,
                    login,
                )

                text = " ".join(
                    [
                        login,
                        str(profile.get("name", "")),
                        str(profile.get("bio", "")),
                        str(profile.get("company", "")),
                        str(profile.get("blog", "")),
                    ]
                )

                results.append(
                    Evidence(
                        id=f"github:user:{login.lower()}",
                        source="GitHub",
                        source_kind=SourceKind.github,
                        evidence_type=EvidenceType.profile,
                        url=profile.get(
                            "html_url",
                            item.get("html_url"),
                        ),
                        title=f"GitHub profile: {login}",
                        author=login,
                        excerpt=profile.get("bio"),
                        content=text,
                        entities=extract_entities(text),
                        metadata={
                            "login": login,
                            "name": profile.get("name"),
                            "company": profile.get("company"),
                            "location": profile.get("location"),
                            "public_repositories": profile.get(
                                "public_repos",
                                0,
                            ),
                            "followers": profile.get(
                                "followers",
                                0,
                            ),
                        },
                    )
                )

        return results

    async def _fetch_profile(
        self,
        client: httpx.AsyncClient,
        login: str,
    ) -> dict:

        response = await client.get(
            f"{self.API}/users/{login}"
        )

        if response.status_code != 200:
            return {
                "login": login,
                "html_url": f"https://github.com/{login}",
            }

        return response.json()
