"""Persistent observations of local wardrobe images; no network until explicitly indexed."""

import base64
import hashlib
import json
import re
import uuid
from pathlib import Path
from outfit_policy import automatic_outfit

VERSION = "wardrobe-observations-v1"


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def provider_id(adapter):
    settings = getattr(adapter, "settings", None)
    # Credentials never enter files or cache identities.
    signature = [getattr(settings, key, "") for key in ("protocol", "base_url", "model")]
    if not signature[-1]:
        signature[-1] = getattr(adapter, "model", "")
    return hashlib.sha256(json.dumps(signature).encode()).hexdigest()[:24]


def parse_object(text):
    return json.JSONDecoder().raw_decode(text[text.index("{"):])[0]


class OutfitIndex:
    def __init__(self, wardrobe):
        self.wardrobe = wardrobe
        self.root = wardrobe.directory / "annotations" / provider_id(wardrobe.adapter)
        self._hashes = {}

    def image_hash(self, oid):
        path = self.wardrobe.thumbnail_path(oid)
        if not path:
            return None
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        if key not in self._hashes:
            self._hashes[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        return self._hashes[key]

    def path(self, oid):
        digest = self.image_hash(oid)
        if not digest:
            return None
        key = hashlib.sha256((VERSION + oid + digest).encode()).hexdigest()
        return self.root / (key + ".json")

    def read(self, oid):
        path = self.path(oid)
        if not path:
            return None
        # Observations describe an image, and remain valid after changing selector models.
        paths = [path, *[p for p in (self.wardrobe.directory / 'annotations').glob('*/' + path.name) if p != path]]
        for candidate in paths:
            try:
                row = json.loads(candidate.read_text(encoding='utf-8'))
                if row.get('id') == oid and row.get('image_hash') == self.image_hash(oid) and row.get('version') == VERSION:
                    return row
            except (OSError, ValueError, AttributeError):
                continue
        return None

    async def annotate(self, ids, batch_size=10):
        """Observe already prepared images in small batches. Caller explicitly authorizes this stage."""
        if not 1 <= batch_size <= 48:
            raise ValueError("索引批次需要1至48张图片，每页最多12张")
        ids = list(dict.fromkeys(ids))
        if any(oid not in self.wardrobe.entries or not self.wardrobe.thumbnail_path(oid) for oid in ids):
            raise ValueError("请先完成本地服装图片准备")
        # Visual facts remain valid across selection-model changes when the source image matches.
        for oid in ids:
            if self.read(oid): continue
            target = self.path(oid)
            if target is None: continue
            for candidate in (self.wardrobe.directory / 'annotations').glob('*/' + target.name):
                try:
                    row = json.loads(candidate.read_text(encoding='utf-8'))
                    if row.get('id') == oid and row.get('image_hash') == self.image_hash(oid) and row.get('version') == VERSION:
                        atomic_json(target, row)
                        break
                except (OSError, ValueError): pass
        pending = [oid for oid in ids if not self.read(oid)]
        for offset in range(0, len(pending), batch_size):
            group = pending[offset:offset + batch_size]
            options = [dict(id=oid, label=self.wardrobe.entries[oid].get("dressName", oid)) for oid in group]
            paths = [self.wardrobe.thumbnail_path(oid) for oid in group]
            sheets = self.wardrobe._contact_sheets("index-" + VERSION, options, paths)
            payload = dict(items=[dict(id=oid, image_hash=self.image_hash(oid)) for oid in group])
            for attempt in range(2):
                reply = await self.wardrobe.adapter.complete_with_images(
                    "请观察这批本地角色服装预览，为每张图片记录可见外观。按图中完整id对应，原样返回image_hash。"
                    "summary描述上衣、可见下装、配饰、款式；colors、tags、occasion填写简短列表。"
                    "图片未显示或无法判断的信息留空，画面下缘之外的裙摆、鞋袜与身体部分保持未知。"
                    '只输出JSON：{"items":[{"id":"完整衣装id","image_hash":"原样hash","summary":"观察描述",'
                    '"colors":[],"tags":[],"occasion":[],"unknown":[],"uncertain":false}]}。'
                    "缩略图难以看清重要服装细节时uncertain填true。",
                    json.dumps({**payload, **({"format_repair": "完整返回上述items，每个id和image_hash逐字一致，列表字段用数组。"} if attempt else {})}, ensure_ascii=False),
                    ["data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode() for p in sheets])
                try:
                    rows = parse_object(reply)["items"]
                    if not isinstance(rows, list) or len(rows) != len(group):
                        raise ValueError()
                    checked = {}
                    for row in rows:
                        oid = row.get("id")
                        if oid not in group or oid in checked or row.get("image_hash") != self.image_hash(oid):
                            raise ValueError()
                        if not isinstance(row.get("summary"), str) or not row["summary"].strip():
                            raise ValueError()
                        clean = dict(id=oid, image_hash=row["image_hash"], version=VERSION, summary=row["summary"].strip()[:1200])
                        if not isinstance(row.get("uncertain", False), bool):
                            raise ValueError()
                        clean.update(uncertain=row.get("uncertain", False), page=next(
                            dict(file=str(sheets[n // 12]), slot=n % 12 + 1)
                            for n, candidate in enumerate(group) if candidate == oid))
                        for name in ("colors", "tags", "occasion", "unknown"):
                            values = row.get(name, [])
                            if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                                raise ValueError()
                            clean[name] = [v.strip()[:100] for v in values[:20] if v.strip()]
                        checked[oid] = clean
                    if set(checked) != set(group):
                        raise ValueError()
                except (ValueError, KeyError, TypeError, AttributeError):
                    if attempt:
                        raise ValueError("服装图册标注缺少正确id、图片hash或外观记录，可以重试") from None
                    continue
                break
            # The complete batch validates before any annotation becomes visible.
            for oid, row in checked.items():
                atomic_json(self.path(oid), row)
            print(f"OUTFIT INDEX {offset + len(group)}/{len(pending)} newly annotated", flush=True)
        return [self.read(oid) for oid in ids]

    def candidates(self, cid, context, limit=8, required=()):
        rows = [self.read(oid) for oid in self.wardrobe.by_character.get(cid, [])]
        rows = [row for row in rows if row and automatic_outfit(row['id'])]
        terms = set(re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]{2,}", context.lower()))
        terms |= {term[i:i + 2] for term in list(terms) for i in range(len(term) - 1)}
        default = self.wardrobe.adapter.characters[cid].default_outfit
        required = list(dict.fromkeys([*required, default]))

        def rank(row):
            text = " ".join([row["summary"], *row["tags"], *row["colors"], *row["occasion"]]).lower()
            priority = len(required) - required.index(row["id"]) if row["id"] in required else 0
            return (priority, sum(term in text for term in terms))

        rows.sort(key=rank, reverse=True)
        return [dict(id=row["id"], summary=row["summary"], colors=row["colors"], tags=row["tags"], occasion=row["occasion"], unknown=row["unknown"], uncertain=row.get("uncertain", False)) for row in rows[:limit]]

    async def clarify(self, ids):
        """Recheck at most four uncertain candidates against clear rendered stands."""
        ids = list(dict.fromkeys(ids))[:4]
        rows = [self.read(oid) for oid in ids]
        ids = [row["id"] for row in rows if row and row.get("uncertain")]
        if not ids:
            return
        await self.wardrobe._render(ids, high_resolution=True)
        paths = [self.wardrobe.directory / "details" / "thumbnails" / (oid + ".png") for oid in ids]
        if any(not path.is_file() for path in paths):
            raise ValueError("清晰服装预览未能完成，可以重试")
        reply = await self.wardrobe.adapter.complete_with_images(
            "请逐张复核清晰角色立绘，依据实际可见服装修正summary、colors、tags、occasion、unknown。"
            "每张图与输入items顺序对应，id和image_hash原样返回；仍不确定填写uncertain:true。"
            "画面外的鞋袜、裙摆与下半身继续列为unknown。"
            '输出JSON：{"items":[{"id":"...","image_hash":"...","summary":"...",'
            '"colors":[],"tags":[],"occasion":[],"unknown":[],"uncertain":false}]}。',
            json.dumps(dict(items=[self.read(oid) for oid in ids]), ensure_ascii=False),
            ["data:image/png;base64," + base64.b64encode(path.read_bytes()).decode() for path in paths])
        data = parse_object(reply).get("items")
        if not isinstance(data, list) or len(data) != len(ids):
            raise ValueError("清晰服装复核返回不完整")
        checked = {}
        for row in data:
            oid = row.get("id")
            if oid not in ids or oid in checked or row.get("image_hash") != self.image_hash(oid):
                raise ValueError("清晰服装复核图片对应有误")
            if not isinstance(row.get("summary"), str) or not row["summary"].strip() or not isinstance(row.get("uncertain"), bool):
                raise ValueError("清晰服装复核缺少观察描述")
            old = self.read(oid)
            old.update(summary=row["summary"].strip()[:1200], uncertain=row["uncertain"], detail_file=str(paths[ids.index(oid)]))
            for key in ("colors", "tags", "occasion", "unknown"):
                if not isinstance(row.get(key), list) or any(not isinstance(value, str) for value in row[key]):
                    raise ValueError("清晰服装复核标签格式有误")
                old[key] = [value[:100] for value in row[key][:20]]
            checked[oid] = old
        for oid, row in checked.items():
            atomic_json(self.path(oid), row)
