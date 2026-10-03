#!/usr/bin/env bash
set -e

# Start Tor in the background. It bootstraps (~10-30s) while the API
# comes up; the API only needs Tor once a crawl actually runs, so the
# web port opens immediately and the platform's health check passes.
tor --RunAsDaemon 0 --SocksPort 9050 --Log "notice stdout" &

cd backend

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
