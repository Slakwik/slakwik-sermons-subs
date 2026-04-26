"""GHA-side orchestrator: decides whether to run, pushes the Kaggle kernel,
waits for completion, pulls outputs, and stages them in the repo working tree.
The actual git commit + push is done by the workflow's next step."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
KERNEL_DIR = REPO_ROOT / "kaggle"
KERNEL_META = KERNEL_DIR / "kernel-metadata.json"
TRANSCRIPTS_DIR = REPO_ROOT / "transcripts"
VIDEOS_FILE = REPO_ROOT / "videos.yml"

POLL_SEC = 60
TIMEOUT_MIN = 300  # 5h — Kaggle script kernels run up to 9h


def align_kernel_owner_to_env() -> str:
    """Rewrite kernel-metadata.json so the kernel id owner matches the
    authenticated Kaggle user. Returns the resulting full id (user/slug)."""
    user = os.environ["KAGGLE_USERNAME"].strip()
    meta = json.loads(KERNEL_META.read_text())
    _old_user, slug = meta["id"].split("/", 1)
    meta["id"] = f"{user}/{slug}"
    KERNEL_META.write_text(json.dumps(meta, indent=2) + "\n")
    return meta["id"]


def kernel_slug() -> str:
    return json.loads(KERNEL_META.read_text())["id"]


def has_pending() -> bool:
    data = yaml.safe_load(VIDEOS_FILE.read_text()) or {}
    return any(v.get("status", "pending") == "pending" for v in data.get("videos", []))


def kaggle(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["kaggle", *args],
        check=True,
        text=True,
        capture_output=capture,
    )


def push_kernel() -> None:
    print("Pushing Kaggle kernel...")
    kaggle("kernels", "push", "-p", str(KERNEL_DIR))


def wait_for_completion(slug: str) -> str:
    deadline = time.time() + TIMEOUT_MIN * 60
    last = ""
    while time.time() < deadline:
        result = kaggle("kernels", "status", slug, capture=True)
        out = (result.stdout or "").strip()
        if out != last:
            print(out)
            last = out
        low = out.lower()
        if "complete" in low:
            return "complete"
        if any(t in low for t in ("error", "fail", "cancel")):
            return "error"
        time.sleep(POLL_SEC)
    raise TimeoutError(f"Kernel {slug} did not finish in {TIMEOUT_MIN} minutes")


def pull_outputs(slug: str) -> Path:
    tmp = REPO_ROOT / ".kaggle-out"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    print("Pulling kernel outputs...")
    kaggle("kernels", "output", slug, "-p", str(tmp))
    return tmp


def merge_outputs(tmp: Path) -> None:
    src_tr = tmp / "transcripts"
    if src_tr.is_dir():
        TRANSCRIPTS_DIR.mkdir(exist_ok=True)
        for f in src_tr.iterdir():
            if f.is_file():
                shutil.copy2(f, TRANSCRIPTS_DIR / f.name)
                print(f"  + transcripts/{f.name}")
    updated_yml = tmp / "videos.yml"
    if updated_yml.is_file():
        shutil.copy2(updated_yml, VIDEOS_FILE)
        print("  + videos.yml (updated statuses)")
    shutil.rmtree(tmp)


def main() -> int:
    if not has_pending():
        print("No pending videos — skipping Kaggle run.")
        return 0

    slug = align_kernel_owner_to_env()
    print(f"Kernel id: {slug}")
    push_kernel()
    state = wait_for_completion(slug)
    out = pull_outputs(slug)
    merge_outputs(out)

    if state == "error":
        print("Kernel finished with error state — see Kaggle logs.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
