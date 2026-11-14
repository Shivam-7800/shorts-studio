"""
Terminal version — same pipeline as the web app, for when you want the old
question-and-answer flow.   python main.py
For the web UI, run:        python app.py
"""

import os
import uuid

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import pipeline
from yt_common import choose_channel, upload_short


def main():
    topic = input("\nEnter Video Topic: ").strip()
    codes = list(pipeline.LANGUAGES)
    print("\nChoose script language:")
    for i, code in enumerate(codes, 1):
        print(f"  {i}. {pipeline.LANGUAGES[code]['label']}")
    pick = input("Enter number: ").strip()
    language = codes[int(pick) - 1] if pick.isdigit() and 1 <= int(pick) <= len(codes) else "en-IN"
    gender = "male" if input("Voice: (f)emale or (m)ale? ").strip().lower().startswith("m") else "female"

    script = pipeline.generate_script(topic, language, log=print)
    print("\n================ SCRIPT ================\n" + script + "\n")

    result = pipeline.build_video(uuid.uuid4().hex[:12], topic, language, gender, script,
                                  log=print, step=lambda s: print(f"\n== {s} =="))
    path = pipeline.VIDEOS_DIR / result["video"]
    print(f"\nVideo saved at: {path}\nWatch it before deciding.\n")

    if input("Upload to YouTube now? y/n: ").strip().lower() != "y":
        print("Skipping upload. The file stays local.")
        return
    channel = choose_channel()
    mapping = {"1": "private", "2": "unlisted", "3": "public"}
    privacy = mapping.get(input("Publish as (1) private (2) unlisted (3) public: ").strip(), "private")
    tags = result["hashtags"]
    upload_short(path, topic, " ".join(f"#{t}" for t in tags), tags, privacy, channel)
    print("\nDONE!")


if __name__ == "__main__":
    main()
