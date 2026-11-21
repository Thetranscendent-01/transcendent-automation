# The Transcendent — Automated Promotion & SEO Setup

This package monitors your live **Blogger RSS** (`thetranscendent-official.blogspot.com`) and **YouTube Channel RSS** (`@theTranscendent-official`) automatically in the cloud every 6 hours while you sleep, and publishes a live **GitHub Pages SEO Syndication Hub** with automatic backlinks to **`https://thetranscendent.org/`**.

## Live Properties & Feeds
- **Main Website**: https://thetranscendent.org/
- **Official Blog**: https://thetranscendent-official.blogspot.com/ ([RSS Feed](https://thetranscendent-official.blogspot.com/feeds/posts/default?alt=rss))
- **YouTube Channel**: https://www.youtube.com/@theTranscendent-official ([RSS Feed](https://www.youtube.com/feeds/videos.xml?channel_id=UCtrv7j7JKqOh1Wg_J-HD2pQ))
- **Live GitHub Pages SEO Hub**: https://thetranscendent-01.github.io/transcendent-automation/
  - Unified RSS Feed: `https://thetranscendent-01.github.io/transcendent-automation/feed.xml`
  - XML Sitemap: `https://thetranscendent-01.github.io/transcendent-automation/sitemap.xml`

## What It Does Automatically (Every 6 Hours)
1. Detects every new Blogger article and YouTube video.
2. Rebuilds the **GitHub Pages SEO Syndication Landing Page** (`index.html`, `feed.xml`, `sitemap.xml`) with schema.org JSON-LD (`EducationalOrganization` + `ItemList`), canonical backlinks to `thetranscendent.org`, and summaries of your latest Blogger articles and YouTube documentaries.
3. Generates `daily_pack.md` with:
   - High-CTR rewritten titles (removes `#` tag clutter that lowers search clicks)
   - 155-character SEO Search Descriptions
   - Ready-to-post X/Twitter, LinkedIn, and Reddit discussion copy
4. Pushes new posts automatically to any **Webhook** (Make.com, Zapier, Discord, Slack) and **Telegram Channel** if configured.
5. Pings **IndexNow** for instant Bing/Yandex indexing on `thetranscendent.org`.

## Repository Contents
- `promote.py` — Zero-dependency Python 3 promotion & SEO syndication engine.
- `.github/workflows/daily-promote.yml` — GitHub Actions workflow running every 6 hours (`0 */6 * * *`) + on-demand `workflow_dispatch`.
- `index.html`, `feed.xml`, `sitemap.xml` — Live GitHub Pages SEO syndication hub.
- `daily_pack.md` — Ready-to-publish social media & Reddit copy pack.
- `seo-templates/thetranscendent-head-seo.html` — `<head>` SEO meta tags, multilingual `hreflang`, and `EducationalOrganization` JSON-LD for `https://thetranscendent.org/`.
- `seo-templates/blogger-callout-widget.html` — Callout widget for Blogger post footers linking readers to `thetranscendent.org` and YouTube.

## Optional Secrets for Social Auto-Posting
In your GitHub repo go to **Settings → Secrets and variables → Actions** and add:
- `WEBHOOK_URL` — Paste a **Make.com** or **Zapier** webhook URL connected to your X, LinkedIn, Facebook, and Pinterest accounts.
- `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID` — Auto-posts to your Telegram channel.
- `INDEXNOW_KEY` — Your IndexNow key for instant search indexing.

## One-Time Manual Registrations (Required by Google / Microsoft)
- **Google News**: https://publishercenter.google.com/ (Add RSS: `https://thetranscendent-official.blogspot.com/feeds/posts/default?alt=rss`)
- **Microsoft Start (MSN)**: https://publishers.microsoft.com/
- **Flipboard**: https://about.flipboard.com/publishers/
- **Blogger Meta Description Fix**: In Blogger **Settings → Meta tags**, replace `https://thetranscendent.org/` with a real description.
