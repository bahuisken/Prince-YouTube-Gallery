# YouTube thumbnail gallery

A GitHub Action checks the channel's RSS feed every day, adds new videos to `ids.txt`, records titles in `titles.json` (shown on hover), rebuilds `docs/index.html`, and commits the result. GitHub Pages serves that page.

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
- Set `SKIP_SHORTS: "1"` in the workflow to leave Shorts out.
- GitHub pauses scheduled workflows in a repo with no activity for 60 days. If that happens, re-enable it in the Actions tab.
- Run locally: `CHANNEL_ID=UC... python3 update_gallery.py` (add `--prune` to check for deleted videos).
