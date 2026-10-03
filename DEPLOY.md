# Deploying TracePoint

The app has two parts with very different hosting needs:

| Part | Where | Why |
| --- | --- | --- |
| **Frontend** (React/Vite) | **Vercel** | Static site; Vercel is ideal. |
| **Backend** (FastAPI + Tor crawler) | **Render or Koyeb** (Docker) | Needs Tor, a long-running process and a writable disk — none of which Vercel's serverless functions provide. |

Deploy the **backend first** so you have its URL for the frontend.

---

## 1. Backend → Render (free, no credit card)

The repo already contains a `Dockerfile` (installs Tor + the API) and a
`render.yaml` blueprint.

1. Push this repo to GitHub (it already has an `origin` remote).
2. Go to <https://render.com> → **New** → **Blueprint** → pick this repo.
   Render reads `render.yaml` and creates a free Docker web service.
   *(Or: **New → Web Service → Docker**, select the repo, leave the
   Dockerfile path as `./Dockerfile`, plan Free.)*
3. Wait for the first build (~3–6 min). You'll get a URL like
   `https://tracepoint-backend.onrender.com`.
4. Check it: open `https://<your-backend>.onrender.com/api/health` —
   you should see `{"status":"ok",...}`.
5. Leave the `TRACEPOINT_CORS_ORIGINS` env var for now; you'll set it to
   the Vercel URL in step 3.

### Koyeb instead of Render
<https://koyeb.com> → **Create Service** → **GitHub** → select the repo →
builder **Dockerfile** → set the port to **8000** → Deploy. Add the same
env vars under the service's **Environment** tab.

---

## 2. Frontend → Vercel

The repo's `vercel.json` already builds only the frontend.

1. Go to <https://vercel.com> → **Add New → Project** → import this repo.
   Leave the Root Directory as the repository root (do **not** set it to
   `frontend`; `vercel.json` handles the build).
2. Under **Environment Variables**, add:

   | Name | Value |
   | --- | --- |
   | `VITE_API_BASE` | `https://<your-backend>.onrender.com/api` |

   (Note the trailing `/api`, and no trailing slash.)
3. **Deploy.** You'll get a URL like
   `https://darkweb-de-anonymizer.vercel.app`.

---

## 3. Point the backend back at the frontend (CORS)

The browser will block the frontend from calling the backend until the
backend allows its origin.

1. In Render → your service → **Environment**, set:

   | Name | Value |
   | --- | --- |
   | `TRACEPOINT_CORS_ORIGINS` | `https://darkweb-de-anonymizer.vercel.app` |

   The blueprint already adds `TRACEPOINT_CORS_ORIGIN_REGEX =
   https://.*\.vercel\.app` so Vercel **preview** deployments work too.
2. Save → Render redeploys automatically.
3. Open your Vercel URL. The header should read **API ONLINE** and a
   search should work.

---

## What to expect on the free tier

- **Cold starts.** A free Render/Koyeb service **sleeps after ~15 min**
  of no traffic and takes ~30–60s to wake on the next visit. During that
  window the UI shows **API OFFLINE**; just wait and retry.
- **Tor bootstrap.** After each wake, Tor needs ~30s before `.onion`
  crawling works. Surface sources (GitHub/GitLab) and the keyserver
  check work immediately.
- **Data resets on restart.** Free tiers have no persistent disk, so the
  crawl queue and actor database start empty after a restart/redeploy.
  The crawler re-seeds and rebuilds automatically; you only lose
  history, not functionality.
- **Searches take ~60s** because each one runs a live onion hunt
  (tunable with `TRACEPOINT_HUNT_SECONDS`).

## Useful backend env vars

| Variable | Default | Purpose |
| --- | --- | --- |
| `TRACEPOINT_CORS_ORIGINS` | localhost | Comma-separated allowed frontend origins |
| `TRACEPOINT_CORS_ORIGIN_REGEX` | — | Regex for origins (Vercel previews) |
| `TRACEPOINT_ONION_WORKER` | `1` | `0` disables the background crawler (saves resources) |
| `TRACEPOINT_HUNT_SECONDS` | `60` | Time each search spends live-crawling |
| `GITHUB_TOKEN` / `GITLAB_TOKEN` | — | Optional; raise API limits / enable fuzzy GitLab search |
