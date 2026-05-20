# ContentMatrix OS — Deployment Guide

How to push this engine to GitHub and run it on Streamlit Cloud — same
pattern as `topical-map-engine-pro` and `topical_map_engine`.

---

## Prerequisites

- GitHub account (free)
- Streamlit Cloud account at https://share.streamlit.io (free, sign in with GitHub)
- API keys: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `SERPER_API_KEY`
- Git installed locally (`git --version` should work)

---

## Step 1 — Create the GitHub Repository

### Option A: GitHub web UI (easiest)

1. Go to https://github.com/new
2. Repository name: `content-creation-engine`
3. Visibility: **Private** (recommended — contains your prompts and IP)
4. **Do NOT** check "Add a README" or "Add .gitignore" — we already have those
5. Click **Create repository**
6. Copy the URL shown (e.g. `https://github.com/yourname/content-creation-engine.git`)

### Option B: GitHub CLI

```bash
cd "C:\Users\ALPHA TECH\OneDrive\Desktop\content-creation-engine"
gh repo create content-creation-engine --private --source=. --remote=origin
```

---

## Step 2 — Push the Code

```powershell
cd "C:\Users\ALPHA TECH\OneDrive\Desktop\content-creation-engine"

# Initialize and stage
git init
git add .

# Verify .env is NOT being committed (should be in .gitignore)
git status | Select-String -Pattern "\.env$"
# If you see ".env" in the output, STOP — fix .gitignore before continuing.

# Commit
git commit -m "Initial scaffold: content creation engine v0.1"

# Connect remote and push
git branch -M main
git remote add origin https://github.com/YOURNAME/content-creation-engine.git
git push -u origin main
```

If `git push` asks for credentials, use a **Personal Access Token**, not your
GitHub password. Create one at https://github.com/settings/tokens (scope: `repo`).

---

## Step 3 — Verify the Push

Open `https://github.com/YOURNAME/content-creation-engine` and confirm you see:

- `app.py`, `pipeline.py`, `content_models.py`
- `stages/`, `ui/`, `prompts/`, `templates/`, `examples/` folders
- `requirements.txt`, `runtime.txt`, `README.md`
- **NO `.env` file** (only `.env.example`)
- **NO `cache/*.db`** or `sessions/*` content (only `.gitkeep`)

If anything sensitive leaked, follow the "Remove leaked secrets" section below
before going further.

---

## Step 4 — Connect to Streamlit Cloud

1. Go to https://share.streamlit.io
2. Click **New app**
3. Configure:
   - **Repository**: `YOURNAME/content-creation-engine`
   - **Branch**: `main`
   - **Main file path**: `app.py`
   - **App URL**: pick a slug, e.g. `cge-yourname` -> `cge-yourname.streamlit.app`
4. Click **Advanced settings** -> **Python version**: `3.11` (matches `runtime.txt`)
5. Click **Deploy**

First deploy takes 3-5 minutes. You will see install logs in real time.

---

## Step 5 — Add API Keys as Secrets

While the app is deploying (or after it boots and shows "secrets missing"):

1. Open your app on Streamlit Cloud
2. Click the three-dot menu (top right) -> **Settings** -> **Secrets**
3. Paste:

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
GEMINI_API_KEY    = "..."
SERPER_API_KEY    = "..."

# Optional — leave empty if not using Turso
TURSO_DATABASE_URL = ""
TURSO_AUTH_TOKEN   = ""
```

4. Click **Save**
5. The app auto-restarts. The keys are now available as `os.environ[...]`.

---

## Step 6 — Verify the App Works

1. Open `https://cge-yourname.streamlit.app`
2. You should see the dark home screen
3. Go to **Upload** tab
4. Try the **Manual form** tab — fill in any niche and click "Use this minimal brief"
5. Go to **Generate** -> enable **Dry run** -> click "Generate article"
6. Should complete in seconds with placeholder content + a real score

If dry run works, your scaffold is healthy. Now test with **Dry run OFF**:
should make real LLM calls and produce real content.

---

## Step 7 — Connect to the Topical Map Engine (Optional)

Currently the `Upload -> From topical-map-engine session` tab expects a local
folder path. On Streamlit Cloud there is no local `topical-map-engine-pro`
folder, so you have three options:

**Option 1**: Upload the `topical_map.json` + `all_briefs.json` via the
**Upload JSON** tab (wrap them into a `ContentEngineInput` JSON — see
`examples/example_input.json`).

**Option 2**: Push both engines into a single mono-repo, then point the
`session_root` path to the sibling folder.

**Option 3** (recommended for the long run): Add a small "Pull from URL"
feature — paste the GitHub raw URL of the session JSONs. (Not built yet.)

---

## Subsequent Deploys

Streamlit Cloud auto-deploys on every push to `main`. Workflow:

```powershell
cd "C:\Users\ALPHA TECH\OneDrive\Desktop\content-creation-engine"
git add .
git commit -m "Phase 2A: section writer wired to real LLM"
git push
```

Wait ~60 seconds and the live app reflects the change.

---

## Local Development

```powershell
cd "C:\Users\ALPHA TECH\OneDrive\Desktop\content-creation-engine"

# One-time setup
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env — paste your API keys

# Run
streamlit run app.py
```

App opens at `http://localhost:8501`.

---

## Streamlit Cloud Free Tier Limits

- **1 GB** RAM
- **800 MB** disk (ephemeral — wiped on app sleep/restart)
- App sleeps after 7 days of inactivity (auto-wakes on visit)
- 3 public apps OR unlimited private apps

The SQLite cache lives in `cache/engine_cache.db` — **it gets wiped on every
restart** in the free tier. For persistent cache, either:

- Upgrade to a paid tier ($20/mo, persistent disk)
- Use Turso cloud SQLite (free 9 GB) — swap `_conn()` in `stages/cache.py`
- Commit the cache to a private GitHub repo periodically (cron worker)

For Phase 2A this is fine — first run is uncached, second run within the
same session is cached, and articles are saved to `sessions/` (also ephemeral
but downloadable from the UI).

---

## Common Issues

### "ModuleNotFoundError: No module named 'X'"
- `requirements.txt` is missing the package. Add it, commit, push.

### "ANTHROPIC_API_KEY not set"
- The key is missing in Streamlit Cloud Secrets. Re-check Step 5.

### "Serper returned HTTP 429"
- You hit the 1000/month free limit. Either wait or upgrade.

### App stuck on "Your app is in the oven..."
- Check the deploy logs (Manage app -> Logs). Usually a missing dependency.

### Cache file growing too large
- Run `cache.purge_expired()` from a small admin button, or just delete
  `cache/engine_cache.db` on restart.

---

## Remove Leaked Secrets (Emergency)

If you accidentally pushed `.env` or API keys to GitHub:

1. **Rotate the keys immediately** — go to each provider's dashboard and
   revoke + regenerate. Assume the leaked key is compromised forever.
2. Add `.env` to `.gitignore` (already there in this repo).
3. Remove from git history:
   ```bash
   git rm --cached .env
   git commit -m "Remove .env from tracking"
   git push
   ```
   This stops tracking but the key is still in history. For full history
   rewrite, use `git filter-repo` (advanced — see GitHub docs).
4. If the repo is public, make it **private** immediately.

---

## Production Checklist

Before sharing the live app with clients:

- [ ] Repo is **Private**
- [ ] `.env` is in `.gitignore` and not in the repo
- [ ] API keys are set in Streamlit Cloud Secrets
- [ ] Dry-run end-to-end works
- [ ] Real LLM end-to-end works (test with cheapest model first)
- [ ] Cost tracker shows reasonable cost per article (<$0.50 for 2k words)
- [ ] You have a backup plan for cache loss (acceptable for now)
- [ ] You have set a model fallback strategy (e.g. Sonnet fails -> Haiku)
