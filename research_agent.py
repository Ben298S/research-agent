import os
import json
import requests
from datetime import datetime, timezone

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


# ── Telegram ──────────────────────────────────────────────────────────────────

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chunk in [text[i:i+4096] for i in range(0, len(text), 4096)]:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "parse_mode": "HTML"}, timeout=15)


# ── Reddit via DuckDuckGo ─────────────────────────────────────────────────────

def gather_reddit() -> list:
    from duckduckgo_search import DDGS
    queries = [
        "site:reddit.com crepey skin",
        "site:reddit.com \"crepey skin\" treatment",
        "site:reddit.com \"crepey skin\" anti-aging",
    ]
    all_posts = []
    seen = set()

    with DDGS() as ddgs:
        for q in queries:
            try:
                for r in ddgs.text(q, max_results=10):
                    url = r.get("href", "")
                    if not url or url in seen or "reddit.com" not in url:
                        continue
                    seen.add(url)
                    parts = url.split("/")
                    sub = parts[4] if len(parts) > 4 and parts[3] == "r" else "reddit"
                    all_posts.append({
                        "title": r.get("title", ""),
                        "url": url,
                        "subreddit": sub,
                        "body": r.get("body", "")[:400],
                        "score": 0,
                        "date": "",
                    })
            except Exception as e:
                print(f"  DDG error '{q}': {e}")

    print(f"  Total Reddit posts: {len(all_posts)}")
    return all_posts


# ── Meta Ad Library ───────────────────────────────────────────────────────────

def get_meta_ads(search_terms: list) -> dict:
    if not META_ACCESS_TOKEN:
        return {}
    results = {}
    for term in search_terms:
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


# ── Hook scoring ──────────────────────────────────────────────────────────────

HOOK_KEYWORDS = [
    "why", "how", "stop", "finally", "secret", "fix", "help",
    "embarrassed", "hate", "ugly", "instantly", "overnight",
    "years younger", "anti-aging", "saggy", "loose", "collagen",
    "crepey", "crepe", "thin skin", "turkey neck",
]

def score_post(post: dict) -> int:
    text = (post["title"] + " " + post["body"]).lower()
    return sum(20 for kw in HOOK_KEYWORDS if kw in text)

def extract_hooks(posts: list) -> list:
    hooks = []
    for p in sorted(posts, key=score_post, reverse=True)[:20]:
        if any(kw in p["title"].lower() for kw in ["how", "why", "stop", "finally", "secret", "fix", "help"]):
            hooks.append(p["title"])
        if len(hooks) >= 5:
            break
    return hooks


# ── Summary ───────────────────────────────────────────────────────────────────

def build_message(reddit_posts: list, meta_ads: dict, today: str) -> str:
    lines = [f"🔬 <b>Daily Research Brief — {today}</b>\n"]

    lines.append("📱 <b>Reddit — Crepey Skin</b>")
    if reddit_posts:
        for p in sorted(reddit_posts, key=score_post, reverse=True)[:8]:
            lines.append(f'• <a href="{p["url"]}">{p["title"][:90]}</a>')
            lines.append(f'  └ r/{p["subreddit"]}')
            if p["body"]:
                lines.append(f'  └ "{p["body"][:120]}"')
    else:
        lines.append("Keine Posts gefunden.")

    hooks = extract_hooks(reddit_posts)
    if hooks:
        lines.append("\n🔥 <b>Trending Hooks &amp; Angles</b>")
        for h in hooks:
            lines.append(f"  → {h[:100]}")

    lines.append("\n📢 <b>Meta Ads — Cellu &amp; Happy Mammoth</b>")
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

    lines.append(f"\n💡 {len(reddit_posts)} Posts gescannt.")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    print("Gathering Reddit posts...")
    reddit_posts = gather_reddit()
    print("Fetching Meta ads...")
    meta_ads = get_meta_ads(["getcellu", "Happy Mammoth"])
    print("Sending to Telegram...")
    send_telegram(build_message(reddit_posts, meta_ads, today))
    print("Done.")

if __name__ == "__main__":
    main()
