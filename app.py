import os
import json
import logging
import requests
import threading
from datetime import datetime, timezone
from flask import Flask, request

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

app = Flask(__name__)


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(text: str, chat_id: str = None):
    cid = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chunk in [text[i:i+4096] for i in range(0, len(text), 4096)]:
        requests.post(url, data={"chat_id": cid, "text": chunk}, timeout=15)


# ── Reddit via SerpAPI ────────────────────────────────────────────────────────

def gather_reddit() -> list:
    queries = [
        "site:reddit.com crepey skin",
        'site:reddit.com "crepey skin" treatment',
        'site:reddit.com "crepey skin" anti-aging',
        'site:reddit.com/r/SkincareAddiction crepey skin',
        'site:reddit.com/r/antiaging crepey skin',
        'site:reddit.com/r/womenover50 crepey skin',
        'site:reddit.com/r/womenover40 crepey skin',
        'site:reddit.com/r/Frugal_Jerk saggy loose skin collagen',
        'site:reddit.com "turkey neck" treatment',
        'site:reddit.com "loose skin" collagen anti-aging',
    ]
    all_posts = []
    seen = set()
    for q in queries:
        try:
            r = requests.get("https://serpapi.com/search", params={
                "api_key": SERPAPI_KEY,
                "engine": "google",
                "q": q,
                "num": 10,
            }, timeout=15)
            r.raise_for_status()
            for result in r.json().get("organic_results", []):
                url = result.get("link", "")
                if not url or url in seen or "reddit.com" not in url:
                    continue
                seen.add(url)
                parts = url.split("/")
                sub = parts[4] if len(parts) > 4 and parts[3] == "r" else "reddit"
                all_posts.append({
                    "title": result.get("title", ""),
                    "url": url,
                    "subreddit": sub,
                    "body": result.get("snippet", "")[:400],
                })
        except Exception as e:
            log.warning(f"SerpAPI error '{q}': {e}")
    log.info(f"Reddit posts found: {len(all_posts)}")
    return all_posts


# ── Meta Ads ──────────────────────────────────────────────────────────────────

def get_meta_ads() -> dict:
    if not META_ACCESS_TOKEN:
        return {}
    results = {}
    for term in ["getcellu", "Happy Mammoth"]:
        try:
            r = requests.get(
                "https://graph.facebook.com/v19.0/ads_archive",
                params={
                    "access_token": META_ACCESS_TOKEN,
                    "search_terms": term,
                    "ad_reached_countries": ["US", "GB", "DE", "AU"],
                    "ad_type": "ALL",
                    "limit": 5,
                    "fields": "ad_creative_bodies,ad_creative_link_titles,ad_delivery_start_time,ad_snapshot_url,page_name",
                },
                timeout=15,
            )
            r.raise_for_status()
            results[term] = r.json().get("data", [])
        except Exception as e:
            results[term] = []
    return results


# ── Research & Message ────────────────────────────────────────────────────────

HOOK_KEYWORDS = [
    "why", "how", "stop", "finally", "secret", "fix", "help",
    "embarrassed", "hate", "ugly", "instantly", "overnight",
    "years younger", "anti-aging", "saggy", "loose", "collagen",
    "crepey", "crepe", "thin skin", "turkey neck",
]

def score_post(post: dict) -> int:
    text = (post["title"] + " " + post.get("body", "")).lower()
    return sum(20 for kw in HOOK_KEYWORDS if kw in text)

def run_research(chat_id: str = None):
    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    log.info("Starting research run...")

    reddit_posts = gather_reddit()
    meta_ads = get_meta_ads()

    lines = [f"Research Brief {today}\n"]

    lines.append("Reddit - Crepey Skin")
    if reddit_posts:
        for p in sorted(reddit_posts, key=score_post, reverse=True)[:8]:
            lines.append(f'* {p["title"][:90]}')
            lines.append(f'  r/{p["subreddit"]} | {p["url"]}')
            if p.get("body"):
                lines.append(f'  "{p["body"][:120]}"')
    else:
        lines.append("Keine Posts gefunden.")

    # Hooks
    hooks = []
    for p in sorted(reddit_posts, key=score_post, reverse=True)[:20]:
        if any(kw in p["title"].lower() for kw in ["how", "why", "stop", "finally", "secret", "fix", "help"]):
            hooks.append(p["title"])
        if len(hooks) >= 5:
            break
    if hooks:
        lines.append("\nTrending Hooks")
        for h in hooks:
            lines.append(f"  -> {h[:100]}")

    lines.append("\nMeta Ads - Cellu & Happy Mammoth")
    if meta_ads:
        for brand, ads in meta_ads.items():
            lines.append(f"\n{brand}: {len(ads)} Ad(s)")
            for ad in ads[:3]:
                copy = (ad.get("ad_creative_bodies") or []) + (ad.get("ad_creative_link_titles") or [])
                if copy:
                    lines.append(f'  "{copy[0][:150]}"')
                if ad.get("ad_snapshot_url"):
                    lines.append(f'  {ad["ad_snapshot_url"]}')
    else:
        lines.append("Kein Meta-Token konfiguriert.")

    lines.append(f"\n{len(reddit_posts)} Posts gescannt.")
    send_telegram("\n".join(lines), chat_id=chat_id)
    log.info("Research sent.")


# ── Telegram Webhook ──────────────────────────────────────────────────────────

@app.route(f"/webhook/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    msg = data.get("message", {})
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = msg.get("text", "").lower().strip()

    if not chat_id:
        return "ok"

    if text in ["/start", "/help"]:
        send_telegram(
            "Hallo! Befehle:\n/research - Sofort recherchieren\n/status - Status",
            chat_id=chat_id
        )
    elif text == "/research":
        send_telegram("Recherche gestartet... dauert ~30 Sek.", chat_id=chat_id)
        threading.Thread(target=run_research, args=(chat_id,), daemon=True).start()
    elif text == "/status":
        send_telegram("Bot lauft. Täglich um 10:00 Uhr CEST.", chat_id=chat_id)
    else:
        send_telegram("Nutze /research für eine sofortige Recherche.", chat_id=chat_id)

    return "ok"


@app.route("/run", methods=["GET", "POST"])
def run_endpoint():
    """Called by Render cron job daily at 10am."""
    threading.Thread(target=run_research, daemon=True).start()
    return "Research started", 200


@app.route("/")
def health():
    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
