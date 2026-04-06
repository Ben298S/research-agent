import os
import json
import requests
from datetime import datetime, timezone

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")  # optional

HEADERS = {"User-Agent": "ResearchBot/1.0 (automated daily briefing)"}


# ── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = [text[i:i+4096] for i in range(0, len(text), 4096)]
    for chunk in chunks:
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
        }, timeout=15)


# ── Reddit ────────────────────────────────────────────────────────────────────

def search_reddit(query: str, subreddit: str = None, limit: int = 8) -> list:
    if subreddit:
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        params = {"q": query, "sort": "new", "limit": limit, "restrict_sr": 1}
    else:
        url = "https://www.reddit.com/search.json"
        params = {"q": query, "sort": "new", "limit": limit}

    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=15)
        r.raise_for_status()
        posts = r.json()["data"]["children"]
    except Exception:
        return []

    results = []
    for post in posts:
        d = post["data"]
        results.append({
            "title": d["title"],
            "url": f"https://reddit.com{d['permalink']}",
            "score": d["score"],
            "subreddit": d["subreddit"],
            "date": datetime.utcfromtimestamp(d["created_utc"]).strftime("%Y-%m-%d"),
            "body": d.get("selftext", "")[:400],
        })
    return results


def gather_reddit() -> list:
    query = "crepey skin"
    subreddits = ["SkincareAddiction", "Skincare", "antiaging", "30PlusSkinCare", "weddingplanning"]
    all_posts = []
    seen = set()

    for sub in subreddits:
        for post in search_reddit(query, subreddit=sub, limit=5):
            if post["url"] not in seen:
                seen.add(post["url"])
                all_posts.append(post)

    # global search as well
    for post in search_reddit(query, limit=10):
        if post["url"] not in seen:
            seen.add(post["url"])
            all_posts.append(post)

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
                    "fields": (
                        "ad_creative_bodies,"
                        "ad_creative_link_titles,"
                        "ad_creative_link_descriptions,"
                        "ad_delivery_start_time,"
                        "ad_snapshot_url,"
                        "page_name,"
                        "publisher_platforms"
                    ),
                },
                timeout=15,
            )
            r.raise_for_status()
            results[term] = r.json().get("data", [])
        except Exception as e:
            results[term] = []

    return results


# ── Claude Summary ────────────────────────────────────────────────────────────

def summarize_with_claude(reddit_posts: list, meta_ads: dict) -> str | None:
    if not ANTHROPIC_API_KEY:
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        reddit_snippet = json.dumps(reddit_posts[:15], ensure_ascii=False)[:4000]
        ads_snippet = json.dumps(meta_ads, ensure_ascii=False)[:2000]

        prompt = f"""You are a direct-response marketing researcher. Analyze the data below and write a concise daily briefing in this exact structure:

📱 REDDIT HIGHLIGHTS (Crepey Skin)
- List the 4-5 most interesting posts/discussions. Note the subreddit and key pain point or language used.

🔥 TRENDING HOOKS & ANGLES
- Identify 3-5 hooks or emotional angles that are resonating (based on upvotes, language, recurring themes).

📢 META ADS — Cellu & Happy Mammoth
- Summarize new/notable ads found. Quote actual ad copy if available. Note if no new ads found.

💡 QUICK TAKEAWAYS
- 2-3 actionable insights for ad creatives or landing pages.

Keep it tight, concrete, no fluff. Format for Telegram (plain text + emojis, no markdown tables or bold asterisks).

=== REDDIT DATA ===
{reddit_snippet}

=== META ADS DATA ===
{ads_snippet}
"""

        msg = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    except Exception as e:
        return None


# ── Fallback Plain Summary ────────────────────────────────────────────────────

HOOK_KEYWORDS = [
    "why", "how", "stop", "finally", "secret", "nobody", "doctor",
    "ugly", "hate", "embarrassed", "fix", "instantly", "overnight",
    "years younger", "anti-aging", "saggy", "loose", "wrinkl", "collagen",
    "crepe", "crepey", "thin skin", "turkey neck", "arms", "legs",
]

def score_post(post: dict) -> int:
    score = post["score"]
    text = (post["title"] + " " + post["body"]).lower()
    for kw in HOOK_KEYWORDS:
        if kw in text:
            score += 20
    return score


def extract_hooks(posts: list) -> list:
    """Pull recurring emotional angles from titles."""
    hooks = []
    for p in sorted(posts, key=score_post, reverse=True)[:20]:
        title = p["title"].lower()
        if any(kw in title for kw in ["how", "why", "stop", "finally", "secret", "fix", "help"]):
            hooks.append(p["title"])
        if len(hooks) >= 5:
            break
    return hooks


def plain_summary(reddit_posts: list, meta_ads: dict, today: str) -> str:
    lines = [f"🔬 <b>Daily Research Brief — {today}</b>\n"]

    # Top Reddit posts sorted by relevance score
    sorted_posts = sorted(reddit_posts, key=score_post, reverse=True)

    lines.append("📱 <b>Reddit — Crepey Skin (Top Posts)</b>")
    for p in sorted_posts[:8]:
        lines.append(f'• <a href="{p["url"]}">{p["title"][:90]}</a>')
        lines.append(f'  └ r/{p["subreddit"]} · {p["date"]} · {p["score"]} pts')
        if p["body"]:
            lines.append(f'  └ "{p["body"][:120]}…"')

    # Trending hooks
    hooks = extract_hooks(reddit_posts)
    if hooks:
        lines.append("\n🔥 <b>Trending Hooks &amp; Angles</b>")
        for h in hooks:
            lines.append(f"  → {h[:100]}")

    # Meta Ads
    lines.append("\n📢 <b>Meta Ads — Cellu &amp; Happy Mammoth</b>")
    if meta_ads:
        for brand, ads in meta_ads.items():
            lines.append(f"\n<b>{brand}</b> — {len(ads)} ad(s) found")
            for ad in ads[:3]:
                page = ad.get("page_name", "")
                start = ad.get("ad_delivery_start_time", "")[:10]
                bodies = ad.get("ad_creative_bodies") or []
                titles = ad.get("ad_creative_link_titles") or []
                copy = bodies + titles
                if page:
                    lines.append(f"  📌 {page} (live since {start})")
                if copy:
                    lines.append(f'  "{copy[0][:150]}"')
                snap = ad.get("ad_snapshot_url")
                if snap:
                    lines.append(f"  🔗 {snap}")
    else:
        lines.append("META_ACCESS_TOKEN not configured — skipped.")

    lines.append("\n💡 <b>Quick Note</b>")
    lines.append(f"Scanned {len(reddit_posts)} Reddit posts across SkincareAddiction, antiaging, 30PlusSkinCare &amp; more.")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    today = datetime.now(timezone.utc).strftime("%d.%m.%Y")

    print("Gathering Reddit posts…")
    reddit_posts = gather_reddit()
    print(f"  Found {len(reddit_posts)} posts")

    print("Fetching Meta ads…")
    meta_ads = get_meta_ads(["getcellu", "Happy Mammoth"])
    print(f"  Brands checked: {list(meta_ads.keys())}")

    print("Generating summary…")
    summary = summarize_with_claude(reddit_posts, meta_ads)

    if summary:
        message = f"🔬 <b>Daily Research Brief — {today}</b>\n\n{summary}"
    else:
        message = plain_summary(reddit_posts, meta_ads, today)

    print("Sending to Telegram…")
    send_telegram(message)
    print("Done.")


if __name__ == "__main__":
    main()
