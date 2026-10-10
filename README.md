# YouTube thumbnail gallery

A GitHub Action checks the channel's RSS feed every 4 hours, adds new videos to `ids.txt` and Shorts to `shorts.txt`, records titles in `titles.json` (shown on hover), and rebuilds the pages: `docs/index.html` (Videos) and `docs/shorts/index.html` (Shorts, linked from the main page). It commits the result and GitHub Pages serves it.

## Setup (about 5 minutes)

1. Create a new GitHub repo and push these files to it (`ids.txt`, `update_gallery.py`, `.github/`). The `docs/` folder is created by the first run.
2. The channel ID (`UCv3mNSNjuWldihk1DUdnGtw`) is already set as the default in `update_gallery.py`. To use a different channel without editing code, add a repository variable named `CHANNEL_ID` (**Settings → Secrets and variables → Actions → Variables**); it overrides the default.
3. Run the first update: **Actions → Update thumbnail gallery → Run workflow**.

4. Turn on Pages: **Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: `main`, folder `/docs`**.
Your gallery will be at `https://<your-username>.github.io/<repo-name>/`.

## Notes

- Titles for older videos are looked up automatically on the first run (a minute or two). Any lookup that fails is retried on the next run.
- Downloaded files are named after the video title (spaces become underscores, punctuation and emoji are dropped), e.g. `Purple_Rain_Live.jpg`. A video with no title uses its ID, and repeated titles get the ID appended.
- `ids.txt` is newest first. New videos are added to the top.
- The RSS feed only lists the 15 most recent uploads, so the job relies on `ids.txt` for everything older. Don't delete it.
- On Sundays (UTC) the job also removes videos that return a 404 from YouTube. Network errors never remove anything.
- Shorts are detected from the feed (a `/shorts/` link, or the channel's automatic Shorts playlist `UUSH...`) and go on the Shorts page. Anything listed in `shorts.txt` is removed from the Videos page automatically.
- The browser-tab title is `PAGE_TITLE` near the top of `update_gallery.py` (the Shorts page adds " - Shorts"). You can also set a repository variable named `PAGE_TITLE` to override it.
- GitHub pauses scheduled workflows in a repo with no activity for 60 days. If that happens, re-enable it in the Actions tab.
- Run locally: `CHANNEL_ID=UC... python3 update_gallery.py` (add `--prune` to check for deleted videos).

## Backfilling all Shorts (one time)

The RSS feed only lists the 15 newest uploads, so older Shorts need a one-time import. On your computer:

```
git pull --rebase
pip install yt-dlp
yt-dlp --flat-playlist --print id "https://www.youtube.com/channel/UCv3mNSNjuWldihk1DUdnGtw/shorts" > shorts.txt
git add shorts.txt
git commit -m "Backfill Shorts"
git push
```

Then run **Actions -> Update thumbnail gallery -> Run workflow**. The job moves any of those IDs out of `ids.txt`, looks up their titles, and builds the Shorts page.
