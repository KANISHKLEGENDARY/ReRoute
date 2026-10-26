# Deploying ReRoute (100% Free Tier, No Credit Card, Zero Billing Risk)

This guide walks you click-by-click through deploying ReRoute completely free:
- **Backend, PostgreSQL & Redis** on **Render** (Free tier plans)
- **Frontend** on **Vercel** (Hobby free plan)
- **Google Gemini API** on **Google AI Studio** free tier

> [!WARNING]
> **NEVER select a paid plan.** Render and Vercel offer 100% Free tiers that do not require credit cards or billing details. Always ensure the plan selector reads **"Free" ($0/month)**.

---

## 1. Safety & Cost Protection Architecture

1. **Zero Billing Risk**: Google Gemini free tier (`gemini-3.5-flash-lite`) has no attached billing account. Exceeding daily free tier limits results only in an HTTP 429 response, never a charge.
2. **Hard Daily Budget Cap**: The backend enforces `LLM_HARD_DAILY_CALL_LIMIT=100` (stops real calls after 80 attempts/day) and persists counts across stateless restarts in the PostgreSQL table `llm_usage` (`LLM_USAGE_STORE=db`).
3. **Deterministic Fallback**: If the cap is reached or network fails, the system executes deterministic policy matching in <25 ms without calling any LLM.
4. **Access Protection**: The `POST /api/v1/events/simulate` endpoint requires the `X-Demo-Key` header matching your `DEMO_API_KEY` to prevent strangers from consuming your daily quota.

---

## 2. Render Deployment (Backend, Postgres, Redis)

Follow these click-by-click steps in the [Render Dashboard](https://dashboard.render.com).

### Step 2.1: Create Free PostgreSQL Database
1. Click **New +** > **PostgreSQL**.
2. Set:
   - **Name**: `reroute-postgres`
   - **Database**: `travel_concierge`
   - **User**: `postgres`
   - **Region**: Choose the closest region (e.g., Oregon or Frankfurt).
   - **Instance Type**: Select **Free** (256 MB RAM, 1 GB storage, $0/month).
3. Click **Create Database**.
4. Once provisioned, copy the **Internal Database URL** (e.g. `postgres://postgres:...@.../travel_concierge`).

### Step 2.2: Create Free Redis (Key Value) Instance
1. Click **New +** > **Key Value** (Redis-compatible).
2. Set:
   - **Name**: `reroute-redis`
   - **Region**: Same region as your database.
   - **Instance Type**: Select **Free** (25 MB RAM, in-memory, $0/month).
3. Click **Create Key Value**.
4. Once provisioned, copy the **Internal Connection String** (e.g. `redis://red-...:6379`).

### Step 2.3: Deploy the Backend Web Service (Docker)
1. Click **New +** > **Web Service**.
2. Select **Build and deploy from a Git repository** and connect your GitHub repo `reroute`.
3. Set:
   - **Name**: `reroute-backend`
   - **Region**: Same region as database and Redis.
   - **Branch**: `main`
   - **Root Directory**: (Leave blank or `backend`)
   - **Runtime**: **Docker**
   - **Dockerfile Path**: `backend/Dockerfile`
   - **Docker Context**: `backend`
   - **Instance Type**: Select **Free** (0.1 CPU, 512 MB RAM, $0/month).
4. Scroll down to **Environment Variables** and add:

| Key | Value | Description | Secret? |
| :--- | :--- | :--- | :--- |
| `DATABASE_URL` | Paste your **Internal Database URL** | Auto-converted to asyncpg format | Yes |
| `REDIS_URL` | Paste your **Internal Redis URL** | Redis pub/sub messaging | Yes |
| `AUTO_SEED` | `true` | Creates tables & demo records if empty | No |
| `LLM_USAGE_STORE` | `db` | Persists call counts across restarts | No |
| `LLM_PROVIDER` | `google` | LLM vendor | No |
| `LLM_MODEL` | `gemini-3.5-flash-lite` | Free tier model | No |
| `GOOGLE_API_KEY` | Your Google AI Studio Key | Gemini API access | **YES** |
| `DEMO_API_KEY` | Choose a secret phrase (e.g., `reroute-demo-2026`) | Protects /events/simulate | **YES** |
| `LLM_HARD_DAILY_CALL_LIMIT` | `100` | Hard stop cap (80 calls = 80%) | No |
| `MAX_LLM_CALLS_PER_EVENT` | `6` | Guardrail per event | No |
| `DEBUG` | `false` | Production mode | No |
| `CORS_ORIGINS` | `*` (or your Vercel URL once known) | Frontend CORS | No |

5. Click **Create Web Service**.
6. When deployment finishes, note your public URL: `https://reroute-backend-xxxx.onrender.com`.

---

## 3. Vercel Deployment (Frontend Static Site)

Deploy the React dashboard to Vercel for free:

1. Go to [Vercel](https://vercel.com) and click **Add New...** > **Project**.
2. Import your GitHub repository `reroute`.
3. Configure Project Settings:
   - **Framework Preset**: `Vite`
   - **Root Directory**: Click *Edit* and select `frontend`.
   - **Build Command**: `npm run build` (default).
   - **Output Directory**: `dist` (default).
4. Under **Environment Variables**, add:
   - **Key**: `VITE_API_URL`
   - **Value**: `https://reroute-backend-xxxx.onrender.com` (your Render backend URL without trailing slash).
5. Click **Deploy**.
6. Once deployed, copy your frontend URL (e.g. `https://reroute-frontend.vercel.app`).
7. *(Optional)* Return to your Render backend service settings and set `CORS_ORIGINS` to `https://reroute-frontend.vercel.app` for strict security.

---

## 4. Run the Deployment Smoke Test

Verify your production deployment end-to-end:

```powershell
python scripts/smoke_test.py https://reroute-backend-xxxx.onrender.com your-demo-key
```

Expected output:
```text
=======================================================
 ReRoute Deployment Smoke Test
 Target: https://reroute-backend-xxxx.onrender.com
 Demo Key: [Configured]
=======================================================

[PASS] Step 1: /health -> 200 OK (status: healthy)
[PASS] Step 2: /metrics -> 200 OK (events=0, cost=₹0.0)
[PASS] Step 3: /events/simulate -> 200 OK (event_id=SIM-8A7B3C2D)
Waiting up to 90s for pipeline stages and final RESULT trace...
[PASS] Step 4: Event completed in 7.4s (action: REBOOKED, verdict: APPROVED)
       Stages reached: INGESTION -> DETECTION -> RETRIEVAL -> REVISION_1 -> VERIFICATION -> NOTIFICATION -> RESULT

>>> ALL SMOKE TESTS PASSED <<<
```

---

## 5. Free Plan Realities & Management

| Service | Free Limit | Behavior & Solution |
| :--- | :--- | :--- |
| **Render Web Service** | Inactive spindown | Free web services sleep after 15 min without requests. The next request takes 30-50 seconds to wake up (cold start). |
| **Optional Uptime Ping** | Keep-alive | To eliminate cold starts, set up a free 14-minute HTTP monitor (e.g. via [cron-job.org](https://cron-job.org) or [UptimeRobot](https://uptimerobot.com)) hitting `GET https://reroute-backend-xxxx.onrender.com/api/v1/health`. |
| **Render PostgreSQL** | 30-day lifespan | Free Render databases expire 30 days after creation. Render emails you before deletion. |
| **Recreating Database** | 2 clicks | When it expires, simply delete `reroute-postgres`, create a new one, and copy the new URL into `DATABASE_URL`. Because `AUTO_SEED=true`, the backend **automatically re-creates all tables and re-seeds the demo dataset on first boot**. |
| **Redis (Key Value)** | 25 MB RAM | In-memory only. ReRoute only uses Redis for real-time pub/sub event streaming, so no persistence is required. |
