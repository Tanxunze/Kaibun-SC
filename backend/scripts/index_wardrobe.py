"""Separate local image preparation and explicitly requested visual indexing stages."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend"))

from paths import load_environment
load_environment()
from adapters import ProjectAdapter
from asset_index import atomic_json


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare-images", action="store_true")
    parser.add_argument("--index", action="store_true", help="Send prepared contact sheets to the configured model")
    parser.add_argument("--all", action="store_true", help="Prepare the entire local wardrobe")
    parser.add_argument("--character", action="append", default=[])
    parser.add_argument("--batch-size", type=int, default=12)
    args = parser.parse_args()
    if not args.prepare_images and not args.index:
        parser.error("Choose --prepare-images or --index")
    adapter = ProjectAdapter()
    wardrobe = adapter.wardrobe
    selected = args.character or list(wardrobe.by_character)
    ids = list(dict.fromkeys(oid for cid in selected for oid in wardrobe.by_character.get(cid, []))) if args.all or args.character else wardrobe.initial_images()
    report = dict(total=len(ids), prepared=0, failed=[], pages=[])
    try:
        if args.prepare_images:
            missing = [oid for oid in ids if not wardrobe.thumbnail_path(oid)]
            for offset in range(0, len(missing), 128):
                group = missing[offset:offset + 128]
                try:
                    await wardrobe._render(group)
                except Exception as error:
                    print("render batch", offset, type(error).__name__, flush=True)
                report["prepared"] = sum(bool(wardrobe.thumbnail_path(oid)) for oid in ids)
                report["failed"] = [oid for oid in missing[:offset + len(group)] if not wardrobe.thumbnail_path(oid)]
                atomic_json(wardrobe.directory / "prepare-progress.json", report)
                print(json.dumps(dict(prepared=report["prepared"], total=len(ids), failed=len(report["failed"])), ensure_ascii=False), flush=True)
            for cid in selected:
                choices = [wardrobe.outfit(cid, oid) for oid in ids if oid in wardrobe.by_character.get(cid, []) and wardrobe.thumbnail_path(oid)]
                pages = wardrobe._contact_sheets(cid, choices, [wardrobe.thumbnail_path(item["id"]) for item in choices])
                report["pages"].extend(dict(character=cid, page=i, file=str(path), ids=[item["id"] for item in choices[i * 12:i * 12 + 12]]) for i, path in enumerate(pages))
            report["prepared"] = sum(bool(wardrobe.thumbnail_path(oid)) for oid in ids)
            report["failed"] = [oid for oid in ids if not wardrobe.thumbnail_path(oid)]
            atomic_json(wardrobe.directory / "page.index.json", report)
            print(json.dumps(dict(stage="images", total=len(ids), prepared=report["prepared"], failed=report["failed"], pages=len(report["pages"])), ensure_ascii=False), flush=True)
        if args.index:
            if any(not wardrobe.thumbnail_path(oid) for oid in ids):
                raise ValueError("Complete --prepare-images before --index")
            await wardrobe.index.annotate(ids, batch_size=args.batch_size)
            counts = {cid: sum(wardrobe.index.read(oid) is not None for oid in ids if oid in wardrobe.by_character.get(cid, [])) for cid in selected}
            print(json.dumps(dict(stage="indexed", total=sum(counts.values()), characters=counts), ensure_ascii=False), flush=True)
    finally:
        await adapter.close()


if __name__ == "__main__":
    asyncio.run(main())
