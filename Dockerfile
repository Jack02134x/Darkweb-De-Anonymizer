# Backend image for Render / Koyeb / any container host.
# Runs Tor (for .onion crawling) alongside the FastAPI app.
FROM python:3.12-slim

# tor  : local SOCKS proxy the crawler uses for .onion requests
# curl : used by the container health check
RUN apt-get update \
    && apt-get install -y --no-install-recommends tor curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY start.sh .
RUN chmod +x start.sh

# The host sets $PORT; default to 8000 for local `docker run`.
ENV PORT=8000
EXPOSE 8000

CMD ["./start.sh"]
