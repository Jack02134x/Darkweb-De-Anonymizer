from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    app_name: str = "TracePoint"
    version: str = "2.0.0"

    request_timeout: float = float(
        os.getenv("TRACEPOINT_REQUEST_TIMEOUT", "10")
    )

    max_results_per_source: int = int(
        os.getenv("TRACEPOINT_MAX_RESULTS", "20")
    )

    max_page_size: int = int(
        os.getenv("TRACEPOINT_MAX_PAGE_SIZE", "2_000_000")
    )

    user_agent: str = os.getenv(
        "TRACEPOINT_USER_AGENT",
        "TracePoint/2.0 (+OSINT research demonstrator)"
    )

    # Browser origins allowed to call the API (comma-separated). Set this
    # to your deployed frontend URL, e.g. "https://my-app.vercel.app".
    cors_origins: str = os.getenv(
        "TRACEPOINT_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )

    # Optional regex for origins, handy for Vercel preview URLs, e.g.
    # "https://.*\\.vercel\\.app".
    cors_origin_regex: str | None = (
        os.getenv("TRACEPOINT_CORS_ORIGIN_REGEX") or None
    )

    # Tor SOCKS proxy used for all .onion requests.
    tor_proxy: str = os.getenv(
        "TRACEPOINT_TOR_PROXY",
        "socks5://127.0.0.1:9050",
    )

    # Background onion crawler.
    onion_worker_enabled: bool = (
        os.getenv("TRACEPOINT_ONION_WORKER", "1") == "1"
    )

    onion_max_depth: int = int(
        os.getenv("TRACEPOINT_ONION_MAX_DEPTH", "3")
    )

    # Live onion hunt run on every search: how long the request may
    # spend crawling, and how many pages it fetches in parallel.
    hunt_seconds: float = float(
        os.getenv("TRACEPOINT_HUNT_SECONDS", "60")
    )

    hunt_concurrency: int = int(
        os.getenv("TRACEPOINT_HUNT_CONCURRENCY", "6")
    )

    # Use the Ahmia onion search engine to find candidate pages.
    ahmia_enabled: bool = (
        os.getenv("TRACEPOINT_AHMIA", "1") == "1"
    )

    # Optional; raises the GitHub API rate limit from 60 to 5000 req/h.
    github_token: str | None = os.getenv("GITHUB_TOKEN") or None

    # Optional; GitLab requires a token for fuzzy user search.
    gitlab_token: str | None = os.getenv("GITLAB_TOKEN") or None


settings = Settings()
