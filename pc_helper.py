"""
PC helper for the website's Remake / React links (Instagram, Facebook, etc.).

Those sites block servers like GitHub but not your own internet. This script
runs on your PC, watches your repo for links you paste on the website,
downloads the sound here, and hands it to GitHub, which writes the script.

Run:   python pc_helper.py      (leave the window open)
First run asks for your GitHub token (Contents + Actions: Read and write)
and saves it in .env. Press Ctrl+C to stop.
"""
import base64
import json
import os
import tempfile
import time
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent
ENV = BASE / ".env"
API = "https://api.github.com"
POLL_SECONDS = 10
MAX_AGE_SECONDS = 15 * 60  # ignore requests older than this (e.g. made while the PC was off)


def load_settings():
    values = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    changed = False
    if not values.get("GH_REPO"):
        values["GH_REPO"] = input("Your repo (for example Shivam-7800/shorts-studio): ").strip()
        changed = True
    if not values.get("GH_HELPER_TOKEN"):
        values["GH_HELPER_TOKEN"] = input("Paste your GitHub token (github_pat_...): ").strip()
        changed = True
    if changed:
        lines = [l for l in (ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else [])
                 if l.split("=", 1)[0].strip() not in ("GH_REPO", "GH_HELPER_TOKEN")]
        lines += [f"GH_REPO={values['GH_REPO']}", f"GH_HELPER_TOKEN={values['GH_HELPER_TOKEN']}"]
        ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("Saved to .env")
    return values["GH_REPO"], values["GH_HELPER_TOKEN"]


class GitHub:
    def __init__(self, repo, token):
        self.repo = repo
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                               "X-GitHub-Api-Version": "2022-11-28"})

    def call(self, method, path, **kw):
        r = self.s.request(method, f"{API}/repos/{self.repo}{path}", timeout=60, **kw)
        if r.status_code in (401, 403):
            raise SystemExit("GitHub refused the token. It needs Contents and Actions: Read and write. "
                             "Delete GH_HELPER_TOKEN from .env and run again with a new token.")
        return r

    def pending_requests(self):
        ref = self.call("GET", "/git/ref/heads/uploads")
        if ref.status_code == 404:
            return []
        commit = self.call("GET", f"/git/commits/{ref.json()['object']['sha']}").json()
        tree = self.call("GET", f"/git/trees/{commit['tree']['sha']}", params={"recursive": "1"}).json()
        folders = {}
        for item in tree.get("tree", []):
            parts = item["path"].split("/")
            if len(parts) == 3 and parts[0] == "uploads":
                folders.setdefault(parts[1], {})[parts[2]] = item["sha"]
        return [(fid, files["request.json"]) for fid, files in folders.items()
                if "request.json" in files and not any(n.startswith("media.") for n in files)]

    def read_blob(self, sha):
        return base64.b64decode(self.call("GET", f"/git/blobs/{sha}").json()["content"])

    def add_file(self, path, data):
        blob = self.call("POST", "/git/blobs", json={"content": base64.b64encode(data).decode(), "encoding": "base64"})
        blob.raise_for_status()
        for _ in range(5):  # retry if the website uploaded something at the same moment
            head = self.call("GET", "/git/ref/heads/uploads").json()["object"]["sha"]
            base_tree = self.call("GET", f"/git/commits/{head}").json()["tree"]["sha"]
            tree = self.call("POST", "/git/trees", json={"base_tree": base_tree, "tree": [
                {"path": path, "mode": "100644", "type": "blob", "sha": blob.json()["sha"]}]}).json()
            commit = self.call("POST", "/git/commits", json={"message": "pc helper", "tree": tree["sha"],
                                                              "parents": [head]}).json()
            if self.call("PATCH", "/git/refs/heads/uploads", json={"sha": commit["sha"]}).ok:
                return
            time.sleep(2)
        raise RuntimeError("couldn't save the file to GitHub")

    def start_writer(self, req, upload_id, error=""):
        inputs = {"mode": req.get("mode", "remake"), "language": req.get("language", "hi-IN"),
                  "upload_id": upload_id, "request_id": req.get("request_id", ""),
                  "context": f"HELPER_ERROR: {error}" if error else ""}
        r = self.call("POST", "/actions/workflows/ai-text.yml/dispatches", json={"ref": "main", "inputs": inputs})
        if not r.ok:
            print("  Couldn't start GitHub:", r.status_code, r.text[:200])


def download_audio(url):
    import yt_dlp
    tmp = Path(tempfile.mkdtemp())
    opts = {"format": "bestaudio/best", "outtmpl": str(tmp / "media.%(ext)s"), "quiet": True,
            "noplaylist": True, "match_filter": yt_dlp.utils.match_filter_func("duration < 1200")}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)
    files = sorted((f for f in tmp.iterdir() if f.stat().st_size > 0), key=lambda f: f.stat().st_size, reverse=True)
    if not files:
        raise RuntimeError("the site sent an empty file (the video may be private or need a login)")
    if files[0].stat().st_size > 90 * 1024 * 1024:
        raise RuntimeError("the video is too big (over 90 MB)")
    return files[0]


def main():
    repo, token = load_settings()
    gh = GitHub(repo, token)
    print(f"PC helper is running for {repo}. Leave this window open. (Ctrl+C to stop)")
    done = set()
    while True:
        try:
            for upload_id, sha in gh.pending_requests():
                if upload_id in done:
                    continue
                done.add(upload_id)
                req = json.loads(gh.read_blob(sha))
                if time.time() - req.get("created", 0) / 1000 > MAX_AGE_SECONDS:
                    continue  # stale request, skip
                print(f"Link received: {req.get('url')}")
                try:
                    path = download_audio(req["url"])
                    print(f"  Downloaded ({path.stat().st_size // 1024} KB), sending to GitHub")
                    gh.add_file(f"uploads/{upload_id}/media{path.suffix}", path.read_bytes())
                    gh.start_writer(req, upload_id)
                    print("  Done. The script will appear on the website in about a minute.")
                except Exception as e:
                    msg = str(e).splitlines()[0][:200]
                    print("  Failed:", msg)
                    gh.start_writer(req, upload_id, error=f"Your PC couldn’t download that link: {msg}. "
                                                          "Save the video and use “Upload the video” instead.")
        except SystemExit:
            raise
        except Exception as e:
            print("Connection problem, retrying:", str(e)[:150])
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
