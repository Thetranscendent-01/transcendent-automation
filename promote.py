#!/usr/bin/env python3
"""
Automated Daily Promotion & SEO Syndication Engine for The Transcendent.
Monitors Blogger RSS & YouTube Channel RSS, generates ready-to-post social/SEO
packs, builds live GitHub Pages SEO syndication files (index.html, feed.xml,
sitemap.xml), pings IndexNow, and dispatches to configured webhooks/social APIs.
Zero external dependencies (Python 3 standard library only).
"""

import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

BLOGGER_RSS = "https://thetranscendent-official.blogspot.com/feeds/posts/default?alt=rss"
YOUTUBE_RSS = "https://www.youtube.com/feeds/videos.xml?channel_id=UCtrv7j7JKqOh1Wg_J-HD2pQ"
MAIN_SITE = "https://thetranscendent.org"
BLOG_SITE = "https://thetranscendent-official.blogspot.com"
YOUTUBE_CHANNEL = "https://www.youtube.com/@theTranscendent-official"
PAGES_URL = "https://thetranscendent-01.github.io/transcendent-automation"

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "state.json"
DAILY_PACK_FILE = BASE_DIR / "daily_pack.md"
INDEX_HTML_FILE = BASE_DIR / "index.html"
FEED_XML_FILE = BASE_DIR / "feed.xml"
SITEMAP_XML_FILE = BASE_DIR / "sitemap.xml"

USER_AGENT = "TheTranscendentBot/1.0 (+https://thetranscendent.org/)"


def fetch_url(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 15) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


def clean_html(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_title(raw_title: str) -> str:
    """Remove trailing hashtag clutter for higher CTR on search & social."""
    t = html.unescape(raw_title or "").strip()
    t = re.sub(r",?\s*#theTRANSCENDENT\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r",?\s*#tTʇ\b", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t).strip(" ,.-")
    return t


def suggest_subreddits(title: str, summary: str) -> list[str]:
    text = f"{title} {summary}".lower()
    subs = []
    if any(k in text for k in ["africa", "congo", "djibouti", "egypt", "guinea", "ivoire", "comoros"]):
        subs.extend(["r/geopolitics", "r/Africa", "r/economics"])
    if any(k in text for k in ["ai", "gemini", "outage", "security", "tech", "big tech", "autonomous"]):
        subs.extend(["r/technology", "r/artificial", "r/futurology"])
    if any(k in text for k in ["voyager", "nasa", "space", "cosmos", "telescope", "milky way"]):
        subs.extend(["r/space", "r/astronomy"])
    if any(k in text for k in ["oil", "energy", "economy", "economic", "market"]):
        subs.append("r/economics")
    if not subs:
        subs = ["r/geopolitics", "r/worldnews", "r/TrueReddit"]
    # Deduplicate preserving order
    seen = set()
    return [s for s in subs if not (s in seen or seen.add(s))][:4]


def parse_blogger_rss(xml_text: str, limit: int = 12) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for item in root.findall("./channel/item")[:limit]:
        title = item.findtext("title", "").strip()
        link = item.findtext("link", "").strip()
        pub_date = item.findtext("pubDate", "").strip()
        desc = clean_html(item.findtext("description", ""))
        items.append({
            "source": "blogger",
            "title": title,
            "clean_title": clean_title(title),
            "url": link,
            "published": pub_date,
            "summary": desc[:280].rsplit(" ", 1)[0] + "..." if len(desc) > 280 else desc,
        })
    return items


def parse_youtube_rss(xml_text: str, limit: int = 12) -> list[dict]:
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }
    root = ET.fromstring(xml_text)
    items = []
    for entry in root.findall("atom:entry", ns)[:limit]:
        title = entry.findtext("atom:title", "", ns).strip()
        link_el = entry.find("atom:link[@rel='alternate']", ns)
        link = link_el.attrib.get("href", "") if link_el is not None else ""
        published = entry.findtext("atom:published", "", ns).strip()
        desc_el = entry.find("media:group/media:description", ns)
        desc = clean_html(desc_el.text if desc_el is not None and desc_el.text else "")
        items.append({
            "source": "youtube",
            "title": title,
            "clean_title": clean_title(title),
            "url": link,
            "published": published,
            "summary": desc[:240].rsplit(" ", 1)[0] + "..." if len(desc) > 240 else desc,
        })
    return items


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"processed_urls": [], "last_run": None}


def save_state(state: dict) -> None:
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    # Keep last 500 URLs to prevent unbounded growth
    state["processed_urls"] = state["processed_urls"][-500:]
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def ping_indexnow(urls: list[str]) -> str | None:
    key = os.environ.get("INDEXNOW_KEY", "").strip()
    if not key:
        return None
    results = []
    # 1. Always ping IndexNow for the verified GitHub Pages SEO Syndication Hub
    pages_host = "thetranscendent-01.github.io"
    pages_urls = [
        f"{PAGES_URL}/",
        f"{PAGES_URL}/feed.xml",
        f"{PAGES_URL}/sitemap.xml",
    ]
    pages_payload = {
        "host": pages_host,
        "key": key,
        "keyLocation": f"{PAGES_URL}/{key}.txt",
        "urlList": pages_urls,
    }
    status_p, body_p = post_json("https://api.indexnow.org/indexnow", pages_payload)
    results.append(f"IndexNow ({pages_host}) HTTP {status_p}: {body_p[:80]}")

    # 2. Ping IndexNow for main site URLs if any are in the batch
    main_urls = [u for u in urls if u.startswith(MAIN_SITE)]
    if main_urls:
        main_payload = {
            "host": "thetranscendent.org",
            "key": key,
            "keyLocation": f"{MAIN_SITE}/{key}.txt",
            "urlList": main_urls,
        }
        status_m, body_m = post_json("https://api.indexnow.org/indexnow", main_payload)
        results.append(f"IndexNow (thetranscendent.org) HTTP {status_m}: {body_m[:80]}")

    return " | ".join(results)


def dispatch_webhook(item: dict) -> str | None:
    webhook_url = os.environ.get("WEBHOOK_URL", "").strip()
    if not webhook_url:
        return None
    message = (
        f"**{item['clean_title']}**\n"
        f"{item['summary']}\n\n"
        f"Read/Watch: {item['url']}\n"
        f"More free AI, Coding & Geopolitics: {MAIN_SITE}/"
    )
    # Compatible with Discord, Slack, Make.com, and Zapier webhooks
    payload = {
        "content": message,
        "text": message,
        "title": item["clean_title"],
        "url": item["url"],
        "source": item["source"],
        "summary": item["summary"],
        "main_site": MAIN_SITE,
    }
    status, _ = post_json(webhook_url, payload)
    return f"Webhook HTTP {status}"


def dispatch_telegram(item: dict) -> str | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return None
    text = (
        f"🌍 <b>{html.escape(item['clean_title'])}</b>\n\n"
        f"{html.escape(item['summary'])}\n\n"
        f"🔗 {item['url']}\n"
        f"🎓 Free Courses & Tools: {MAIN_SITE}/"
    )
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    status, _ = post_json(api_url, {"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    return f"Telegram HTTP {status}"


def format_markdown_pack(items: list[dict], run_time: str) -> str:
    lines = [
        f"# Daily Promotion & SEO Pack — {run_time}",
        "",
        "Ready-to-publish social posts, high-CTR titles, and subreddit targets generated automatically from your live Blogger & YouTube feeds.",
        "",
    ]
    for idx, item in enumerate(items, 1):
        subs = ", ".join(suggest_subreddits(item["clean_title"], item["summary"]))
        meta_desc = (item["summary"][:152].rsplit(" ", 1)[0] + "...") if len(item["summary"]) > 155 else item["summary"]
        lines.extend([
            f"## {idx}. [{item['source'].upper()}] {item['clean_title']}",
            f"- **Original URL**: {item['url']}",
            f"- **High-CTR Title (Remove `#` tags from title)**: `{item['clean_title']}`",
            f"- **SEO Meta / Search Description (155 chars)**: `{meta_desc}`",
            f"- **Target Subreddits**: {subs}",
            "",
            "### Ready-to-Post X / LinkedIn Copy",
            "```text",
            f"{item['clean_title']}",
            "",
            f"{item['summary']}",
            "",
            f"Full breakdown: {item['url']}",
            f"Free AI, Coding & Global Insights: {MAIN_SITE}/",
            "#Geopolitics #GlobalEconomy #TheTranscendent",
            "```",
            "",
            "### Ready-to-Post Reddit Discussion Starter",
            "```text",
            f"Title: {item['clean_title']}",
            "",
            f"{item['summary']}",
            "",
            f"Full analysis & sources: {item['url']}",
            "```",
            "",
            "---",
            "",
        ])
    return "\n".join(lines)


def generate_feed_xml(items: list[dict], now_iso: str) -> str:
    rfc_now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    entries = []
    for it in items:
        title_esc = html.escape(it["clean_title"])
        url_esc = html.escape(it["url"])
        summary_esc = html.escape(it["summary"])
        pub_esc = html.escape(it.get("published") or rfc_now)
        source_label = "Official Blog" if it["source"] == "blogger" else "YouTube Documentary"
        entries.append(f"""    <item>
      <title>{title_esc}</title>
      <link>{url_esc}</link>
      <guid isPermaLink="true">{url_esc}</guid>
      <pubDate>{pub_esc}</pubDate>
      <category>{source_label}</category>
      <description>{summary_esc} — Explore more free AI, Coding &amp; UX courses at {MAIN_SITE}/</description>
    </item>""")
    items_xml = "\n".join(entries)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>The Transcendent — Global Insights, Free AI &amp; Coding Courses, YouTube &amp; Dispatches</title>
    <link>{MAIN_SITE}/</link>
    <atom:link href="{PAGES_URL}/feed.xml" rel="self" type="application/rss+xml" />
    <description>Unified live syndication feed for The Transcendent ({MAIN_SITE}), Official Blogger Dispatches ({BLOG_SITE}), and YouTube Documentaries ({YOUTUBE_CHANNEL}).</description>
    <language>en-us</language>
    <lastBuildDate>{rfc_now}</lastBuildDate>
{items_xml}
  </channel>
</rss>
"""


MAIN_SITE_DEEP_LINKS = [
    ("https://thetranscendent.org/courses/", "Free Multilingual Courses Directory (English, বাংলা, हिन्दी)"),
    ("https://thetranscendent.org/courses/html-introduction-why-learn-to-html-code-in-the-age-of-ai-era-english/", "HTML Introduction: Why Learn HTML Code in the Age of AI (English)"),
    ("https://thetranscendent.org/courses/html-ai-%e0%a6%8f%e0%a6%b0-%e0%a6%af%e0%a7%81%e0%a6%97%e0%a7%87-%e0%a6%ac%e0%a6%be%e0%a6%82%e0%a6%b2%e0%a6%be-%e0%a6%a4%e0%a7%87/", "HTML AI এর যুগে বাংলা তে (Bengali HTML Course)"),
    ("https://thetranscendent.org/courses/html-ai-%e0%a4%af%e0%a5%81%e0%a4%97-%e0%a4%95%e0%a5%87-%e0%a4%af%e0%a5%81%e0%a4%97-%e0%a4%b9%e0%a4%bf%e0%a4%82%e0%a4%a6%e0%a5%80-%e0%a4%ae%e0%a5%87%e0%a4%82/", "HTML AI युग के युग हिंदी में (Hindi HTML Course)"),
    ("https://thetranscendent.org/courses/ai-artificial-intelligence-foundations-thinking-machine-learning-english-00/", "AI Foundations: Thinking & Machine Learning (English)"),
    ("https://thetranscendent.org/courses/%e0%a6%8f-%e0%a6%86%e0%a6%87-%e0%a6%86%e0%a6%b0%e0%a7%8d%e0%a6%9f%e0%a6%bf%e0%a6%ab%e0%a6%bf%e0%a6%b6%e0%a6%bf%e0%a6%af%e0%a6%bc%e0%a6%be%e0%a6%b2-%e0%a6%87%e0%a6%a8%e0%a7%8d%e0%a6%9f%e0%a7%87/", "এ আই আর্টিফিশিয়াল ইন্টেলিজেন্স Foundations (Bengali AI Course)"),
    ("https://thetranscendent.org/courses/ai-%e0%a4%86%e0%a4%b0%e0%a5%8d%e0%a4%9f%e0%a4%bf%e0%a4%ab%e0%a4%bf%e0%a4%b6%e0%a4%bf%e0%a4%af%e0%a4%b2-%e0%a4%87%e0%a4%82%e0%a4%9f%e0%a5%87%e0%a4%b2%e0%a4%bf%e0%a4%9c%e0%a5%87%e0%a4%82%e0%a4%b8-founda/", "AI आर्टिफिशियल इंटेलिजेंस Foundations (Hindi AI Course)"),
    ("https://thetranscendent.org/courses/how-to-build-your-career-path-in-user-experience-ux/", "How to Build Your Career Path in User Experience (UX)"),
    ("https://thetranscendent.org/courses/the-evolution-of-brand-design-from-foundations-to-fundamentals-a-look-into-its-origins-trends-and-future-insights/", "The Evolution of Brand Design: Foundations to Fundamentals (English)"),
    ("https://thetranscendent.org/courses/%e0%a6%ac%e0%a7%8d%e0%a6%b0%e0%a7%8d%e0%a6%af%e0%a6%be%e0%a6%a8%e0%a7%8d%e0%a6%a1-%e0%a6%a1%e0%a6%bf%e0%a6%9c%e0%a6%be%e0%a6%87%e0%a6%a8%e0%a7%87%e0%a6%b0-%e0%a6%ac%e0%a6%bf%e0%a6%ac%e0%a6%b0%e0%a7%8d/", "ব্র্যান্ড ডিজাইনের বিবর্তন (Bengali Brand Design Course)"),
    ("https://thetranscendent.org/courses/%e0%a4%ac%e0%a5%8d%e0%a4%b0%e0%a4%be%e0%a4%82%e0%a4%a1-%e0%a4%a1%e0%a4%bf%e0%a4%9c%e0%a4%bc%e0%a4%be%e0%a4%87%e0%a4%a8-%e0%a4%95%e0%a4%be-%e0%a4%b5%e0%a4%bf%e0%a4%95%e0%a4%be%e0%a4%b8-%e0%a4%a8/", "ब्रांड डिज़ाइन का विकास (Hindi Brand Design Course)"),
    ("https://thetranscendent.org/courses/jewelry-drawing-foundations-from-basic-geometric-shapes-to-professional-organic-sketching/", "Jewelry Drawing Foundations: Geometric Shapes to Organic Sketching"),
    ("https://thetranscendent.org/courses/how-to-learn-english/", "How to Learn English — Complete Free Course"),
    ("https://thetranscendent.org/how-to-use-free-3d-cad-volume-calculators-for-gold-silver-platinum-and-other-metal/", "Free 3D CAD Volume Calculators for Gold, Silver, Platinum & Other Metals"),
    ("https://thetranscendent.org/free-background-remover-tool-remove-image-backgrounds-instantly/", "Free AI Image Background Remover Tool"),
    ("https://thetranscendent.org/n8n-for-beginner-course-free/", "n8n Automation for Beginners — Free Course"),
    ("https://thetranscendent.org/build-n8n-ai-bots-create-ai-powered-chatbots-with-n8n/", "Build n8n AI Bots & AI-Powered Chatbots"),
    ("https://thetranscendent.org/the-generative-ai-prompt-playbook-ready-made-prompts-for-productivity/", "The Generative AI Prompt Playbook"),
    ("https://thetranscendent.org/shop/", "3D CAD Fine Jewelry Shop & Designs"),
    ("https://thetranscendent.org/app/", "Interactive Browser Apps & Web Tools"),
]


def generate_sitemap_xml(items: list[dict], now_date: str) -> str:
    urls = [
        (f"{PAGES_URL}/", "1.0", "hourly"),
        (f"{PAGES_URL}/feed.xml", "0.8", "hourly"),
        (f"{MAIN_SITE}/", "1.0", "daily"),
        (f"{BLOG_SITE}/", "0.9", "daily"),
        (YOUTUBE_CHANNEL, "0.9", "daily"),
    ]
    seen = {u[0] for u in urls}
    for link_url, _ in MAIN_SITE_DEEP_LINKS:
        if link_url not in seen:
            seen.add(link_url)
            urls.append((link_url, "0.9", "weekly"))
    for it in items:
        u = it.get("url", "").strip()
        if u and u not in seen:
            seen.add(u)
            urls.append((u, "0.8", "weekly"))

    url_entries = []
    for loc, prio, freq in urls:
        loc_esc = html.escape(loc)
        url_entries.append(f"""  <url>
    <loc>{loc_esc}</loc>
    <lastmod>{now_date}</lastmod>
    <changefreq>{freq}</changefreq>
    <priority>{prio}</priority>
  </url>""")
    body = "\n".join(url_entries)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{body}
</urlset>
"""


def generate_index_html(blogger_items: list[dict], youtube_items: list[dict], run_time: str) -> str:
    def render_cards(items: list[dict], badge_text: str, badge_class: str, cta_text: str) -> str:
        if not items:
            return "<p class='empty'>Feed items will appear on the next scheduled sync.</p>"
        cards = []
        for it in items:
            t = html.escape(it["clean_title"])
            u = html.escape(it["url"])
            s = html.escape(it["summary"])
            p = html.escape(it.get("published", "")[:25])
            cards.append(f"""        <article class="card">
          <div class="card-meta">
            <span class="badge {badge_class}">{badge_text}</span>
            <time>{p}</time>
          </div>
          <h3><a href="{u}" rel="noopener" target="_blank">{t}</a></h3>
          <p>{s}</p>
          <div class="card-links">
            <a href="{u}" class="btn-link" rel="noopener" target="_blank">{cta_text} &rarr;</a>
            <a href="{MAIN_SITE}/" class="hub-backlink">TheTranscendent.org Hub</a>
          </div>
        </article>""")
        return "\n".join(cards)

    blog_cards = render_cards(blogger_items, "Blogger Dispatch", "badge-blog", "Read Full Article")
    yt_cards = render_cards(youtube_items, "YouTube Documentary", "badge-yt", "Watch on YouTube")

    all_items = blogger_items + youtube_items
    item_list_Element = []
    for idx, it in enumerate(all_items, 1):
        item_list_Element.append({
            "@type": "ListItem",
            "position": idx,
            "name": it["clean_title"],
            "url": it["url"],
            "description": it["summary"],
        })

    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "EducationalOrganization",
                "name": "The Transcendent",
                "url": f"{MAIN_SITE}/",
                "logo": f"{MAIN_SITE}/assets/images/a5e4bc950598_cropped-v1Asset-34.png",
                "sameAs": [
                    f"{MAIN_SITE}/",
                    f"{BLOG_SITE}/",
                    YOUTUBE_CHANNEL,
                ],
                "description": "Free multilingual coding, AI, and UX courses (English, বাংলা, हिन्दी), interactive browser utilities, geopolitical dispatches, and 3D CAD fine jewelry.",
            },
            {
                "@type": "ItemList",
                "name": "The Transcendent — Latest Articles & Video Documentaries",
                "itemListElement": item_list_Element,
            },
        ]
    }, indent=2)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>The Transcendent | Official SEO Content Hub — Free AI, Coding &amp; UX Courses, Blog &amp; YouTube</title>
  <meta name="description" content="Official live syndication hub for The Transcendent (thetranscendent.org). Explore free multilingual AI, HTML &amp; UX courses in English, বাংলা, and हिन्दी, daily geopolitical articles, and YouTube documentaries." />
  <meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1" />
  <link rel="canonical" href="{PAGES_URL}/" />
  <link rel="alternate" type="application/rss+xml" title="The Transcendent Unified RSS Feed" href="{PAGES_URL}/feed.xml" />
  <link rel="alternate" type="application/rss+xml" title="The Transcendent Official Blog RSS" href="{BLOGGER_RSS}" />
  <link rel="alternate" type="application/rss+xml" title="The Transcendent YouTube Channel RSS" href="{YOUTUBE_RSS}" />

  <!-- OpenGraph / Social -->
  <meta property="og:type" content="website" />
  <meta property="og:title" content="The Transcendent | Free AI, Coding &amp; UX Courses, Global Dispatches &amp; YouTube" />
  <meta property="og:description" content="Master HTML code, AI foundations, and UX design in English, বাংলা, and हिन्दी for free. Explore daily geopolitical analysis, web utilities, and 3D CAD designs." />
  <meta property="og:url" content="{MAIN_SITE}/" />

  <script type="application/ld+json">
{json_ld}
  </script>

  <style>
    :root {{
      --bg: #0b0f19;
      --surface: #131a2a;
      --surface-hover: #1a2438;
      --border: #23304a;
      --text: #e6edf3;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --accent-blue: #2563eb;
      --accent-red: #ef4444;
      --accent-green: #10b981;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .container {{ max-width: 1180px; margin: 0 auto; padding: 0 20px; }}
    header {{
      background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
      border-bottom: 1px solid var(--border);
      padding: 48px 0 36px;
    }}
    .brand-bar {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 20px;
    }}
    .brand-title {{
      font-size: 2rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: #fff;
    }}
    .sync-pill {{
      font-size: 0.8rem;
      background: rgba(16, 185, 129, 0.15);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.35);
      padding: 6px 12px;
      border-radius: 999px;
      font-weight: 600;
    }}
    .hero-desc {{
      font-size: 1.1rem;
      color: #cbd5e1;
      max-width: 840px;
      margin-bottom: 28px;
    }}
    .cta-grid {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 11px 20px;
      border-radius: 8px;
      font-weight: 600;
      font-size: 0.95rem;
      text-decoration: none !important;
      transition: transform 0.15s ease, opacity 0.15s ease;
    }}
    .btn:hover {{ transform: translateY(-1px); opacity: 0.95; }}
    .btn-primary {{ background: var(--accent-blue); color: #fff; }}
    .btn-yt {{ background: var(--accent-red); color: #fff; }}
    .btn-blog {{ background: #0284c7; color: #fff; }}
    .btn-outline {{
      background: rgba(255, 255, 255, 0.06);
      color: #e2e8f0;
      border: 1px solid var(--border);
    }}
    .pillars {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
      gap: 16px;
      margin: 32px 0;
    }}
    .pillar {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px;
    }}
    .pillar h2 {{ font-size: 1.05rem; margin-bottom: 8px; color: #fff; }}
    .pillar p {{ font-size: 0.9rem; color: var(--muted); margin-bottom: 12px; }}
    .section-head {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      border-bottom: 1px solid var(--border);
      padding-bottom: 12px;
      margin: 40px 0 20px;
    }}
    .section-head h2 {{ font-size: 1.4rem; color: #fff; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
      gap: 20px;
    }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 22px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: border-color 0.15s ease, background 0.15s ease;
    }}
    .card:hover {{
      border-color: var(--accent);
      background: var(--surface-hover);
    }}
    .card-meta {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 10px;
      font-size: 0.78rem;
      color: var(--muted);
    }}
    .badge {{
      padding: 3px 9px;
      border-radius: 4px;
      font-weight: 700;
      text-transform: uppercase;
      font-size: 0.72rem;
    }}
    .badge-blog {{ background: rgba(56, 189, 248, 0.15); color: #38bdf8; }}
    .badge-yt {{ background: rgba(239, 68, 68, 0.15); color: #f87171; }}
    .card h3 {{
      font-size: 1.08rem;
      line-height: 1.4;
      margin-bottom: 10px;
    }}
    .card h3 a {{ color: #fff; }}
    .card p {{
      font-size: 0.9rem;
      color: var(--muted);
      margin-bottom: 16px;
      flex-grow: 1;
    }}
    .card-links {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 0.85rem;
      padding-top: 12px;
      border-top: 1px solid rgba(255, 255, 255, 0.06);
    }}
    .btn-link {{ font-weight: 600; color: var(--accent); }}
    .hub-backlink {{ color: var(--muted); font-size: 0.8rem; }}
    footer {{
      margin-top: 64px;
      padding: 36px 0;
      border-top: 1px solid var(--border);
      font-size: 0.88rem;
      color: var(--muted);
      text-align: center;
    }}
    footer .footer-links {{
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 20px;
      margin-bottom: 14px;
    }}
  </style>
</head>
<body>
  <header>
    <div class="container">
      <div class="brand-bar">
        <h1 class="brand-title">The Transcendent — Live SEO &amp; Content Syndication Hub</h1>
        <span class="sync-pill">Auto-Synced Every 6 Hours &bull; Last Updated: {run_time}</span>
      </div>
      <p class="hero-desc">
        Welcome to the official syndication and discovery index for <strong><a href="{MAIN_SITE}/">TheTranscendent.org</a></strong>.
        Explore our free multilingual coding, AI, and UX courses (English, বাংলা, हिन्दी), interactive browser utilities,
        3D CAD jewelry calculators, daily geopolitical articles, and documentary videos.
      </p>
      <div class="cta-grid">
        <a class="btn btn-primary" href="{MAIN_SITE}/">Explore TheTranscendent.org &rarr;</a>
        <a class="btn btn-blog" href="{BLOG_SITE}/">Official Blogger Dispatches &rarr;</a>
        <a class="btn btn-yt" href="{YOUTUBE_CHANNEL}?sub_confirmation=1">Watch &amp; Subscribe on YouTube &rarr;</a>
        <a class="btn btn-outline" href="{PAGES_URL}/feed.xml">Unified RSS Feed</a>
        <a class="btn btn-outline" href="{PAGES_URL}/sitemap.xml">XML Sitemap</a>
      </div>
    </div>
  </header>

  <main class="container">
    <section class="pillars" aria-label="Core Ecosystem Links">
      <div class="pillar">
        <h2>Free Multilingual Tech Courses</h2>
        <p>Master HTML code, AI foundations, and UX design in English, বাংলা (Bengali), and हिन्दी (Hindi) for free.</p>
        <a href="{MAIN_SITE}/">Start Learning on TheTranscendent.org &rarr;</a>
      </div>
      <div class="pillar">
        <h2>Interactive Web Tools &amp; 3D CAD</h2>
        <p>Free browser utilities, precious metal 3D CAD volume calculators for Gold, Silver &amp; Platinum, and digital designs.</p>
        <a href="{MAIN_SITE}/">Launch Free Web Utilities &rarr;</a>
      </div>
      <div class="pillar">
        <h2>Global Geopolitics &amp; Economics Blog</h2>
        <p>In-depth analytical dispatches covering global economics, technology, space exploration, and international affairs.</p>
        <a href="{BLOG_SITE}/">Read Official Blog &rarr;</a>
      </div>
      <div class="pillar">
        <h2>YouTube Video Documentaries</h2>
        <p>High-impact video breakdowns and documentaries on @theTranscendent-official.</p>
        <a href="{YOUTUBE_CHANNEL}">Visit YouTube Channel &rarr;</a>
      </div>
    </section>

    <div class="section-head">
      <h2>Latest Official Blog Articles</h2>
      <a href="{BLOG_SITE}/">View All Articles on Blogger &rarr;</a>
    </div>
    <section class="grid">
{blog_cards}
    </section>

    <div class="section-head">
      <h2>Latest YouTube Videos (@theTranscendent-official)</h2>
      <a href="{YOUTUBE_CHANNEL}">View All Videos on YouTube &rarr;</a>
    </div>
    <section class="grid">
{yt_cards}
    </section>

    <div class="section-head">
      <h2>Free Courses, Web Utilities &amp; 3D CAD Index (thetranscendent.org)</h2>
      <a href="{MAIN_SITE}/courses/">Explore All Courses &rarr;</a>
    </div>
    <section class="grid">
""" + "\n".join(
        f'        <article class="card"><h3><a href="{html.escape(u)}" rel="noopener" target="_blank">{html.escape(label)}</a></h3><div class="card-links"><a href="{html.escape(u)}" class="btn-link" rel="noopener" target="_blank">Open on TheTranscendent.org &rarr;</a></div></article>'
        for u, label in MAIN_SITE_DEEP_LINKS
    ) + f"""
    </section>
  </main>

  <footer>
    <div class="container">
      <div class="footer-links">
        <a href="{MAIN_SITE}/">Main Website (thetranscendent.org)</a>
        <a href="{BLOG_SITE}/">Official Blog (Blogspot)</a>
        <a href="{YOUTUBE_CHANNEL}">YouTube (@theTranscendent-official)</a>
        <a href="{BLOGGER_RSS}">Blogger RSS</a>
        <a href="{YOUTUBE_RSS}">YouTube RSS</a>
        <a href="{PAGES_URL}/feed.xml">Syndication RSS</a>
        <a href="{PAGES_URL}/sitemap.xml">Sitemap XML</a>
      </div>
      <p>&copy; {datetime.now(timezone.utc).year} <a href="{MAIN_SITE}/">The Transcendent</a>. Automated 24/7 via GitHub Actions &amp; GitHub Pages.</p>
    </div>
  </footer>
</body>
</html>
"""


def main() -> int:
    force_pack = "--force-pack" in sys.argv
    state = load_state()
    processed = set(state.get("processed_urls", []))

    blogger_items: list[dict] = []
    youtube_items: list[dict] = []

    try:
        blogger_xml = fetch_url(BLOGGER_RSS)
        blogger_items = parse_blogger_rss(blogger_xml, limit=12)
    except Exception as e:
        print(f"[WARN] Failed to fetch Blogger RSS: {e}")

    try:
        yt_xml = fetch_url(YOUTUBE_RSS)
        youtube_items = parse_youtube_rss(yt_xml, limit=12)
    except Exception as e:
        print(f"[WARN] Failed to fetch YouTube RSS: {e}")

    all_items: list[dict] = blogger_items[:6] + youtube_items[:6]
    syndication_items: list[dict] = blogger_items + youtube_items

    new_items = [it for it in all_items if it["url"] and it["url"] not in processed]
    print(f"Fetched {len(syndication_items)} total feed items; {len(new_items)} new items.")

    for item in new_items:
        wh = dispatch_webhook(item)
        if wh:
            print(f"  -> {item['clean_title'][:45]}... | {wh}")
        tg = dispatch_telegram(item)
        if tg:
            print(f"  -> {item['clean_title'][:45]}... | {tg}")
        processed.add(item["url"])

    now_utc = datetime.now(timezone.utc)
    run_time = now_utc.strftime("%Y-%m-%d %H:%M UTC")
    now_iso = now_utc.isoformat()
    now_date = now_utc.strftime("%Y-%m-%d")

    pack_items = new_items if new_items else (all_items[:8] if force_pack else [])
    if pack_items:
        DAILY_PACK_FILE.write_text(format_markdown_pack(pack_items, run_time), encoding="utf-8")
        print(f"Updated {DAILY_PACK_FILE} with {len(pack_items)} items.")

    if syndication_items:
        INDEX_HTML_FILE.write_text(generate_index_html(blogger_items, youtube_items, run_time), encoding="utf-8")
        FEED_XML_FILE.write_text(generate_feed_xml(syndication_items, now_iso), encoding="utf-8")
        SITEMAP_XML_FILE.write_text(generate_sitemap_xml(syndication_items, now_date), encoding="utf-8")
        print("Updated GitHub Pages SEO syndication files: index.html, feed.xml, sitemap.xml")

    if new_items or syndication_items:
        idx_res = ping_indexnow([it["url"] for it in new_items])
        if idx_res:
            print(f"  -> {idx_res}")

    state["processed_urls"] = list(processed)
    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
