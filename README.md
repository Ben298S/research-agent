# CUTIS Research Agent

A Flask-based research dashboard and Telegram bot for collecting public market signals around crepey skin and anti-aging skincare. It summarizes public search/review signals and can send reports to Telegram and Notion; Anthropic integration can draft ad-copy variations.

## Features

- Dashboard for viewing research summaries and triggering a run
- Telegram commands: `/research`, `/adcopy`, `/total`, and `/status`
- Research memory stored in `/tmp/brain.json` while the service instance is alive
- Optional integrations for SerpAPI, Notion, Meta Ad Library, and Anthropic
- Render deployment configuration in `render.yaml`

Treat search snippets as research leads, not verified claims. Collection depends on third-party APIs, availability, and terms.

## Local setup

1. Use Python 3.11 or a compatible deployment-supported version.
2. Create a virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   # Windows PowerShell: .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Set environment variables. `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are required by `app.py`. Start from `.env.example`, but keep real credentials in your shell or deployment secret manager—never commit them.
4. Start the app:

   ```bash
   flask --app app run
   ```

5. Endpoints:
   - `/` health check
   - `/dashboard?key=YOUR_PWA_SECRET` dashboard
   - `/api/data?key=YOUR_PWA_SECRET` dashboard data
   - `POST /run?key=YOUR_PWA_SECRET` trigger a research run

Use a long, random `PWA_SECRET` before exposing the app publicly.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Required Telegram bot token |
| `TELEGRAM_CHAT_ID` | Required default Telegram chat |
| `PWA_SECRET` | Secret for dashboard/research endpoints; set a strong random value |
| `SERPAPI_KEY` | Search-based collection |
| `NOTION_TOKEN` | Optional Notion integration |
| `NOTION_DB_ID` | Optional target Notion database |
| `META_ACCESS_TOKEN` | Optional Meta Ad Library integration |
| `ANTHROPIC_API_KEY` | Optional ad-copy generation |

## Deployment notes

- Configure secrets in Render environment settings, not in source files.
- The scheduled Render job in `render.yaml` calls the configured research endpoint daily; verify the service URL and schedule in your own Render project.
- Research memory is written to `/tmp/brain.json`. Ephemeral filesystems may reset this file after restarts; use persistent storage if history must survive deployments.

## Development checks

Run a syntax check locally:

```bash
python -m compileall -q app.py research_agent.py
```

GitHub Actions runs this check on pushes and pull requests. It checks Python syntax only; API integrations still require separate tests with valid credentials.
