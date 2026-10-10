#!/usr/bin/env python3
"""
Keep a YouTube thumbnail gallery current, with Videos and Shorts on separate pages.

1. Reads known IDs from ids.txt (videos) and shorts.txt (Shorts), titles from titles.json.
2. Fetches the channel's RSS feed (and the channel's Shorts feed), files new items
   under Videos or Shorts, and refreshes titles.
3. Moves any video in ids.txt that is also in shorts.txt over to the Shorts list.
4. Looks up titles for anything that still has none (YouTube oEmbed, no API key).
5. Regenerates docs/index.html (Videos) and docs/shorts/index.html (Shorts).

Optional:
    --prune   Remove IDs whose video has been deleted (oEmbed returns 404).
    --force   Rebuild the pages even if nothing changed (e.g. after editing the template).

Settings (environment variables, all optional):
    CHANNEL_ID    The channel's UC... ID (overrides the default below).
    PAGE_TITLE    Browser-tab title (overrides the default below).
    FEED_URL / SHORTS_FEED_URL   Override the feed URLs (used for testing).
"""
import argparse
import html
import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

# Environment variables (if set) override the defaults below.
CHANNEL_ID = os.environ.get("CHANNEL_ID") or "UCv3mNSNjuWldihk1DUdnGtw"
PAGE_TITLE = os.environ.get("PAGE_TITLE") or "Thumbnails"

FEED_URL = os.environ.get(
    "FEED_URL",
    f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}",
)
# YouTube keeps an automatic "Shorts only" playlist: UC... -> UUSH...
SHORTS_FEED_URL = os.environ.get(
    "SHORTS_FEED_URL",
    f"https://www.youtube.com/feeds/videos.xml?playlist_id=UUSH{CHANNEL_ID[2:]}",
)

IDS_FILE = "ids.txt"
SHORTS_FILE = "shorts.txt"
TITLES_FILE = "titles.json"
VIDEOS_PAGE = os.path.join("docs", "index.html")
SHORTS_PAGE = os.path.join("docs", "shorts", "index.html")
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
UA = {"User-Agent": "Mozilla/5.0"}
OEMBED = "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={id}&format=json"


def read_list(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(dict.fromkeys(l.strip() for l in f if l.strip()))


def write_list(path, items):
    with open(path, "w") as f:
        f.write("\n".join(items) + ("\n" if items else ""))


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


def fetch_feed(url):
    """Return [(video_id, title, is_short), ...] from an RSS feed, newest first."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        root = ET.fromstring(resp.read())
    found = []
    for entry in root.findall("a:entry", NS):
        vid = entry.findtext("yt:videoId", namespaces=NS)
        if not vid:
            continue
        link = entry.find("a:link", NS)
        is_short = link is not None and "/shorts/" in link.get("href", "")
        found.append((vid, (entry.findtext("a:title", namespaces=NS) or "").strip(), is_short))
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


def build_html(ids, titles, shorts_page=False):
    files = download_names(ids, titles)
    if shorts_page:
        page_title = f"{PAGE_TITLE} - Shorts"
        nav = '<a href="../">&larr; Videos</a>'
        fit = "contain"  # Shorts are vertical; don't crop them
    else:
        page_title = PAGE_TITLE
        nav = '<a href="shorts/">Shorts &rarr;</a>'
        fit = "cover"

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
<title>{html.escape(page_title)}</title>
<style>
body{{margin:0;padding:16px;background:#111;font-family:sans-serif;color:#eee}}
nav{{text-align:right;margin-bottom:12px}}
nav a{{color:#8ab4f8;text-decoration:none;font-size:15px}}
nav a:hover{{text-decoration:underline}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}}
figure{{margin:0}}
img{{width:100%;aspect-ratio:16/9;object-fit:{fit};border-radius:6px;background:#222;display:block}}
.dl{{display:block;margin-top:6px;font-size:13px;color:#8ab4f8;text-decoration:none}}
.dl:hover{{text-decoration:underline}}
</style>
<nav>{nav}</nav>
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


def write_page(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prune", action="store_true", help="remove deleted videos")
    ap.add_argument("--force", action="store_true", help="rebuild the pages even if nothing changed")
    args = ap.parse_args()

    ids, shorts, titles = read_list(IDS_FILE), read_list(SHORTS_FILE), read_titles()
    original = (list(ids), list(shorts), dict(titles))

    feed = fetch_feed(FEED_URL)
    try:
        shorts_feed = fetch_feed(SHORTS_FEED_URL)
    except Exception as e:  # the Shorts playlist feed is a bonus; never fail the run over it
        print(f"Note: could not read the Shorts feed ({e}); using /shorts/ links only.")
        shorts_feed = []

    # A video is a Short if the main feed links it as /shorts/ or the Shorts feed lists it.
    feed_shorts = list(dict.fromkeys(
        [v for v, _, s in feed if s] + [v for v, _, _ in shorts_feed]
    ))
    feed_short_set = set(feed_shorts)

    # Shorts we haven't filed yet (including any that earlier landed in ids.txt)
    new_shorts = [v for v in feed_shorts if v not in set(shorts)]
    # Videos we haven't seen anywhere
    seen = set(ids) | set(shorts) | feed_short_set
    new_videos = list(dict.fromkeys(v for v, _, _ in feed if v not in seen))

    if new_videos:
        print(f"{len(new_videos)} new video(s): {', '.join(new_videos)}")
    if new_shorts:
        print(f"{len(new_shorts)} new short(s): {', '.join(new_shorts)}")
    if not (new_videos or new_shorts):
        print("No new videos or shorts.")

    shorts = new_shorts + shorts
    short_set = set(shorts)
    moved = [i for i in ids if i in short_set]
    if moved:
        print(f"Moving {len(moved)} item(s) from Videos to Shorts.")
    ids = new_videos + [i for i in ids if i not in short_set]

    for vid, title, _ in feed + shorts_feed:
        if title:
            titles[vid] = title  # the feed has the current title

    fill_missing_titles(ids + shorts, titles)

    if args.prune:
        before = len(ids) + len(shorts)
        ids, shorts = prune(ids), prune(shorts)
        print(f"Pruned {before - len(ids) - len(shorts)} video(s).")

    keep = set(ids) | set(shorts)
    titles = {i: t for i, t in titles.items() if i in keep and t}

    # Skip writing when nothing changed so the workflow doesn't commit every run.
    if ((ids, shorts, titles) == original
            and os.path.exists(VIDEOS_PAGE) and os.path.exists(SHORTS_PAGE) and not args.force):
        print(f"Gallery unchanged ({len(ids)} videos, {len(shorts)} shorts).")
        return

    write_list(IDS_FILE, ids)
    write_list(SHORTS_FILE, shorts)
    write_titles(titles, ids + shorts)
    write_page(VIDEOS_PAGE, build_html(ids, titles))
    write_page(SHORTS_PAGE, build_html(shorts, titles, shorts_page=True))
    print(f"Gallery has {len(ids)} videos and {len(shorts)} shorts.")


if __name__ == "__main__":
    main()
