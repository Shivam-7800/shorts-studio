# Shorts Studio

A local web app for your Shorts pipeline. Type a topic, edit the script Gemini writes, build the video, watch it, then publish to YouTube Shorts and/or Instagram Reels, all from the browser.

## What's in the folder

| File | What it does |
|---|---|
| `app.py` | The web server. Run this. |
| `static/index.html` | The whole interface |
| `pipeline.py` | Script → visuals → voice → footage → render (your old `main.py` logic) |
| `yt_common.py` | YouTube sign-in and upload (now with progress and returned links) |
| `insta.py` | Instagram Reels publishing |
| `main.py` | Terminal version, same pipeline, if you still want it |
| `upload_existing.py` | Your original terminal reframe script, unchanged |

## First-time setup (Windows)

```powershell
cd shorts-studio
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
notepad .env          # paste your GEMINI_API_KEY and PEXELS_API_KEY
```

Then put your `client_secret.json` in the folder (download a fresh one from Google Cloud Console, see the security note below).

## Run it

```powershell
.venv\Scripts\activate
python app.py
```

Open **http://127.0.0.1:5000**. The coloured dots at the top right show which services are ready.

The first time you post to a channel, click **Connect** next to it. A Google sign-in window opens on your computer; pick the right account and channel. After that, the saved `token_S.json` / `token_B.json` is reused automatically.

To rename "Channel S" and "Channel B", edit `CHANNELS` in `yt_common.py`.

## What's new

* **Faster.** Gemini switches to the next model instantly when one is busy, the build makes one Gemini call instead of three, every voice line is recorded at once, every clip downloads at once, clips are fetched at 1080p instead of 4K, and rendering uses a faster encoder setting.
* **Auto description.** The build writes a title, description and hashtags. Change the title and the description and hashtags rewrite themselves (unless you've edited the description by hand). "Write from title" does it on demand.
* **Look.** Real stock footage, or Cartoon / Anime images drawn by Pollinations (free, no key, about one image every 15 seconds).
* **My voice.** Record 15 seconds in the app and the script is spoken in your voice (English and Hindi). Needs a one-time install: `python -m pip install --user chatterbox-tts`.

## Instagram setup (optional)

Instagram only allows posting through its official API, which needs:

1. An Instagram **Business or Creator** account (free switch in the Instagram app: Settings → Account type).
2. A Meta developer app at https://developers.facebook.com with the Instagram API product and the `instagram_content_publish` permission.
3. Your Instagram account ID and a long-lived access token from that app.

Put them in `.env`:

```
IG_USER_ID=1784...
IG_ACCESS_TOKEN=EAAB...
```

If your token came from "Instagram Login" rather than "Facebook Login", also add `IG_GRAPH_HOST=graph.instagram.com`. Restart `app.py` after editing `.env`.

Reels go public immediately (Instagram has no private/unlisted), so the app asks you to confirm every time.

## Putting it on GitHub

The `.gitignore` already keeps out `.env`, `client_secret*.json`, `token_*.json`, and all generated videos. **Check before your first push:**

```powershell
git init
git add .
git status            # make sure no .env, client_secret or token_ files are listed
git commit -m "Shorts Studio web UI"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO.git
git push -u origin main
```

If you're adding this to an existing repo that already has `client_secret.json` or token files committed, remove them from tracking (they stay on disk):

```powershell
git rm --cached client_secret.json token_S.json token_B.json
git commit -m "Stop tracking secrets"
```

Files committed in the past stay in the repo's history, so rotate those credentials anyway.

## Running it from GitHub (no computer needed)

The `docs/` page is a control panel served by GitHub Pages. It starts the
**Make a Short** and **Publish a Short** workflows in `.github/workflows/`, which
run on GitHub's machines. Keys live in the repo's private **Secrets**
(Settings → Secrets and variables → Actions):

`GEMINI_API_KEY`, `PEXELS_API_KEY`, `CLIENT_SECRET_JSON`, `YT_TOKEN_S`, `YT_TOKEN_B`
(the last three hold the full text of those files).

Optional secrets for the website:

* `IG_USER_ID` and `IG_ACCESS_TOKEN` turn on Instagram posting (see "Instagram setup").
* `VOICE_SAMPLE_B64` turns on "My voice": record your voice in the PC app, run
  `python make_voice_secret.py`, and paste what it copies. Builds with your voice take 10 to 15 minutes.

Each person opening the panel needs their own GitHub token with Actions access
to this repo, so visitors without one can't build or publish anything.
Workflow logs on a public repo are public, so the workflows never print video links.
Built videos can be downloaded by any signed-in GitHub user who finds the run, for 7 days.

## Notes

* Locally, the server listens only on `127.0.0.1`, so nothing outside your computer can reach it.
* Videos render one at a time. Files land in `videos/`; scratch files go in `work/` and can be deleted anytime.
* Output is H.264 + AAC, 1080×1920, which both YouTube and Instagram accept.
