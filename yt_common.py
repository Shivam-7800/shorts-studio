import os
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE_DIR = Path(__file__).resolve().parent
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRET = BASE_DIR / "client_secret.json"

# Vertical Shorts frame. Small free servers (Render sets RENDER=true) use 720p
# so the render fits in 512 MB of memory; your own computer makes 1080p.
_LOW = os.environ.get("RENDER") == "true" or os.environ.get("LOW_MEMORY") == "1"
TARGET_W, TARGET_H = (720, 1280) if _LOW else (1080, 1920)
SHORTS_MAX_SECONDS = 180  # YouTube's current Shorts duration cap

# One entry per channel. Rename the labels to your real channel names — they show
# in the web UI. Token files are created the first time you connect a channel.
CHANNELS = {
    "S": {"label": "Channel S", "token_file": "token_S.json"},
    "B": {"label": "Channel B", "token_file": "token_B.json"},
}


def _token_path(channel_key):
    return BASE_DIR / CHANNELS[channel_key]["token_file"]


def channel_status():
    return [
        {"key": k, "label": v["label"], "connected": _token_path(k).exists()}
        for k, v in CHANNELS.items()
    ]


def choose_channel():
    """Terminal prompt, kept for upload_existing.py / main.py."""
    print("\nWhich channel should this post to?")
    for key, info in CHANNELS.items():
        print(f"  {key} - {info['label']}")
    choice = input("Enter channel: ").strip().upper()
    while choice not in CHANNELS:
        choice = input(f"Not recognized. Enter one of {', '.join(CHANNELS)}: ").strip().upper()
    return choice


def get_youtube_service(channel_key, log=print):
    """Authenticated YouTube client. First time per channel, a browser window
    opens on this computer for Google sign-in; after that the saved token is
    reused and refreshed automatically."""
    info = CHANNELS[channel_key]
    token_path = _token_path(channel_key)

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if os.environ.get("SPACE_ID") or os.environ.get("HOST", "127.0.0.1") != "127.0.0.1":
                raise RuntimeError(f"{info['label']} isn't signed in on the server. Connect it once on your own "
                                   f"computer, then copy {info['token_file']} into the YT_TOKEN_{channel_key} secret.")
            if not CLIENT_SECRET.exists():
                raise RuntimeError(f"client_secret.json is missing. Put it in this folder: {BASE_DIR}")
            log(f"A browser window is opening. Sign in with the Google account for {info['label']} "
                "and pick the right channel if that account has several.")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def fit_vertical(clip):
    """Resize+crop (cover fit) to TARGET_W x TARGET_H so output is always a proper
    vertical 9:16 frame."""
    clip = clip.resized(height=TARGET_H)
    if clip.w > TARGET_W:
        clip = clip.cropped(x_center=clip.w / 2, width=TARGET_W)
    elif clip.w < TARGET_W:
        clip = clip.resized(width=TARGET_W)
        if clip.h > TARGET_H:
            clip = clip.cropped(y_center=clip.h / 2, height=TARGET_H)
    return clip


def upload_short(video_path, title, description, tags, privacy_status, channel_key,
                 log=print, on_progress=None, publish_at=None):
    """Uploads video_path as a Short and returns its YouTube link."""
    info = CHANNELS[channel_key]
    log(f"Uploading to {info['label']} as {privacy_status}")

    if "#shorts" not in description.lower():
        description = f"{description}\n#Shorts".strip()

    youtube = get_youtube_service(channel_key, log=log)
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title[:100],  # YouTube's title limit
                "description": description,
                "tags": tags,
                "categoryId": "28",
            },
            # A scheduled video must be uploaded as private; YouTube makes it
            # public by itself at publish_at (ISO time, e.g. 2026-11-20T18:30:00Z).
            "status": ({"privacyStatus": "private", "publishAt": publish_at} if publish_at
                       else {"privacyStatus": privacy_status}),
        },
        media_body=MediaFileUpload(str(video_path), chunksize=4 * 1024 * 1024, resumable=True),
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and on_progress:
            on_progress(status.progress())

    url = f"https://youtube.com/shorts/{response['id']}"
    log(f"Uploaded to {info['label']}: {url}")
    return url
