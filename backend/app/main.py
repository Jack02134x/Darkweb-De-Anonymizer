import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, HttpUrl

from .collectors import COLLECTORS
from .collectors.onion.queue_worker import onion_worker
from .config import settings
from .database import (
    add_url,
    get_url_stats,
    init_db,
)
from .models import (
    SearchRequest,
    Target,
    TargetType,
    URLRequest,
)
from .intel import (
    get_actor,
    init_intel_db,
    list_actors,
    query_observations,
    stats as intel_stats,
)
from .intel.export import (
    export_actors_csv,
    export_json,
    export_observations_csv,
    export_report_html,
)
from .services.investigation import (
    collect,
    create_investigation,
)
from .services.pgp_verify import verify_fingerprint
from .services.url_discovery import discover_from_url
from .storage import store


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# httpx logs every request at INFO, which drowns out crawler output.
logging.getLogger("httpx").setLevel(logging.WARNING)

ONION_SOURCES_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "onion_sources.json"
)


class URLDiscoveryRequest(BaseModel):
    url: HttpUrl
    max_links: int = 100


def seed_onion_queue():
    """Queue every enabled seed from data/onion_sources.json."""

    if not ONION_SOURCES_PATH.exists():
        return

    sources = json.loads(
        ONION_SOURCES_PATH.read_text(encoding="utf-8")
    )

    for source in sources:

        if not source.get("enabled", True):
            continue

        add_url(
            url=source["url"],
            host=(urlparse(source["url"]).hostname or "").lower(),
            depth=0,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):

    init_db()
    init_intel_db()
    seed_onion_queue()

    worker_task = None

    if settings.onion_worker_enabled:
        worker_task = asyncio.create_task(
            onion_worker.run_forever(interval=2)
        )

    yield

    if worker_task:
        onion_worker.stop()
        worker_task.cancel()

        try:
            await worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="TracePoint OSINT investigation platform",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():

    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.version,
        "collectors": list(COLLECTORS.keys()),
        "onion_worker": onion_worker.running,
    }


@app.get("/api/onion/queue")
async def onion_queue():

    return get_url_stats()


@app.post("/api/onion/discover")
async def discover_onion_links(request: URLDiscoveryRequest):

    try:
        return await discover_from_url(
            str(request.url),
            max_links=min(request.max_links, 500),
        )

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not fetch onion URL through Tor: {exc}",
        ) from exc


@app.get("/api/investigations")
async def list_investigations():

    return store.list()


@app.get(
    "/api/investigations/{investigation_id}"
)
async def get_investigation(
    investigation_id: str,
):

    investigation = store.get(
        investigation_id
    )

    if not investigation:
        raise HTTPException(
            status_code=404,
            detail="Investigation not found.",
        )

    return investigation


@app.post(
    "/api/investigations/{investigation_id}/collect"
)
async def collect_investigation(
    investigation_id: str,
    request: SearchRequest,
):

    investigation = store.get(
        investigation_id
    )

    if not investigation:
        raise HTTPException(
            status_code=404,
            detail="Investigation not found.",
        )

    return await collect(
        investigation,
        request.sources,
        request.max_results,
    )


@app.post("/api/search")
async def search(
    request: SearchRequest,
):

    target = Target(
        value=request.query,
        type=TargetType.username,
    )

    investigation = create_investigation(
        target
    )

    return await collect(
        investigation,
        request.sources,
        request.max_results,
    )


@app.post("/api/fetch-url")
async def fetch_url(
    request: URLRequest,
):

    collector = COLLECTORS["web"]

    try:
        results = await collector.fetch_url(
            request.url
        )

    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "url": request.url,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Actor intelligence: profiles, timeline, export
# ---------------------------------------------------------------------------

@app.get("/api/intel/stats")
async def intel_statistics():

    return intel_stats()


@app.get("/api/actors")
async def actors(
    category: str | None = None,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(500, ge=1, le=5000),
):

    return list_actors(
        category=category,
        min_confidence=min_confidence,
        limit=limit,
    )


@app.get("/api/actors/{handle}")
async def actor_profile(handle: str):

    actor = get_actor(handle)

    if not actor:
        raise HTTPException(status_code=404, detail="Actor not found.")

    return actor


@app.get("/api/observations")
async def observations(
    since: str | None = None,
    until: str | None = None,
    identifier_type: str | None = None,
    actor_handle: str | None = None,
    host: str | None = None,
    limit: int = Query(1000, ge=1, le=100000),
):
    """Timeline query over identifier sightings."""

    return query_observations(
        since=since,
        until=until,
        identifier_type=identifier_type,
        actor_handle=actor_handle,
        host=host,
        limit=limit,
    )


@app.get("/api/export/actors.csv")
async def export_actors():

    return PlainTextResponse(
        export_actors_csv(),
        headers={
            "Content-Disposition": "attachment; filename=actors.csv",
        },
        media_type="text/csv",
    )


@app.get("/api/export/observations.csv")
async def export_observations(
    since: str | None = None,
    until: str | None = None,
    identifier_type: str | None = None,
    actor_handle: str | None = None,
):

    csv_text = export_observations_csv(
        since=since,
        until=until,
        identifier_type=identifier_type,
        actor_handle=actor_handle,
    )

    return PlainTextResponse(
        csv_text,
        headers={
            "Content-Disposition": "attachment; filename=observations.csv",
        },
        media_type="text/csv",
    )


@app.get("/api/export/intel.json")
async def export_intel_json():

    return Response(
        export_json(),
        headers={
            "Content-Disposition": "attachment; filename=intel.json",
        },
        media_type="application/json",
    )


@app.get("/api/export/report.html")
async def export_report():

    return HTMLResponse(export_report_html())


@app.get("/api/pgp/verify/{fingerprint}")
async def pgp_verify(fingerprint: str):
    """Check whether a PGP fingerprint exists on a public keyserver."""

    return await verify_fingerprint(fingerprint)
