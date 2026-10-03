# TracePoint — SIH26151 Prototype

**Problem statement SIH26151: Dark web threat actor de-anonymization.**

TracePoint correlates a threat actor's identifier (alias, handle, email, wallet…) across Tor onion services and the public surface web. It extracts technical indicators (emails, domains, IPs, BTC wallets, PGP fingerprints, Telegram handles) from every source and draws an entity graph. Shared indicators then link an anonymous onion persona to public profiles.

Correlations are leads for human review, not identity conclusions.

## How it works

```
onion_sources.json ──► SQLite URL queue ──► background Tor crawler ──► indexed pages (SQLite)
                                                                              │
search "alias" ──► collectors: onion (index) · github · gitlab · reddit · web ┘
                         │
                         ▼
                IOC extraction ──► investigation (evidence + entities) ──► React/D3 graph
```

- **Alias hunt (every search).** The alias goes on a watchlist. Ahmia, an onion search engine, is asked which onion pages mention it, and those pages are crawled over Tor right away (up to `TRACEPOINT_HUNT_SECONDS`, default 60). The search returns only pages with a **whole-word** mention of the alias (`8chan` does not match `8chanho`). Each result carries only the indicators found within about 300 characters of a mention, and mirror sites are merged.
- **Following the trail.** When any crawler finds a watched alias on a page, it queues that page's links ahead of everything else and resets their depth count. The crawl keeps following the actor's footprint as deep as it goes, while unrelated branches stop at `TRACEPOINT_ONION_MAX_DEPTH` (default 3). The background worker keeps going after the search returns, so **repeating a search later finds more**.
- **Background discovery.** With no search running, the worker crawls outward from `backend/data/onion_sources.json`.
- **Surface web.** GitHub and GitLab match the exact handle only.

## Requirements

- Python 3.10+
- Node.js 20+
- Tor running locally with a SOCKS proxy on `127.0.0.1:9050` (`sudo systemctl start tor`)

## Run locally

Backend (from the project root):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd backend
uvicorn app.main:app --reload --port 8000
```

Frontend (in another terminal):

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173.

## Configuration (environment variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `TRACEPOINT_TOR_PROXY` | `socks5://127.0.0.1:9050` | Tor SOCKS proxy |
| `TRACEPOINT_ONION_WORKER` | `1` | Set `0` to disable the background crawler |
| `TRACEPOINT_ONION_MAX_DEPTH` | `3` | Maximum link depth from a seed |
| `TRACEPOINT_REQUEST_TIMEOUT` | `10` | HTTP timeout, seconds |
| `TRACEPOINT_HUNT_SECONDS` | `60` | Time each search spends live-crawling for the alias |
| `TRACEPOINT_HUNT_CONCURRENCY` | `6` | Parallel Tor fetches during a hunt |
| `TRACEPOINT_AHMIA` | `1` | Set `0` to skip the Ahmia lookup (it is sent over clearnet) |
| `GITHUB_TOKEN` | — | Optional; raises the GitHub API rate limit |
| `GITLAB_TOKEN` | — | Optional; enables fuzzy GitLab user search (otherwise exact username only) |

Reddit blocks unauthenticated API access, so the Reddit collector usually reports `blocked`.

## API

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/health` | Service status and registered collectors |
| POST | `/api/search` | `{query, sources[], max_results}` → investigation |
| GET | `/api/investigations` / `/{id}` | In-memory investigations |
| POST | `/api/investigations/{id}/collect` | Re-run collectors on an investigation |
| GET | `/api/onion/queue` | Crawl queue counts, indexed pages and watched aliases |
| POST | `/api/onion/discover` | `{url}` — fetch one onion page and queue the onion links on it |
| POST | `/api/fetch-url` | `{url}` — fetch a surface web page and extract IOCs |
| GET | `/api/intel/stats` | Counts of actors, observations, identifiers and links |
| GET | `/api/actors` | Actor profiles; filter by `category`, `min_confidence` |
| GET | `/api/actors/{handle}` | One actor: identifiers, linked personas, sources |
| GET | `/api/observations` | Timeline query; filter by `since`, `until`, `identifier_type`, `actor_handle`, `host` |
| GET | `/api/export/actors.csv` | Actor set as CSV |
| GET | `/api/export/observations.csv` | Sightings as CSV (same filters as `/api/observations`) |
| GET | `/api/export/intel.json` | Full intelligence set as JSON |
| GET | `/api/export/report.html` | Printable HTML report (save as PDF) |
| GET | `/api/pgp/verify/{fingerprint}` | Check a fingerprint against keys.openpgp.org (confirms the key exists; returns UID name/email when served) |

Interactive docs: http://127.0.0.1:8000/docs

## Actor intelligence

As the crawler indexes onion pages that mention a watched alias, it builds a persistent record in SQLite (survives restarts):

- **observations** — every sighting of an identifier (PGP fingerprint, BTC/Monero wallet, email, Telegram, domain, IP) on a source, with a timestamp. This is the timeline-queryable fact table.
- **actors** — persona clusters keyed by handle, each with a category, first/last-seen dates and an **attribution confidence** (0–0.95, capped — these are leads, not proof).
- **actor_identifiers** — the identifiers tied to each actor (only those found near a mention of the handle, not every identifier on the page).
- **actor_links** — relationships between actors who **share a strong identifier** (PGP key, wallet or email). This is how a rebranded or migrated persona on a new market is linked back to a known actor. Each link records the shared value and a confidence weight.

Attribution confidence combines how many distinct sources the actor was seen on, whether it holds a strong identifier, and the strongest cross-actor link. Every correlation is an investigative lead for human review.

**PGP key parsing.** When a page pastes a PGP public key block, the system computes the key's real fingerprint and reads the User ID packets inside it for the name and email the operator chose — often the strongest single leak on a page. Two handles that paste the same key are linked with high confidence, which is how a rebranded or migrated vendor on a new market is tied back to a known actor.

## Project layout

- `backend/app/main.py`: FastAPI app, startup/shutdown, routes
- `backend/app/collectors/surface/`: GitHub, GitLab, Reddit and web page collectors
- `backend/app/collectors/onion/crawler.py`: fetches and parses one onion page over Tor
- `backend/app/collectors/onion/queue_worker.py`: priority crawl queue processing (trail following)
- `backend/app/collectors/onion/collector.py`: runs the hunt, returns pages that mention the alias
- `backend/app/extractors/ioc.py`: indicator (IOC) extraction — emails, domains, IPs, BTC and Monero wallets, Telegram, PGP
- `backend/app/extractors/pgp.py`: parses pasted PGP public-key blocks for the real fingerprint and the UID name/email
- `backend/app/services/hunt.py`: live alias hunt (Ahmia lookup + time-boxed crawl)
- `backend/app/services/matching.py`: whole-word alias matching and context windows
- `backend/app/services/onion_search.py`: Ahmia search client
- `backend/app/intel/store.py`: persistent actor/observation schema and queries
- `backend/app/intel/ingest.py`: turns crawled pages into actor intelligence
- `backend/app/intel/linker.py`: links actors by shared identifiers; attribution confidence
- `backend/app/intel/export.py`: CSV / JSON / HTML report export
- `backend/app/services/investigation.py`, `url_discovery.py`: investigation orchestration, manual onion link discovery
- `backend/app/database.py`: SQLite URL queue and page index (`backend/data/tracepoint.db`)
- `frontend/`: Vite + React + D3 interface
