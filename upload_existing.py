"""
Convert an existing video file into a vertical (9:16) Short and upload it.

Use this for videos you already have — filmed separately, downloaded, edited
elsewhere — that you now want on your channel as a Short. It does NOT touch
Gemini, Pexels, or edge-tts at all; it just reframes your video and uploads it.

Run:
    python upload_existing.py
"""

import os
from datetime import datetime

from moviepy import VideoFileClip

from yt_common import fit_vertical, choose_channel, upload_short, SHORTS_MAX_SECONDS

os.makedirs("videos", exist_ok=True)


def main():
    source_path = input("\nPath to your existing video file: ").strip().strip('"')
    if not os.path.exists(source_path):
        raise SystemExit(f"File not found: {source_path}")

    clip = VideoFileClip(source_path)
    print(f"Loaded: {clip.w}x{clip.h}, {clip.duration:.1f}s")

    if clip.duration > SHORTS_MAX_SECONDS:
        print(f"This is longer than YouTube's {SHORTS_MAX_SECONDS}s Shorts limit.")
        trim_choice = input(f"Trim to the first {SHORTS_MAX_SECONDS}s? y/n: ").strip().lower()
        if trim_choice == "y":
            clip = clip.subclipped(0, SHORTS_MAX_SECONDS)
        else:
            print("Keeping full length — note it may upload as a regular video, not a Short.")

    print("Reframing to vertical 9:16 (cropping to fill, not stretching)...")
    vertical_clip = fit_vertical(clip)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.splitext(os.path.basename(source_path))[0].replace(" ", "_")
    output_path = f"videos/{base_name}_short_{timestamp}.mp4"

    print("\nRendering vertical version...")
    vertical_clip.write_videofile(output_path, fps=24)

    print("\nVIDEO SAVED LOCALLY")
    print(os.path.abspath(output_path))
    print("Open and watch it now before deciding what to do next.\n")

    choice = input("Upload to YouTube now? y/n: ").strip().lower()
    if choice != "y":
        print("Skipping upload. The file stays local — upload manually whenever you're ready.")
        return

    channel_key = choose_channel()
    title = input("Title for this video: ").strip() or base_name.replace("_", " ")
    description = input("Description (leave blank for none): ").strip()

    visibility = input("Publish as (1) private (2) unlisted (3) public — enter 1/2/3: ").strip()
    mapping = {"1": "private", "2": "unlisted", "3": "public"}
    privacy_status = mapping.get(visibility, "private")
    if visibility not in mapping:
        print("Unrecognized choice — defaulting to 'private' to be safe.")

    upload_short(
        video_path=output_path,
        title=title,
        description=description,
        tags=["shorts"],
        privacy_status=privacy_status,
        channel_key=channel_key,
    )

    print("\nDONE!")


if __name__ == "__main__":
    main()
