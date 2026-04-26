"""Kaggle script: pulls videos.yml from the public GitHub repo, transcribes
all entries with status=pending using faster-whisper large-v3 on GPU, and
writes per-video .txt and .srt plus an updated videos.yml into
/kaggle/working/ for the orchestrator to pick up via `kaggle kernels output`."""

import datetime
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

subprocess.run(
    [sys.executable, "-m", "pip", "install", "--quiet",
     "yt-dlp", "faster-whisper", "pyyaml"],
    check=True,
)

import yaml
from faster_whisper import WhisperModel

GH_USER = "Slakwik"
GH_REPO = "slakwik-sermons-subs"
RAW_VIDEOS = f"https://raw.githubusercontent.com/{GH_USER}/{GH_REPO}/main/videos.yml"

WORK = Path("/kaggle/working")
OUT_TR = WORK / "transcripts"
AUDIO_DIR = WORK / "audio"
OUT_TR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:60] or "untitled"


def fetch_videos() -> dict:
    with urllib.request.urlopen(RAW_VIDEOS, timeout=30) as r:
        data = yaml.safe_load(r.read()) or {}
    data.setdefault("videos", [])
    return data


def download_audio(url: str, slug: str) -> Path:
    out_template = str(AUDIO_DIR / f"{slug}.%(ext)s")
    subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "wav", "--no-playlist",
         "-o", out_template, url],
        check=True,
    )
    wavs = list(AUDIO_DIR.glob(f"{slug}.wav"))
    if not wavs:
        raise RuntimeError(f"yt-dlp did not produce a wav for {url}")
    return wavs[0]


def fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def transcribe(model: WhisperModel, audio: Path) -> tuple[str, str]:
    segments, _info = model.transcribe(
        str(audio),
        language="ru",
        vad_filter=True,
        beam_size=5,
    )
    segs = list(segments)
    text = "\n".join(s.text.strip() for s in segs).strip()
    srt_blocks = []
    for i, seg in enumerate(segs, 1):
        srt_blocks.append(
            f"{i}\n{fmt_ts(seg.start)} --> {fmt_ts(seg.end)}\n{seg.text.strip()}\n"
        )
    return text, "\n".join(srt_blocks)


def main() -> None:
    data = fetch_videos()
    pending = [v for v in data["videos"] if v.get("status", "pending") == "pending"]
    print(f"Pending: {len(pending)} of {len(data['videos'])} total")

    if not pending:
        # Still emit an updated videos.yml so the orchestrator has a stable artifact.
        (WORK / "videos.yml").write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return

    print("Loading faster-whisper large-v3 on GPU...")
    model = WhisperModel("large-v3", device="cuda", compute_type="float16")

    today = datetime.date.today().isoformat()
    for v in pending:
        url = v["url"]
        title = v.get("title") or url.rsplit("/", 1)[-1] or "video"
        slug = slugify(title)
        base = f"{today}-{slug}"
        try:
            print(f"\n=== {url} ===")
            audio = download_audio(url, slug)
            text, srt = transcribe(model, audio)
            (OUT_TR / f"{base}.txt").write_text(text, encoding="utf-8")
            (OUT_TR / f"{base}.srt").write_text(srt, encoding="utf-8")
            v["status"] = "done"
            v["transcript_path"] = f"transcripts/{base}.txt"
            v["srt_path"] = f"transcripts/{base}.srt"
            v.pop("error", None)
            audio.unlink(missing_ok=True)
        except Exception as exc:
            print(f"FAILED {url}: {exc}", file=sys.stderr)
            v["status"] = "error"
            v["error"] = str(exc)

    (WORK / "videos.yml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


main()
