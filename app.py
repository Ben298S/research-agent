import os
import re
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
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DB_ID = os.environ.get("NOTION_DB_ID", "6471286176f84407849480f3defa781")
PWA_SECRET = os.environ.get("PWA_SECRET", "cutis-research-2024")

BRAIN_FILE = "/tmp/brain.json"
app = Flask(__name__)

last_research_cache: dict = {}


def write_to_notion(data):
    if not NOTION_TOKEN:
        log.warning("NOTION_TOKEN not set")
        return
    try:
        headers = {
            "Authorization": "Bearer " + NOTION_TOKEN,
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        today_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
        today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        def h2(t):
            return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": t}}]}}
        def h3(t):
            return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": t}}]}}
        def bullet(t):
            return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": t[:2000]}}]}}
        def quote(t):
            return {"object": "block", "type": "quote", "quote": {"rich_text": [{"type": "text", "text": {"content": t[:2000]}}]}}
        def divider():
            return {"object": "block", "type": "divider", "divider": {}}

        children = []
        children.append(h2("\U0001f50d Reddit \u2014 Crepey Skin"))
        for p in data.get("reddit_top", [])[:10]:
            children.append(bullet("r/" + p.get("subreddit", "reddit") + " \u00b7 " + p["title"][:150]))
            if p.get("body"):
                children.append(quote(p["body"][:300]))
        if data.get("desires"):
            children.append(divider())
            children.append(h3("\U0001f49a Desires \u2014 Was sie wollen"))
            for d in data["desires"][:6]:
                children.append(bullet(d))
        if data.get("problems"):
            children.append(h3("\U0001f624 Frustrationen \u2014 Was sie nervt"))
            for p in data["problems"][:6]:
                children.append(bullet(p))
        if data.get("language"):
            children.append(h3("\U0001f4ac Kundensprache O-T\u00f6ne"))
            for l in data["language"][:5]:
                children.append(quote(l))
        children.append(divider())
        children.append(h2("\U0001f6d2 Amazon Reviews"))
        for p in data.get("amazon_top", [])[:8]:
            children.append(bullet(p["title"][:150]))
            if p.get("body"):
                children.append(quote(p["body"][:300]))
        if data.get("hooks"):
            children.append(divider())
            children.append(h2("\U0001f525 Trending Hooks"))
            for h in data["hooks"][:8]:
                children.append(bullet("\u2192 " + h[:150]))
        brain = data.get("brain", {})
        if brain:
            children.append(divider())
            children.append(h2("\U0001f9e0 Brain Session #" + str(brain.get("sessions", 0))))
            for d in brain.get("desires", [])[-5:]:
                children.append(bullet("\U0001f49a " + d))
            for p in brain.get("problems", [])[-5:]:
                children.append(bullet("\U0001f624 " + p))
            for l in brain.get("language", [])[-3:]:
                children.append(quote(l))
        if data.get("trustpilot"):
            children.append(divider())
            children.append(h2("\u2b50 Trustpilot \u2014 Konkurrenz Reviews"))
            for p in data["trustpilot"][:6]:
                children.append(bullet(p["title"][:150]))
                if p.get("body"):
                    children.append(quote(p["body"][:300]))
        children.append(divider())
        children.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {
                "content": "\U0001f4ca " + str(data.get("total_posts", 0)) + " Posts gescannt \u00b7 Gehirn: " + str(brain.get("sessions", 0)) + " Sessions"
            }, "annotations": {"italic": True}}]}
        })

        payload = {
            "parent": {"database_id": NOTION_DB_ID},
            "icon": {"type": "emoji", "emoji": "\U0001f4ca"},
            "properties": {
                "Titel": {"title": [{"type": "text", "text": {"content": "Research Brief " + today_str}}]},
                "Datum": {"date": {"start": today_iso}},
                "Quellen": {"number": data.get("total_posts", 0)},
                "Brain Sessions": {"number": brain.get("sessions", 0)},
                "Status": {"select": {"name": "\U0001f195 Neu"}},
                "Desires gefunden": {"number": len(data.get("desires", []))},
                "Probleme gefunden": {"number": len(data.get("problems", []))},
                "Hooks gefunden": {"number": len(data.get("hooks", []))},
            },
            "children": children[:100],
        }
        r = requests.post("https://api.notion.com/v1/pages", headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        log.info("Notion page created.")
    except Exception as e:
        log.warning("Notion error: " + str(e))


def load_brain():
    try:
        with open(BRAIN_FILE) as f:
            return json.load(f)
    except Exception:
        return {"sessions": 0, "desires": [], "problems": [], "language": [], "hooks": [], "top_posts": []}

def save_brain(brain):
    try:
        with open(BRAIN_FILE, "w") as f:
            json.dump(brain, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning("Brain save error: " + str(e))

HOOK_KEYWORDS = [
    "why", "how", "stop", "finally", "secret", "fix", "help",
    "embarrassed", "hate", "ugly", "instantly", "overnight",
    "years younger", "anti-aging", "saggy", "loose", "collagen",
    "crepey", "crepe", "thin skin", "turkey neck",
    "wie", "warum", "endlich", "peinlich", "hasse", "sofort",
    "schlaffes", "haengende", "kollagen", "straffen",
]

def score_post(post):
    text = (post["title"] + " " + post.get("body", "")).lower()
    return sum(20 for kw in HOOK_KEYWORDS if kw in text)

def update_brain(brain, posts, amazon_posts):
    all_posts = posts + amazon_posts
    DESIRE_KW = ["want", "wish", "hope", "looking for", "trying to", "would love", "finally", "need",
                 "suche", "wuensche", "moechte", "hoffe", "traeume", "brauche"]
    PROBLEM_KW = ["hate", "embarrassed", "struggle", "frustrated", "can't", "nothing works",
                  "tried everything", "worse", "hasse", "peinlich", "frustriert",
                  "nichts hilft", "verzweifelt", "schlimmer", "geht nicht"]
    HOOK_KW = ["how", "why", "stop", "finally", "secret", "fix", "help",
               "wie", "warum", "endlich", "geheimnis"]
    new_lang, new_hooks = [], []
    for p in all_posts:
        text = p["title"] + " " + p.get("body", "")
        lower = text.lower()
        for kw in DESIRE_KW:
            if kw in lower:
                s = p["title"][:120]
                if s not in brain["desires"]:
                    brain["desires"].append(s)
                break
        for kw in PROBLEM_KW:
            if kw in lower:
                s = p["title"][:120]
                if s not in brain["problems"]:
                    brain["problems"].append(s)
                break
        body = p.get("body", "")
        if len(body) > 40:
            q = body[:150].strip()
            if q not in brain["language"]:
                new_lang.append(q)
        if any(kw in lower for kw in HOOK_KW):
            h = p["title"][:120]
            if h not in brain["hooks"]:
                new_hooks.append(h)
    brain["language"] = (brain["language"] + new_lang)[-200:]
    brain["hooks"] = (brain["hooks"] + new_hooks)[-100:]
    brain["desires"] = brain["desires"][-100:]
    brain["problems"] = brain["problems"][-100:]
    for p in sorted(all_posts, key=score_post, reverse=True)[:3]:
        entry = {"title": p["title"][:120], "url": p.get("url", ""), "source": p.get("source", "reddit")}
        if entry not in brain["top_posts"]:
            brain["top_posts"].append(entry)
    brain["top_posts"] = brain["top_posts"][-50:]
    brain["sessions"] += 1
    brain["last_update"] = datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M")
    return brain


def send_telegram(text, chat_id=None):
    cid = chat_id or TELEGRAM_CHAT_ID
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage"
    for chunk in [text[i:i+4096] for i in range(0, len(text), 4096)]:
        requests.post(url, data={"chat_id": cid, "text": chunk, "parse_mode": "HTML"}, timeout=15)


def gather_reddit():
    queries = [
        "site:reddit.com crepey skin",
        "site:reddit.com crepey skin treatment",
        "site:reddit.com crepey skin anti-aging",
        "site:reddit.com crepey skin before after",
        "site:reddit.com crepey skin what worked",
        "site:reddit.com/r/SkincareAddiction crepey skin",
        "site:reddit.com/r/antiaging crepey skin",
        "site:reddit.com/r/womenover50 crepey skin",
        "site:reddit.com/r/womenover40 crepey skin",
        "site:reddit.com/r/30PlusSkinCare crepey skin",
        "site:reddit.com/r/femalefashionadvice crepey skin",
        "site:reddit.com turkey neck treatment",
        "site:reddit.com turkey neck fix",
        "site:reddit.com loose skin collagen anti-aging",
        "site:reddit.com saggy skin fix",
        "site:reddit.com skin tightening over 50",
        "site:reddit.com collagen loss skin",
        "site:reddit.com thin skin aging women",
    ]
    all_posts, seen = [], set()
    for q in queries:
        try:
            r = requests.get("https://serpapi.com/search",
                             params={"api_key": SERPAPI_KEY, "engine": "google", "q": q, "num": 15},
                             timeout=20)
            r.raise_for_status()
            for res in r.json().get("organic_results", []):
                url = res.get("link", "")
                if not url or url in seen or "reddit.com" not in url:
                    continue
                seen.add(url)
                parts = url.split("/")
                sub = parts[4] if len(parts) > 4 and parts[3] == "r" else "reddit"
                all_posts.append({
                    "title": res.get("title", ""), "url": url, "subreddit": sub,
                    "body": res.get("snippet", "")[:500], "source": "reddit",
                })
        except Exception as e:
            log.warning("Reddit error: " + str(e))
    log.info("Reddit posts: " + str(len(all_posts)))
    return all_posts


def gather_trustpilot():
    queries = [
        'site:trustpilot.com "getcellu"',
        'site:trustpilot.com "Happy Mammoth"',
        'site:trustpilot.com "crepey skin" cream',
        'site:trustpilot.com "skin tightening" collagen',
        'site:trustpilot.com "anti-aging" skin supplement',
    ]
    all_reviews, seen = [], set()
    for q in queries:
        try:
            r = requests.get("https://serpapi.com/search",
                             params={"api_key": SERPAPI_KEY, "engine": "google", "q": q, "num": 5},
                             timeout=20)
            r.raise_for_status()
            for res in r.json().get("organic_results", []):
                url = res.get("link", "")
                if not url or url in seen or "trustpilot.com" not in url:
                    continue
                seen.add(url)
                all_reviews.append({
                    "title": res.get("title", ""), "url": url,
                    "body": res.get("snippet", "")[:400], "source": "trustpilot",
                })
        except Exception as e:
            log.warning("Trustpilot error: " + str(e))
    log.info("Trustpilot reviews: " + str(len(all_reviews)))
    return all_reviews


def gather_amazon():
    queries = [
        "site:amazon.com crepey skin review",
        "site:amazon.com loose skin collagen review",
        "site:amazon.com saggy skin anti-aging review",
        "site:amazon.com turkey neck cream review",
        "site:amazon.com skin tightening supplement review",
        "site:amazon.com crepey skin serum review",
        "site:amazon.com skin firming over 50 review",
        "site:amazon.com collagen supplement skin review",
    ]
    all_posts, seen = [], set()
    for q in queries:
        try:
            r = requests.get("https://serpapi.com/search",
                             params={"api_key": SERPAPI_KEY, "engine": "google", "q": q, "num": 15},
                             timeout=20)
            r.raise_for_status()
            for res in r.json().get("organic_results", []):
                url = res.get("link", "")
                if not url or url in seen or "amazon.com" not in url:
                    continue
                seen.add(url)
                all_posts.append({
                    "title": res.get("title", ""), "url": url, "subreddit": "amazon",
                    "body": res.get("snippet", "")[:500], "source": "amazon",
                })
        except Exception as e:
            log.warning("Amazon error: " + str(e))
    log.info("Amazon posts: " + str(len(all_posts)))
    return all_posts


def run_research(chat_id=None):
    global last_research_cache
    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    log.info("Starting research run...")
    reddit_posts = gather_reddit()
    amazon_posts = gather_amazon()
    trustpilot_reviews = gather_trustpilot()
    all_posts = reddit_posts + amazon_posts
    brain = load_brain()
    brain = update_brain(brain, reddit_posts, amazon_posts)
    save_brain(brain)

    DESIRE_KW = ["want", "wish", "hope", "looking for", "trying to", "would love", "finally", "need"]
    PROBLEM_KW = ["hate", "embarrassed", "struggle", "frustrated", "can't", "nothing works", "tried everything", "worse"]
    HOOK_KW = ["how", "why", "stop", "finally", "secret", "fix", "wie", "warum", "endlich", "geheimnis"]

    desires = [p["title"][:120] for p in reddit_posts
               if any(kw in (p["title"] + " " + p.get("body", "")).lower() for kw in DESIRE_KW)][:6]
    problems = [p["title"][:120] for p in reddit_posts
                if any(kw in (p["title"] + " " + p.get("body", "")).lower() for kw in PROBLEM_KW)][:6]
    language = [p["body"][:200] for p in reddit_posts if len(p.get("body", "")) > 40][:5]
    hooks = []
    for p in sorted(all_posts, key=score_post, reverse=True)[:30]:
        if any(kw in p["title"].lower() for kw in HOOK_KW):
            hooks.append(p["title"])
            if len(hooks) >= 8:
                break

    notion_data = {
        "reddit_top": sorted(reddit_posts, key=score_post, reverse=True)[:12],
        "amazon_top": sorted(amazon_posts, key=score_post, reverse=True)[:8],
        "trustpilot": trustpilot_reviews,
        "desires": desires, "problems": problems, "language": language,
        "hooks": hooks, "total_posts": len(all_posts), "brain": brain,
    }

    lines = ["<b>Research Brief " + today + "</b>\n"]
    lines.append("<b>Reddit \u2014 Crepey Skin</b>")
    for p in notion_data["reddit_top"][:12]:
        lines.append("\u2022 " + p["title"][:100])
        lines.append("  \u2514 r/" + p["subreddit"])
        if p.get("body"):
            lines.append("  \u2514 \"" + p["body"][:200] + "\"")
    if desires:
        lines.append("\n\U0001f49a <b>Desires:</b>")
        for d in desires:
            lines.append("  \u2022 " + d)
    if problems:
        lines.append("\n\U0001f624 <b>Probleme:</b>")
        for p in problems:
            lines.append("  \u2022 " + p)
    if language:
        lines.append("\n\U0001f4ac <b>Kundensprache:</b>")
        for l in language:
            lines.append("  \"" + l + "\"")
    lines.append("\n<b>Amazon Reviews</b>")
    for p in notion_data["amazon_top"][:8]:
        lines.append("\u2022 " + p["title"][:100])
        if p.get("body"):
            lines.append("  \u2514 \"" + p["body"][:200] + "\"")
    if hooks:
        lines.append("\n<b>Trending Hooks</b>")
        for h in hooks:
            lines.append("  \u2192 " + h[:120])
    lines.append("\n\U0001f4ca " + str(len(all_posts)) + " Posts \u00b7 Session #" + str(brain["sessions"]) + " \u00b7 Notion \u2705")

    if trustpilot_reviews:
        lines.append("\n\u2b50 <b>Trustpilot \u2014 Konkurrenz</b>")
        for p in trustpilot_reviews[:4]:
            lines.append("\u2022 " + p["title"][:100])
            if p.get("body"):
                lines.append("  \u2514 \"" + p["body"][:150] + "\"")

    lines.append("\n\U0001f4ca " + str(len(all_posts)) + " Posts \u00b7 " + str(len(trustpilot_reviews)) + " Trustpilot \u00b7 Session #" + str(brain["sessions"]) + " \u00b7 Notion \u2705")

    # Trustpilot ins Brain
    if "trustpilot" not in brain:
        brain["trustpilot"] = []
    brain["trustpilot"] = (brain["trustpilot"] + [
        {"title": p["title"][:100], "body": p["body"][:200], "url": p["url"]}
        for p in trustpilot_reviews
    ])[-50:]
    save_brain(brain)

    # Cache for PWA
    last_research_cache = {
        "date": today,
        "reddit_count": len(reddit_posts),
        "amazon_count": len(amazon_posts),
        "trustpilot_count": len(trustpilot_reviews),
        "top_hooks": hooks[:5],
    }

    send_telegram("\n".join(lines), chat_id=chat_id)
    write_to_notion(notion_data)
    log.info("Research done.")


def send_total(chat_id):
    brain = load_brain()
    if brain["sessions"] == 0:
        send_telegram("Gehirn leer. Starte /research!", chat_id=chat_id)
        return
    lines = ["<b>Gesammeltes Wissen \u2014 " + str(brain["sessions"]) + " Sessions</b>"]
    if brain["desires"]:
        lines.append("\n\U0001f49a <b>Kundenwuensche:</b>")
        for d in brain["desires"][-15:]:
            lines.append("  \u2022 " + d)
    if brain["problems"]:
        lines.append("\n\U0001f624 <b>Probleme:</b>")
        for p in brain["problems"][-15:]:
            lines.append("  \u2022 " + p)
    if brain["language"]:
        lines.append("\n\U0001f4ac <b>Kundensprache:</b>")
        for l in brain["language"][-10:]:
            lines.append("  \"" + l + "\"")
    if brain["hooks"]:
        lines.append("\n\U0001f525 <b>Hooks:</b>")
        for h in brain["hooks"][-15:]:
            lines.append("  \u2192 " + h)
    send_telegram("\n".join(lines), chat_id=chat_id)


@app.route("/webhook/" + TELEGRAM_BOT_TOKEN, methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    msg = data.get("message", {})
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = msg.get("text", "").lower().strip()
    if not chat_id:
        return "ok"
    if text in ["/start", "/help"]:
        send_telegram("Befehle:\n/research - Recherchieren\n/total - Alles Gelernte\n/status - Status",
                      chat_id=chat_id)
    elif text == "/research":
        send_telegram("Recherche laeuft... ~2 Min. -> Notion ok", chat_id=chat_id)
        threading.Thread(target=run_research, args=(chat_id,), daemon=True).start()
    elif text == "/total":
        threading.Thread(target=send_total, args=(chat_id,), daemon=True).start()
    elif text == "/status":
        brain = load_brain()
        send_telegram(
            "Bot laeuft ok\nSession #" + str(brain["sessions"]) + " Desires: " + str(len(brain["desires"])) + " Hooks: " + str(len(brain["hooks"])),
            chat_id=chat_id)
    else:
        send_telegram("Nutze /research, /total oder /status", chat_id=chat_id)
    return "ok"

@app.route("/run", methods=["GET", "POST"])
def run_endpoint():
    key = request.args.get("key", "") or (request.get_json(silent=True) or {}).get("key", "")
    if key != PWA_SECRET:
        return "unauthorized", 401
    threading.Thread(target=run_research, daemon=True).start()
    return "Research started", 200


@app.route("/api/data")
def api_data():
    if request.args.get("key", "") != PWA_SECRET:
        return {"error": "unauthorized"}, 401
    brain = load_brain()
    return {
        "brain": {
            "sessions": brain.get("sessions", 0),
            "last_update": brain.get("last_update", "–"),
            "desires": brain.get("desires", [])[-10:],
            "problems": brain.get("problems", [])[-10:],
            "language": brain.get("language", [])[-8:],
            "hooks": brain.get("hooks", [])[-10:],
            "top_posts": brain.get("top_posts", [])[-8:],
            "trustpilot": brain.get("trustpilot", [])[-6:],
        },
        "last_run": last_research_cache,
    }


@app.route("/dashboard")
def dashboard():
    if request.args.get("key", "") != PWA_SECRET:
        return "Unauthorized", 401
    from flask import render_template
    return render_template("dashboard.html", secret=PWA_SECRET)


@app.route("/sw.js")
def service_worker():
    from flask import send_from_directory
    return send_from_directory("static", "sw.js", mimetype="application/javascript")


@app.route("/")
def health():
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
