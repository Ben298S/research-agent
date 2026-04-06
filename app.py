import os
import json
import logging
import requests
import threading
from datetime import datetime, timezone
from flask import Flask, request
from collections import Counter

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")

BRAIN_FILE = "/tmp/brain.json"

app = Flask(__name__)


# ── Gehirn (persistentes Lernen) ──────────────────────────────────────────────

def load_brain() -> dict:
    try:
        with open(BRAIN_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "sessions": 0,
            "desires": [],
            "problems": [],
            "language": [],
            "hooks": [],
            "top_posts": [],
        }

def save_brain(brain: dict):
    try:
        with open(BRAIN_FILE, "w") as f:
            json.dump(brain, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"Brain save error: {e}")

def update_brain(brain: dict, posts: list, amazon_posts: list):
    """Extrahiert Learnings aus Posts und fügt sie ins Gehirn ein."""
    all_posts = posts + amazon_posts

    DESIRE_KEYWORDS = [
        "want", "wish", "hope", "looking for", "trying to", "want to",
        "would love", "dream", "goal", "finally", "need something",
        "suche", "wünsche", "möchte", "will", "hoffe", "träume", "brauche",
    ]
    PROBLEM_KEYWORDS = [
        "hate", "embarrassed", "struggle", "frustrated", "cant", "can't",
        "doesn't work", "tried everything", "nothing works", "worse",
        "hasse", "peinlich", "frustriert", "nichts hilft", "verzweifelt",
        "schlimmer", "geht nicht", "funktioniert nicht",
    ]
    LANGUAGE_SNIPPETS = []
    NEW_HOOKS = []

    for p in all_posts:
        text = p["title"] + " " + p.get("body", "")
        lower = text.lower()

        # Desires
        for kw in DESIRE_KEYWORDS:
            if kw in lower:
                snippet = p["title"][:120]
                if snippet not in brain["desires"]:
                    brain["desires"].append(snippet)
                break

        # Problems
        for kw in PROBLEM_KEYWORDS:
            if kw in lower:
                snippet = p["title"][:120]
                if snippet not in brain["problems"]:
                    brain["problems"].append(snippet)
                break

        # Kundensprache – Zitate aus Body
        body = p.get("body", "")
        if len(body) > 40:
            quote = body[:150].strip()
            if quote not in brain["language"]:
                LANGUAGE_SNIPPETS.append(quote)

        # Hooks
        if any(kw in lower for kw in ["how", "why", "stop", "finally", "secret", "fix", "help",
                                        "wie", "warum", "endlich", "geheimnis"]):
            h = p["title"][:120]
            if h not in brain["hooks"]:
                NEW_HOOKS.append(h)

    # Nur neue hinzufügen
    brain["language"] = (brain["language"] + LANGUAGE_SNIPPETS)[-200:]
    brain["hooks"] = (brain["hooks"] + NEW_HOOKS)[-100:]
    brain["desires"] = brain["desires"][-100:]
    brain["problems"] = brain["problems"][-100:]

    # Top Posts (nach Score)
    for p in sorted(all_posts, key=score_post, reverse=True)[:3]:
        entry = {"title": p["title"][:120], "url": p.get("url", ""), "source": p.get("source", "reddit")}
        if entry not in brain["top_posts"]:
            brain["top_posts"].append(entry)
    brain["top_posts"] = brain["top_posts"][-50:]

    brain["sessions"] += 1
    brain["last_update"] = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M")
    return brain


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(text: str, chat_id: str = None):
    cid = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chunk in [text[i:i+4096] for i in range(0, len(text), 4096)]:
        requests.post(url, data={"chat_id": cid, "text": chunk, "parse_mode": "HTML"}, timeout=15)


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
        'site:reddit.com "turkey neck" treatment',
        'site:reddit.com "loose skin" collagen anti-aging',
        'site:reddit.com "saggy skin" fix',
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
                    "source": "reddit",
                })
        except Exception as e:
            log.warning(f"SerpAPI Reddit error '{q}': {e}")
    log.info(f"Reddit posts found: {len(all_posts)}")
    return all_posts


# ── Amazon Reviews via SerpAPI ────────────────────────────────────────────────

def gather_amazon() -> list:
    queries = [
        'site:amazon.com "crepey skin" review',
        'site:amazon.com "loose skin" collagen review',
        'site:amazon.com "saggy skin" anti-aging review',
        'site:amazon.com "turkey neck" cream review',
        'site:amazon.com "skin tightening" supplement review',
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
                if not url or url in seen or "amazon.com" not in url:
                    continue
                seen.add(url)
                all_posts.append({
                    "title": result.get("title", ""),
                    "url": url,
                    "subreddit": "amazon",
                    "body": result.get("snippet", "")[:400],
                    "source": "amazon",
                })
        except Exception as e:
            log.warning(f"SerpAPI Amazon error '{q}': {e}")
    log.info(f"Amazon posts found: {len(all_posts)}")
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


# ── Hook Scoring ──────────────────────────────────────────────────────────────

HOOK_KEYWORDS = [
    "why", "how", "stop", "finally", "secret", "fix", "help",
    "embarrassed", "hate", "ugly", "instantly", "overnight",
    "years younger", "anti-aging", "saggy", "loose", "collagen",
    "crepey", "crepe", "thin skin", "turkey neck",
    "wie", "warum", "endlich", "peinlich", "hasse", "sofort",
    "schlaffes", "hängende", "kollagen", "straffen",
]

def score_post(post: dict) -> int:
    text = (post["title"] + " " + post.get("body", "")).lower()
    return sum(20 for kw in HOOK_KEYWORDS if kw in text)


# ── Research Run ──────────────────────────────────────────────────────────────

def run_research(chat_id: str = None):
    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    log.info("Starting research run...")

    reddit_posts = gather_reddit()
    amazon_posts = gather_amazon()
    meta_ads = get_meta_ads()
    all_posts = reddit_posts + amazon_posts

    # Gehirn updaten
    brain = load_brain()
    brain = update_brain(brain, reddit_posts, amazon_posts)
    save_brain(brain)

    lines = [f"<b>Research Brief {today}</b>\n"]

    # Reddit
    lines.append("<b>Reddit — Crepey Skin</b>")
    if reddit_posts:
        for p in sorted(reddit_posts, key=score_post, reverse=True)[:6]:
            lines.append(f'• <a href="{p["url"]}">{p["title"][:90]}</a>')
            lines.append(f'  └ r/{p["subreddit"]}')
            if p.get("body"):
                lines.append(f'  └ "{p["body"][:120]}"')

        # Desires aus Reddit
        r_desires = [p["title"][:120] for p in reddit_posts
                     if any(kw in (p["title"]+" "+p.get("body","")).lower()
                            for kw in ["want","wish","hope","looking for","trying to","would love","finally","need"])][:4]
        if r_desires:
            lines.append("\n💚 <b>Desires:</b>")
            for d in r_desires:
                lines.append(f"  • {d}")

        # Probleme aus Reddit
        r_problems = [p["title"][:120] for p in reddit_posts
                      if any(kw in (p["title"]+" "+p.get("body","")).lower()
                             for kw in ["hate","embarrassed","struggle","frustrated","can't","nothing works","tried everything","worse"])][:4]
        if r_problems:
            lines.append("\n😤 <b>Probleme:</b>")
            for p in r_problems:
                lines.append(f"  • {p}")

        # Kundensprache O-Ton
        r_lang = [p["body"][:150] for p in reddit_posts if len(p.get("body","")) > 40][:3]
        if r_lang:
            lines.append("\n💬 <b>Kundensprache:</b>")
            for l in r_lang:
                lines.append(f'  "{l}"')
    else:
        lines.append("Keine Posts gefunden.")

    # Amazon Reviews
    lines.append("\n<b>Amazon Reviews — Kundenstimmen</b>")
    if amazon_posts:
        for p in sorted(amazon_posts, key=score_post, reverse=True)[:4]:
            lines.append(f'• <a href="{p["url"]}">{p["title"][:90]}</a>')
            if p.get("body"):
                lines.append(f'  └ "{p["body"][:120]}"')
    else:
        lines.append("Keine Reviews gefunden.")

    # Hooks
    hooks = []
    for p in sorted(all_posts, key=score_post, reverse=True)[:20]:
        if any(kw in p["title"].lower() for kw in ["how", "why", "stop", "finally", "secret", "fix",
                                                     "wie", "warum", "endlich", "geheimnis"]):
            hooks.append(p["title"])
        if len(hooks) >= 5:
            break
    if hooks:
        lines.append("\n<b>Trending Hooks</b>")
        for h in hooks:
            lines.append(f"  → {h[:100]}")

    # Meta Ads
    lines.append("\n<b>Meta Ads — Cellu &amp; Happy Mammoth</b>")
    if meta_ads:
        for brand, ads in meta_ads.items():
            lines.append(f"\n<b>{brand}</b>: {len(ads)} Ad(s)")
            for ad in ads[:3]:
                copy = (ad.get("ad_creative_bodies") or []) + (ad.get("ad_creative_link_titles") or [])
                if copy:
                    lines.append(f'  "{copy[0][:150]}"')
                if ad.get("ad_snapshot_url"):
                    lines.append(f'  🔗 {ad["ad_snapshot_url"]}')
    else:
        lines.append("Kein Meta-Token konfiguriert.")

    # Was ich heute gelernt habe
    lines.append(f"\n<b>Was ich heute gelernt habe (Session #{brain['sessions']})</b>")

    new_desires = [d for d in brain["desires"][-5:]]
    new_problems = [p for p in brain["problems"][-5:]]
    new_lang = [l for l in brain["language"][-3:]]

    if new_desires:
        lines.append("\n💚 <b>Kundenwünsche:</b>")
        for d in new_desires:
            lines.append(f"  • {d}")
    if new_problems:
        lines.append("\n😤 <b>Probleme &amp; Frustrationen:</b>")
        for p in new_problems:
            lines.append(f"  • {p}")
    if new_lang:
        lines.append("\n💬 <b>Kundensprache (O-Ton):</b>")
        for l in new_lang:
            lines.append(f'  "{l}"')

    lines.append(f"\n📊 {len(all_posts)} Posts gescannt | Gehirn hat {brain['sessions']} Sessions gelernt")

    send_telegram("\n".join(lines), chat_id=chat_id)
    log.info("Research sent.")


# ── /total Kommando ───────────────────────────────────────────────────────────

def send_total(chat_id: str):
    brain = load_brain()

    if brain["sessions"] == 0:
        send_telegram("Das Gehirn ist noch leer. Starte /research um zu lernen!", chat_id=chat_id)
        return

    lines = [f"<b>Gesammeltes Wissen — {brain['sessions']} Sessions</b>"]
    lines.append(f"<i>Letztes Update: {brain.get('last_update', 'unbekannt')}</i>\n")

    if brain["desires"]:
        lines.append("<b>💚 Kundenwünsche (was sie wollen):</b>")
        for d in brain["desires"][-15:]:
            lines.append(f"  • {d}")

    if brain["problems"]:
        lines.append("\n<b>😤 Probleme &amp; Frustrationen:</b>")
        for p in brain["problems"][-15:]:
            lines.append(f"  • {p}")

    if brain["language"]:
        lines.append("\n<b>💬 Kundensprache (O-Töne):</b>")
        for l in brain["language"][-10:]:
            lines.append(f'  "{l}"')

    if brain["hooks"]:
        lines.append("\n<b>🔥 Bewährte Hook-Ideen:</b>")
        for h in brain["hooks"][-15:]:
            lines.append(f"  → {h}")

    if brain["top_posts"]:
        lines.append("\n<b>⭐ Top Posts aller Zeit:</b>")
        for p in brain["top_posts"][-10:]:
            src = p.get("source", "")
            lines.append(f'  • [{src}] <a href="{p["url"]}">{p["title"][:80]}</a>')

    send_telegram("\n".join(lines), chat_id=chat_id)


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
            "Hallo! Befehle:\n"
            "/research — Sofort recherchieren\n"
            "/total — Alles was ich gelernt habe\n"
            "/status — Bot Status",
            chat_id=chat_id
        )
    elif text == "/research":
        send_telegram("Recherche gestartet... dauert ~45 Sek.", chat_id=chat_id)
        threading.Thread(target=run_research, args=(chat_id,), daemon=True).start()
    elif text == "/total":
        threading.Thread(target=send_total, args=(chat_id,), daemon=True).start()
    elif text == "/status":
        brain = load_brain()
        send_telegram(
            f"Bot läuft ✅\n"
            f"Gehirn: {brain['sessions']} Sessions gelernt\n"
            f"Desires: {len(brain['desires'])} | Probleme: {len(brain['problems'])}\n"
            f"Hooks: {len(brain['hooks'])} | Sprach-Snippets: {len(brain['language'])}\n"
            f"Täglich um 10:00 Uhr (DE)",
            chat_id=chat_id
        )
    else:
        send_telegram("Nutze /research, /total oder /status", chat_id=chat_id)

    return "ok"


@app.route("/run", methods=["GET", "POST"])
def run_endpoint():
    threading.Thread(target=run_research, daemon=True).start()
    return "Research started", 200


@app.route("/")
def health():
    return "OK", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
