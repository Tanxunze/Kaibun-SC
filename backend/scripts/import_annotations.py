"""Validate locally supplied image observations against the prepared batch manifests."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend")]

from paths import data_root
from asset_index import VERSION, atomic_json  # noqa: E402
from backgrounds import ANNOTATION_VERSION  # noqa: E402


def strings(value, name):
    values = value.get(name, [])
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise ValueError(f"{name}需要文字数组")
    return [item.strip()[:100] for item in values if item.strip()][:20]


def import_rows(adapter, kind, batch_manifest, document, model, batch=None):
    batches = batch_manifest["batches"]
    if batch is not None:
        batches = [item for item in batches if item["batch"] == batch]
    expected = {item["id"]: item for group in batches for item in group["items"]}
    key = "items" if kind == "wardrobe" else "backgrounds"
    rows = document.get(key)
    if not isinstance(rows, list):
        raise ValueError("标注结果缺少数组")
    mapped = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row["id"] not in expected or row["id"] in mapped:
            raise ValueError("标注结果中的图片编号重复或不在图册中")
        mapped[row["id"]] = row
    if set(mapped) != set(expected):
        raise ValueError("标注结果与这批图册编号不完全一致")
    writes = []
    for oid, row in mapped.items():
        original = expected[oid]
        if kind == "wardrobe":
            index = adapter.wardrobe.index
            digest = index.image_hash(oid)
            if not digest or digest != original["image_hash"]:
                raise ValueError("衣装图片已经改变，请先更新图册")
            if not isinstance(row.get("summary"), str) or not row["summary"].strip() or not isinstance(row.get("uncertain", False), bool):
                raise ValueError("衣装标注缺少外观说明或不确定标记")
            clean = dict(id=oid, image_hash=digest, version=VERSION, summary=row["summary"].strip()[:1200],
                         uncertain=row.get("uncertain", False), annotation_model=model)
            for name in ("colors", "tags", "occasion", "unknown"):
                clean[name] = strings(row, name)
            writes.append((index.path(oid), clean))
        else:
            path = adapter.backgrounds.image_path(oid)
            if path is None:
                raise ValueError("背景图片尚未下载")
            import hashlib
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != original["image_sha256"]:
                raise ValueError("背景图片已经改变，请先更新图册")
            if not isinstance(row.get("description"), str) or not row["description"].strip():
                raise ValueError("背景标注缺少画面描述")
            time = row.get("time_of_day", "unknown")
            if time not in ("day", "dusk", "night", "unknown"):
                raise ValueError("背景昼夜标签无效")
            clean = dict(id=oid, image_sha256=digest, annotation_version=ANNOTATION_VERSION, model=model,
                         description=row["description"].strip()[:700], label=str(row.get("label", ""))[:80],
                         tags=strings(row, "tags"), time_of_day=time, place_group=str(row.get("place_group", ""))[:80])
            writes.append((adapter.backgrounds.directory / "annotations" / f"{oid}.json", clean))
    for path, value in writes:
        atomic_json(path, value)
    return len(writes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("wardrobe", "backgrounds"))
    parser.add_argument("input", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--batch", type=int)
    parser.add_argument("--manifest", type=Path, help="Prepared review scope; defaults to index-batches.json")
    args = parser.parse_args()
    import asyncio
    import os
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    os.chdir(ROOT / "backend")
    from adapters import ProjectAdapter

    async def run():
        adapter = ProjectAdapter()
        try:
            folder = "wardrobe" if args.kind == "wardrobe" else "backgrounds"
            path = args.manifest or data_root() / folder / "index-batches.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            count = import_rows(adapter, args.kind, manifest, json.loads(args.input.read_text(encoding="utf-8")), args.model, args.batch)
            print(f"Imported {count} observations from {args.model}; no model request was made")
        finally:
            await adapter.close()
    asyncio.run(run())
