"""Download selected background ids or backgrounds referenced by cached scripts, one request at a time."""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from paths import load_environment, data_root
load_environment()
BG_ID = re.compile(r"\d{5}\Z")
SOURCE = "https://viewer.shinycolors.moe/images/event/bg/"


def referenced_backgrounds(scripts):
    refs = {}
    for path in sorted(Path(scripts).rglob("*.json")):
        try:
            frames = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(frames, dict):
            frames = frames.get("frames", frames.get("data", []))
        if not isinstance(frames, list):
            continue
        for index, frame in enumerate(frames):
            if not isinstance(frame, dict):
                continue
            bid = frame.get("bg")
            if isinstance(bid, str) and BG_ID.fullmatch(bid):
                row = refs.setdefault(bid, {"count": 0, "scripts": []})
                row["count"] += 1
                reference = path.relative_to(scripts).as_posix()
                if reference not in row["scripts"]:
                    row["scripts"].append(reference)
    return refs


def save_manifest(directory, manifest):
    target = directory / "manifest.json"
    temp = target.with_suffix(".json.part")
    temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)


def describe_image(path, thumbnail):
    with Image.open(path) as source:
        source.load()
        width, height = source.size
        image = source.convert("RGB")
        probe = image.resize((16, 16))
        deviation = max(ImageStat.Stat(probe).stddev)
        kind = "solid" if deviation < 2.0 else "scene"
        image.thumbnail((568, 320))
        thumbnail.parent.mkdir(parents=True, exist_ok=True)
        image.save(thumbnail, "WEBP", quality=85)
    return dict(width=width, height=height, type=kind)


def download(scripts, directory, interval=1.1, limit=None, ids=None):
    scripts, directory = Path(scripts).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "originals").mkdir(exist_ok=True)
    (directory / "thumbnails").mkdir(exist_ok=True)
    manifest_path = directory / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {"version": 1, "source": SOURCE, "items": {}}
    refs = referenced_backgrounds(scripts) if ids is None else {bid: {'count': 1, 'scripts': ['manual-selection']} for bid in ids}
    if not refs:
        raise ValueError('未找到背景编号，请提供有效的 --scripts 目录，或使用 --ids 指定5位编号')
    for bid, reference in refs.items():
        manifest["items"].setdefault(bid, {}).update(id=bid, source_url=SOURCE + bid + ".jpg", references=reference)
    manifest.update(download_complete=False, referenced_count=len(refs), stopped_reason=None)
    save_manifest(directory, manifest)
    done = missing = fetched = 0
    last_request = 0.0
    with httpx.Client(timeout=httpx.Timeout(35, connect=15), follow_redirects=True,
                      headers={"User-Agent": "kaibun local background sync (one request per second)"},
                      limits=httpx.Limits(max_connections=1, max_keepalive_connections=1)) as client:
        for bid in sorted(refs):
            item = manifest["items"][bid]
            target = directory / "originals" / f"{bid}.jpg"
            thumbnail = directory / "thumbnails" / f"{bid}.webp"
            if target.is_file() and item.get("sha256") == hashlib.sha256(target.read_bytes()).hexdigest():
                if not thumbnail.is_file():
                    item.update(describe_image(target, thumbnail))
                done += 1
                continue
            if item.get("status") == "missing":
                missing += 1
                continue
            if limit is not None and fetched >= limit:
                manifest["stopped_reason"] = "requested_limit"
                break
            response = None
            for attempt in range(3):
                time.sleep(max(0, interval - (time.monotonic() - last_request)))
                last_request = time.monotonic()
                try:
                    response = client.get(item["source_url"])
                except httpx.HTTPError:
                    if attempt == 2:
                        manifest["stopped_reason"] = "network_error"
                    else:
                        time.sleep(3 * (attempt + 1))
                    continue
                if response.status_code in (401, 403, 429):
                    manifest["stopped_reason"] = f"HTTP {response.status_code}"
                    break
                if response.status_code >= 500:
                    if attempt == 2:
                        manifest["stopped_reason"] = f"HTTP {response.status_code}"
                    else:
                        time.sleep(3 * (attempt + 1))
                    continue
                break
            if manifest["stopped_reason"]:
                save_manifest(directory, manifest)
                print(f"STOP {manifest['stopped_reason']} downloaded={done} missing={missing}", flush=True)
                return False
            if response.status_code == 404:
                item.update(status="missing", http_status=404, checked_at=datetime.now(timezone.utc).isoformat())
                missing += 1
            elif response.status_code == 200 and response.headers.get("content-type", "").startswith("image/"):
                part = target.with_suffix(".jpg.part")
                part.write_bytes(response.content)
                try:
                    metadata = describe_image(part, thumbnail)
                except Exception:
                    part.unlink(missing_ok=True)
                    manifest["stopped_reason"] = f"invalid_image:{bid}"
                    save_manifest(directory, manifest)
                    print(f"STOP invalid_image {bid}", flush=True)
                    return False
                part.replace(target)
                item.update(metadata, status="downloaded", etag=response.headers.get("etag"),
                            sha256=hashlib.sha256(response.content).hexdigest(), bytes=len(response.content),
                            downloaded_at=datetime.now(timezone.utc).isoformat())
                done += 1
                fetched += 1
            else:
                manifest["stopped_reason"] = f"unexpected_HTTP:{response.status_code}"
                save_manifest(directory, manifest)
                print(f"STOP unexpected response {response.status_code} for {bid}", flush=True)
                return False
            save_manifest(directory, manifest)
            if (done + missing) % 20 == 0:
                print(f"PROGRESS {done + missing}/{len(refs)} downloaded={done} missing={missing} last={bid}", flush=True)
        else:
            manifest["download_complete"] = True
    manifest.update(downloaded_count=done, missing_count=missing, updated_at=datetime.now(timezone.utc).isoformat())
    save_manifest(directory, manifest)
    print(f"FINISHED complete={manifest['download_complete']} downloaded={done} missing={missing} new={fetched}", flush=True)
    return manifest["download_complete"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scripts", type=Path, default=ROOT / "corpus" / "mirror" / "scripts")
    parser.add_argument('--ids', nargs='+', help='Download specific 5-digit background ids without a script corpus')
    parser.add_argument("--directory", type=Path, default=data_root() / "backgrounds")
    parser.add_argument("--interval", type=float, default=1.1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--prepare-index", action="store_true", help="Only annotate already downloaded common images; makes model calls")
    args = parser.parse_args()
    if args.ids and any(not BG_ID.fullmatch(bid) for bid in args.ids):
        parser.error('--ids 每一项必须是5位背景编号')
    if args.prepare_index:
        import asyncio

        sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend")]
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        from adapters import ProjectAdapter
        from backgrounds import Backgrounds

        async def prepare_index():
            import os

            os.chdir(ROOT / "backend")
            adapter = ProjectAdapter()
            try:
                await Backgrounds(adapter, args.directory).index_common(args.limit or 30)
            finally:
                await adapter.close()

        asyncio.run(prepare_index())
    else:
        if not args.ids and not args.scripts.is_dir():
            parser.error('剧情缓存目录不存在；使用 --scripts 指定目录，或用 --ids 指定背景编号')
        sys.exit(0 if download(args.scripts, args.directory, max(1.0, args.interval), args.limit, args.ids) else 2)
