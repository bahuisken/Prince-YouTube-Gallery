#!/usr/bin/env python3
"""
Keep a YouTube thumbnail gallery current.

1. Reads known video IDs from ids.txt (newest first) and titles from titles.json.
2. Fetches the channel's RSS feed, adds any new videos, and refreshes titles
   for the videos in the feed.
3. Looks up titles for any video that still has none (YouTube oEmbed, no API key).
4. Regenerates docs/index.html (served by GitHub Pages). Titles show on hover.

Optional:
    --prune   Remove IDs whose video has been deleted (oEmbed returns 404).
    --force   Rebuild docs/index.html even if nothing changed (e.g. after editing the template).

Settings (environment variables, all optional):
    CHANNEL_ID    The channel's UC... ID (overrides the default below).
    SKIP_SHORTS   "1" to ignore Shorts found in the feed (default: include them).
    FEED_URL      Override the feed URL (used for testing).
"""
import argparse
import html
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

# The CHANNEL_ID env var (if set) overrides the default below.
CHANNEL_ID = os.environ.get("CHANNEL_ID") or "UCv3mNSNjuWldihk1DUdnGtw"
SKIP_SHORTS = os.environ.get("SKIP_SHORTS", "0") == "1"
FEED_URL = os.environ.get(
    "FEED_URL",
    f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}",
)

IDS_FILE = "ids.txt"
TITLES_FILE = "titles.json"
OUT_FILE = os.path.join("docs", "index.html")
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
UA = {"User-Agent": "Mozilla/5.0"}
OEMBED = "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={id}&format=json"


def read_ids():
    if not os.path.exists(IDS_FILE):
        return []
    with open(IDS_FILE) as f:
        return list(dict.fromkeys(l.strip() for l in f if l.strip()))


def write_ids(ids):
    with open(IDS_FILE, "w") as f:
        f.write("\n".join(ids) + "\n")


def read_titles():
    if not os.path.exists(TITLES_FILE):
        return {}
    with open(TITLES_FILE, encoding="utf-8") as f:
        return json.load(f)


def write_titles(titles, ids):
    ordered = {i: titles[i] for i in ids if titles.get(i)}
    with open(TITLES_FILE, "w", encoding="utf-8") as f:
        json.dump(ordered, f, ensure_ascii=False, indent=1)
        f.write("\n")


def fetch_feed():
    """Return [(video_id, title), ...] from the RSS feed, newest first."""
    req = urllib.request.Request(FEED_URL, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        root = ET.fromstring(resp.read())
    found = []
    for entry in root.findall("a:entry", NS):
        vid = entry.findtext("yt:videoId", namespaces=NS)
        if not vid:
            continue
        if SKIP_SHORTS:
            link = entry.find("a:link", NS)
            if link is not None and "/shorts/" in link.get("href", ""):
                continue
        found.append((vid, (entry.findtext("a:title", namespaces=NS) or "").strip()))
    return found


def fetch_title(vid):
    """Look up one title via oEmbed. Returns "" on any failure (retried next run)."""
    try:
        req = urllib.request.Request(OEMBED.format(id=vid), headers=UA)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return (json.load(resp).get("title") or "").strip()
    except Exception:
        return ""


def fill_missing_titles(ids, titles):
    missing = [i for i in ids if not titles.get(i)]
    if not missing:
        return
    print(f"Looking up {len(missing)} missing title(s)...")
    with ThreadPoolExecutor(max_workers=8) as pool:
        for vid, title in zip(missing, pool.map(fetch_title, missing)):
            if title:
                titles[vid] = title
    still = sum(1 for i in ids if not titles.get(i))
    if still:
        print(f"  {still} video(s) still have no title (will retry next run).")


def prune(ids):
    """Drop IDs whose video is gone. Only a definite 404 removes an ID."""
    keep = []
    for vid in ids:
        try:
            urllib.request.urlopen(urllib.request.Request(OEMBED.format(id=vid), headers=UA), timeout=15)
            keep.append(vid)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"  removing {vid} (404)")
            else:
                keep.append(vid)
        except Exception:
            keep.append(vid)  # network trouble: never remove on uncertainty
    return keep


def safe_filename(title):
    """'My Video: Part 1 / 2?' -> 'My_Video_Part_1_2'. Keeps letters (any language), digits, - and ."""
    s = unicodedata.normalize("NFKC", title).strip()
    s = re.sub(r"\s+", "_", s)            # spaces -> underscores
    s = re.sub(r"[^\w\-.]", "", s)        # drop punctuation, emoji, slashes, quotes...
    s = re.sub(r"_+", "_", s).strip("._-")
    return s[:100].rstrip("._-")


def download_names(ids, titles):
    """Map video id -> filename. Falls back to the id; repeated titles get the id appended."""
    names, used = {}, set()
    for i in ids:
        base = safe_filename(titles.get(i, "")) or i
        if base.lower() in used:
            base = f"{base}_{i}"
        used.add(base.lower())
        names[i] = base + ".jpg"
    return names


def build_html(ids, titles):
    files = download_names(ids, titles)

    def card(i):
        name = html.escape(i)
        tip = html.escape(titles.get(i, ""), quote=True)
        tip_attr = f' title="{tip}"' if tip else ""
        return (
            f'<figure>'
            f'<a href="https://www.youtube.com/watch?v={name}" target="_blank" rel="noopener"{tip_attr}>'
            f'<img loading="lazy" src="https://i.ytimg.com/vi/{name}/maxresdefault.jpg" '
            f'onload="fb(this,true)" onerror="fb(this,false)" alt="{tip or name}"></a>'
            f'<a class="dl" data-name="{html.escape(files[i], quote=True)}" '
            f'href="https://i.ytimg.com/vi/{name}/maxresdefault.jpg" target="_blank" rel="noopener">Download thumbnail</a>'
            f'</figure>'
        )

    cards = "\n".join(card(i) for i in ids)
    return f"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Thumbnails ({len(ids)})</title>
<style>
body{{margin:0;padding:16px;background:#111;font-family:sans-serif;color:#eee}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}}
figure{{margin:0}}
img{{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:6px;background:#222;display:block}}
.dl{{display:block;margin-top:6px;font-size:13px;color:#8ab4f8;text-decoration:none}}
.dl:hover{{text-decoration:underline}}
</style>
<div class="g">
{cards}
</div>
<script>
function fb(i,ok){{
  if(i.dataset.f) return;
  if(!ok || i.naturalWidth<=120){{
    i.dataset.f=1;
    i.src=i.src.replace('maxresdefault','hqdefault');
    // keep the download link pointing at the thumbnail that actually exists
    i.closest('figure').querySelector('.dl').href=i.src;
  }}
}}
document.querySelectorAll('img').forEach(i=>{{ if(i.complete) fb(i,i.naturalWidth>0); }});

// Try a real download; if the browser blocks the cross-site fetch, open the image in a new tab.
document.addEventListener('click',async e=>{{
  const a=e.target.closest('.dl');
  if(!a) return;
  e.preventDefault();
  try{{
    const r=await fetch(a.href);
    if(!r.ok) throw 0;
    const url=URL.createObjectURL(await r.blob());
    const t=document.createElement('a');
    t.href=url; t.download=a.dataset.name; t.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }}catch(_){{
    window.open(a.href,'_blank','noopener');
  }}
}});
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prune", action="store_true", help="remove deleted videos")
    ap.add_argument("--force", action="store_true", help="rebuild the page even if nothing changed")
    args = ap.parse_args()

    ids = read_ids()
    titles = read_titles()
    original_ids, original_titles = list(ids), dict(titles)
    known = set(ids)

    feed = fetch_feed()
    new = [v for v, _ in feed if v not in known]
    if new:
        print(f"{len(new)} new video(s): {', '.join(new)}")
        ids = new + ids  # feed is newest first
    else:
        print("No new videos.")
    for vid, title in feed:
        if title:
            titles[vid] = title  # the feed has the current title

    fill_missing_titles(ids, titles)

    if args.prune:
        before = len(ids)
        ids = prune(ids)
        print(f"Pruned {before - len(ids)} video(s).")

    titles = {i: titles[i] for i in ids if titles.get(i)}

    # Skip writing when nothing changed so the workflow doesn't commit every run.
    if (ids == original_ids and titles == original_titles
            and os.path.exists(OUT_FILE) and not args.force):
        print(f"Gallery unchanged ({len(ids)} thumbnails).")
        return

    write_ids(ids)
    write_titles(titles, ids)
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(build_html(ids, titles))
    print(f"Gallery has {len(ids)} thumbnails, {len(titles)} with titles.")


if __name__ == "__main__":
    main()
