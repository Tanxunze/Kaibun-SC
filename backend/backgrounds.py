"""Local game background catalog and persistent image annotations for story staging."""

import asyncio
import base64
import hashlib
import json
import re
import logging
from io import BytesIO
from pathlib import Path

from asset_index import provider_id
from paths import data_root


class BackgroundError(ValueError):
    """Locally written, safe explanation for story presentation failures."""


BG_ID = re.compile(r"\d{5}\Z")
ANNOTATION_VERSION = 1
SELECTION_VERSION = 5
log = logging.getLogger(__name__)


def place_terms(place):
    groups = (("摄影", "拍摄", "影棚", "撮影", "スタジオ"),
              ("医院", "病房", "住院", "病院", "病室"),
              ("烹饪", "料理", "家政"), ("教室", "图书角", "座位", "自习"),
              ("走廊", "楼梯"), ("教职员室", "职员室", "办公室", "办公区", "事务所"),
              ("中庭", "长椅", "庭院", "公园"), ("校门", "学校外景", "校舍", "操场"),
              ("放学路", "住宅街", "街道", "商业街"), ("练习室", "舞蹈", "训练室"))
    for group in groups:
        if any(word in place for word in group):
            return group
    return ()


def scene_time(place):
    if any(word in place for word in ("深夜", "夜间", "晚上", "夜晚")):
        return "night"
    if any(word in place for word in ("夕阳", "黄昏", "傍晚", "夕方")):
        return "dusk"
    if any(word in place for word in ("早", "午", "白天", "班会", "课间", "自习")):
        return "day"
    return "unknown"


def location_cues(scene):
    words = ("走进", "走出", "来到", "离开", "回到", "校门", "教室", "走廊", "职员室", "中庭", "长椅", "天台", "图书", "街道", "夕阳", "天色", "太阳", "夜色")
    lines = scene.get("lines", [])
    selected = [line for line in lines if any(word in line.get("zh", "") for word in words)]
    if not selected:
        selected = lines[:1]
    return [dict(id=line["id"], location_text=line.get("zh", "")[:160]) for line in selected[:10]]


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    part.replace(path)


def response_object(text):
    try:
        value, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
    except (ValueError, TypeError):
        raise BackgroundError("背景选择结果格式有误，可以继续重试") from None
    if not isinstance(value, dict):
        raise BackgroundError("背景选择结果格式有误，可以继续重试")
    return value


class Backgrounds:
    def __init__(self, adapter, directory=None):
        self.adapter = adapter
        self.directory = Path(directory or data_root() / 'backgrounds').resolve()
        self._index_lock = asyncio.Lock()
        self._manifest_stamp = None
        self._manifest_cache = {}
        self._catalog_stamp = None
        self._catalog_cache = []

    def import_image(self, data, label, description='', tags=None, time_of_day='unknown'):
        """Register a local image using the same catalog as playback and export."""
        from PIL import Image, ImageOps, UnidentifiedImageError

        label = label.strip()
        if not label or len(data) > 10 * 1024 * 1024:
            raise BackgroundError('请填写名称，并选择10MB以内的图片')
        try:
            with Image.open(BytesIO(data)) as source:
                if source.format not in ('PNG', 'JPEG', 'WEBP') or source.width * source.height > 25000000:
                    raise BackgroundError('请选择2500万像素以内的 PNG、JPG 或 WebP 图片')
                image = ImageOps.exif_transpose(source).convert('RGB')
                width, height = image.size
                output = BytesIO()
                image.save(output, 'JPEG', quality=95)
                original = output.getvalue()
                image.thumbnail((568, 320))
                thumb = BytesIO()
                image.save(thumb, 'WEBP', quality=85)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
            raise BackgroundError('无法读取图片，请选择有效的 PNG、JPG 或 WebP 文件') from None
        digest = hashlib.sha256(original).hexdigest()
        manifest = json.loads(json.dumps(self._manifest()))
        items = manifest.setdefault('items', {})
        existing = next((bid for bid, item in items.items() if item.get('custom') and item.get('sha256') == digest), None)
        if existing:
            return self.card(existing)
        bid = next((f'{i:05}' for i in range(90000, 99999) if f'{i:05}' not in items), None)
        if not bid:
            raise BackgroundError('自定义背景数量已达上限')
        for folder, content, suffix in [('originals', original, '.jpg'), ('thumbnails', thumb.getvalue(), '.webp')]:
            path = self.directory / folder / (bid + suffix)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        items[bid] = dict(id=bid, custom=True, status='downloaded', sha256=digest, bytes=len(original), width=width, height=height, type='scene', references=dict(count=0, scripts=[]))
        save_json(self.directory / 'annotations' / (bid + '.json'), dict(id=bid, image_sha256=digest, annotation_version=ANNOTATION_VERSION, label=label[:80], description=description.strip()[:700] or label[:80], tags=list(dict.fromkeys(t.strip()[:40] for t in (tags or []) if t.strip()))[:20], time_of_day=time_of_day, place_group=label[:80], model='user'))
        save_json(self.directory / 'manifest.json', manifest)
        self._catalog_stamp = None
        return self.card(bid)

    def _manifest(self):
        path = self.directory / "manifest.json"
        try:
            stamp = (path.stat().st_mtime_ns, path.stat().st_size)
        except OSError:
            return {}
        if stamp != self._manifest_stamp:
            manifest = read_json(path, {})
            self._manifest_cache = manifest if isinstance(manifest, dict) else {}
            self._manifest_stamp = stamp
        return self._manifest_cache

    def _items(self):
        return self._manifest().get("items", {})

    def image_path(self, bid, thumbnail=False):
        if not isinstance(bid, str) or not BG_ID.fullmatch(bid):
            return None
        item = self._items().get(bid)
        if not item or item.get("status") != "downloaded":
            return None
        path = self.directory / ("thumbnails" if thumbnail else "originals") / (bid + (".webp" if thumbnail else ".jpg"))
        return path if path.is_file() and path.stat().st_size > 0 else None

    def _annotation(self, bid, item):
        value = read_json(self.directory / "annotations" / f"{bid}.json")
        if isinstance(value, dict) and value.get("image_sha256") == item.get("sha256") and value.get("annotation_version") == ANNOTATION_VERSION:
            return value
        return None

    def list(self):
        items = self._items()
        stamps = []
        for folder in ("annotations", "originals", "thumbnails"):
            path = self.directory / folder
            try:
                stamps.append(path.stat().st_mtime_ns)
            except OSError:
                stamps.append(None)
        stamp = (self._manifest_stamp, *stamps)
        if stamp != self._catalog_stamp:
            self._catalog_cache = [card for bid, item in items.items() if (card := self._card(bid, item))]
            self._catalog_stamp = stamp
        return self._catalog_cache

    def _card(self, bid, item):
        if not self.image_path(bid) or not self.image_path(bid, thumbnail=True):
            return None
        annotation = self._annotation(bid, item) or {}
        description = annotation.get("description", "")
        return dict(id=bid, url=f"/api/kaibun/backgrounds/{bid}/image",
                    thumbnail=f"/api/kaibun/backgrounds/{bid}/thumbnail",
                    label=annotation.get("label") or description[:36] or f"背景 {bid}",
                    description=description, tags=annotation.get("tags", []), indexed=bool(annotation),
                    type=item.get("type", "scene"), time_of_day=annotation.get("time_of_day", "unknown"),
                    place_group=annotation.get("place_group", ""))

    def card(self, bid):
        if not isinstance(bid, str) or not BG_ID.fullmatch(bid):
            return None
        item = self._items().get(bid)
        return self._card(bid, item) if item else None

    async def index_common(self, limit=30):
        """Explicit initial annotation phase: only after the download stage completes."""
        if not self._manifest().get("download_complete"):
            raise BackgroundError("背景图片下载尚未结束，下载完成后再准备图片索引")
        async with self._index_lock:
            items = self._items()
            common = sorted((card for card in self.list() if card["type"] != "solid"),
                            key=lambda card: (-items[card["id"]].get("references", {}).get("count", 0), card["id"]))[:max(1, min(limit, 36))]
            if not common:
                raise BackgroundError("本地尚无可用场景背景图片，请先完成下载")
            pending = [card for card in common if not card["indexed"]]
            for offset in range(0, len(pending), 9):
                batch = pending[offset:offset + 9]
                sheet = await asyncio.to_thread(self._sheet, batch)
                image = "data:image/jpeg;base64," + base64.b64encode(sheet.read_bytes()).decode()
                try:
                    text = await self.adapter.complete_with_images(
                        "你在为原作场景背景图片建立本地检索索引。实际观察每张编号图片，描述可见地点、布局、室内外、昼夜、天气与季节。"
                        "仅记录画面能确定的内容；无法确定的字段使用unknown。相同地点不同时间可用相同place_group简短名称，"
                        "time_of_day为day/dusk/night/unknown，tags使用简短中文地点与外观词。"
                        '输出JSON：{"backgrounds":[{"id":"图中编号","label":"简短地点名","description":"可见画面简述",'
                        '"tags":["事务所","室内"],"time_of_day":"day","place_group":"事务所办公区"}]}。',
                        json.dumps(dict(ids=[card["id"] for card in batch]), ensure_ascii=False), [image])
                except Exception:
                    raise BackgroundError("背景图片标注请求未完成，请检查对话模型的看图接口后继续") from None
                raw = response_object(text).get("backgrounds")
                if not isinstance(raw, list):
                    raise BackgroundError("背景图片标注格式不完整，可以继续重试")
                selected = {value.get("id"): value for value in raw if isinstance(value, dict) and isinstance(value.get("id"), str)}
                annotations = []
                for card in batch:
                    value = selected.get(card["id"], {})
                    if not isinstance(value.get("description"), str) or not value["description"].strip():
                        raise BackgroundError("背景图片标注遗漏了画面说明，可以继续重试")
                    tags = value.get("tags", [])
                    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
                        raise BackgroundError("背景图片标签格式有误，可以继续重试")
                    annotations.append(dict(id=card["id"], annotation_version=ANNOTATION_VERSION,
                                            image_sha256=items[card["id"]]["sha256"], model=self.adapter.model,
                                            label=str(value.get("label", ""))[:80], description=value["description"].strip()[:700],
                                            tags=list(dict.fromkeys(tag.strip()[:40] for tag in tags if tag.strip()))[:20],
                                            time_of_day=value.get("time_of_day") if value.get("time_of_day") in ("day", "dusk", "night", "unknown") else "unknown",
                                            place_group=str(value.get("place_group", ""))[:80]))
                for annotation in annotations:
                    save_json(self.directory / "annotations" / f"{annotation['id']}.json", annotation)
                self._catalog_stamp = None
                print(f"BACKGROUND INDEX {offset + len(batch)}/{len(pending)} newly annotated", flush=True)
            return [card for card in self.list() if card["indexed"]]

    def _sheet(self, cards):
        from PIL import Image, ImageDraw, ImageFont

        items = self._items()
        signature = hashlib.sha256("|".join(items[c["id"]]["sha256"] + c["id"] for c in cards).encode()).hexdigest()[:24]
        target = self.directory / "sheets" / f"{signature}.jpg"
        if target.is_file():
            return target
        sheet = Image.new("RGB", (1200, ((len(cards) + 2) // 3) * 255), "white")
        draw = ImageDraw.Draw(sheet)
        font = ImageFont.load_default(size=19)
        for i, card in enumerate(cards):
            path = self.image_path(card["id"])
            if not path:
                raise BackgroundError("本地背景图片缺失，请重新下载后继续")
            with Image.open(path) as source:
                image = source.convert("RGB")
                image.thumbnail((392, 224))
                x, y = (i % 3) * 400, (i // 3) * 255
                sheet.paste(image, (x + (400 - image.width) // 2, y))
                draw.text((x + 10, y + 229), card["id"], fill="black", font=font)
        target.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(target, "JPEG", quality=90)
        return target

    def _candidates(self, scene, catalog, limit=10):
        text = scene.get("place", "") + " " + " ".join(line.get("zh", "") for line in scene.get("lines", []))
        words = set(re.findall(r"[\w]+", text.lower()))

        def score(card):
            tags = [card["label"], card["place_group"], *card["tags"]]
            place = scene.get("place", "")
            terms = place_terms(place)
            card_place = " ".join(tags)
            overlap = 12 if terms and any(term in card_place for term in terms) else 0
            overlap += sum(3 if tag in place else 1 for tag in tags if tag and tag in text)
            english = len(words & set(re.findall(r"[a-z]+", " ".join(tags).lower())))
            time = card["time_of_day"]
            wanted = scene_time(place)
            if wanted == "night":
                overlap += 3 if time == "night" else -2 if time == "day" else 0
            elif wanted == "dusk":
                overlap += 3 if time == "dusk" else -2 if time == "night" else 0
            elif wanted == "day":
                overlap += 3 if time == "day" else -4 if time == "night" else 0
            return overlap + english

        items = self._items()
        return sorted(catalog, key=lambda card: (-score(card), -items.get(card["id"], {}).get("references", {}).get("count", 0), card["id"]))[:limit]

    def usable_background(self, scene, catalog=None):
        catalog = catalog if catalog is not None else [card for card in self.list() if card["indexed"] and card["type"] != "solid"]
        terms = place_terms(scene.get("place", ""))
        if not terms:
            return catalog[0]["id"] if catalog else None
        for card in self._candidates(scene, catalog, limit=len(catalog)):
            card_place = " ".join([card["label"], card["place_group"], *card["tags"]])
            if any(term in card_place for term in terms):
                return card["id"]
        return self._candidates(scene, catalog, limit=1)[0]["id"] if catalog else None

    async def prepare(self, doc):
        catalog = self.list()
        scenes = doc.get("scenes", [])
        pending = [i for i, scene in enumerate(scenes) if "background" not in scene]
        for scene in scenes:
            if "background" in scene:
                if scene["background"] is not None and not self.image_path(scene["background"]):
                    raise BackgroundError("已选背景图片缺失，请重新下载后继续")
                changes = scene.get("background_changes", {})
                if not isinstance(changes, dict) or any(bid is not None and not self.image_path(bid) for bid in changes.values()):
                    raise BackgroundError("已选场内背景图片缺失，请重新下载后继续")
        if not pending:
            return [scene.get("background") for scene in scenes]
        indexed = [card for card in catalog if card["indexed"] and card["type"] != "solid"]
        if not indexed:
            for i in pending:
                scenes[i].update(background=None, background_changes={})
            return [scene.get('background') for scene in scenes]
        requests = []
        allowed = {}
        # Every pending scene at one place shares a candidate pool: an earlier
        # selection remains legal later even though the plan is generated at once.
        grouped = {}
        for i in pending:
            scene = scenes[i]
            place = re.sub(r"\s+", "", scene.get("place", ""))
            grouped.setdefault(place, []).append(i)
        pools = {}
        for place, indices in grouped.items():
            pool = []
            for i in indices:
                for candidate in self._candidates(scenes[i], indexed, limit=3):
                    if candidate["id"] not in [card["id"] for card in pool]:
                        pool.append(candidate)
            # Existing same-place choices receive priority for continuity.
            previous_ids = [scene.get("background") for scene in scenes
                            if "background" in scene and re.sub(r"\s+", "", scene.get("place", "")) == place]
            for bid in previous_ids:
                if bid and bid not in [card["id"] for card in pool]:
                    if card := next((card for card in catalog if card["id"] == bid), None):
                        pool.insert(0, card)
            combined = dict(place=scenes[indices[0]].get("place", ""),
                            lines=[line for i in indices for line in scenes[i].get("lines", [])])
            for candidate in self._candidates(combined, indexed, limit=12):
                if candidate["id"] not in [card["id"] for card in pool]:
                    pool.append(candidate)
            pools[place] = pool[:12]
        previous = None
        for i, scene in enumerate(scenes):
            if "background" in scene:
                previous = scene["background"]
                for line in scene.get("lines", []):
                    previous = scene.get("background_changes", {}).get(line.get("id"), previous)
                continue
            candidates = pools[re.sub(r"\s+", "", scene.get("place", ""))]
            allowed[i] = {card["id"] for card in candidates}
            requests.append(dict(scene=i, place=scene.get("place", ""), previous_background=previous,
                                 previous_scene=i - 1 if i else None,
                                 location_cues=location_cues(scene),
                                 candidates=[{key: card[key] for key in ("id", "description", "tags", "time_of_day", "place_group")} for card in candidates]))
        payload = dict(premise=doc.get("premise", ""), scenes=requests)
        items = self._items()
        image_hashes = {bid: items[bid].get("sha256") for pool in allowed.values() for bid in pool}
        cache_key = hashlib.sha256(json.dumps(dict(provider=provider_id(self.adapter), index_version=ANNOTATION_VERSION, selection_version=SELECTION_VERSION,
                                                 images=image_hashes, context=payload), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        cache = self.directory / "choices" / f"{cache_key}.json"
        raw = read_json(cache)
        selector_fallback = False
        if raw is None:
            try:
                text = await self.adapter.complete(
                    "你根据已观察过的本地背景图片文字索引，为对白剧选择场景背景。按place与对白中的实际地点、昼夜选择。"
                    "相同地点的连续交流沿用前景；幕中确实转场时才在对应台词id设置background_changes。"
                    "地点类别相符时优先采用现有背景，布局、家具与故事有合理差异也可以使用，同地点尽量保持同一张图。"
                    "每个场景都从其candidates中选择最接近的有效图片id。优先地点类别，其次昼夜，允许家具布局等合理差异。"
                    '输出JSON：{"scenes":[{"scene":0,"background":"有效图片编号","background_changes":{"台词id":"有效图片编号"}}]}。',
                    json.dumps(payload, ensure_ascii=False) +
                    '\n请直接返回机器读取的JSON对象：{"scenes":[{"scene":0,"background":"有效图片编号","background_changes":{}}]}。')
                try:
                    raw = response_object(text)
                except BackgroundError:
                    repaired = await self.adapter.complete(
                        "把已有背景方案整理为JSON，沿用方案中的图片编号与转场位置。",
                        json.dumps(dict(plan=text, allowed={str(i): sorted(ids) for i, ids in allowed.items()}), ensure_ascii=False) +
                        '\n只返回完整JSON：{"scenes":[{"scene":0,"background":"有效图片编号","background_changes":{"台词id":"有效图片编号"}}]}。')
                    raw = response_object(repaired)
            except Exception as error:
                log.warning("background selector model=%s failed type=%s; using local indexed candidates", self.adapter.model, type(error).__name__)
                selector_fallback = True
                raw = {"scenes": []}
        values = raw.get("scenes") if isinstance(raw, dict) else None
        if not isinstance(values, list):
            values = []
            selector_fallback = True
        mapping = {value.get("scene"): value for value in values if isinstance(value, dict) and type(value.get("scene")) is int}
        plans = {}
        fallback_scenes = []
        for i in pending:
            value = mapping.get(i)
            if not isinstance(value, dict):
                value = {}
            if "background" not in value or value["background"] is None:
                fallback_scenes.append(i)
                pool = [card for card in indexed if card["id"] in allowed[i]]
                value = {**value, "background": self.usable_background(scenes[i], pool)}
            bid, changes = value["background"], value.get("background_changes", {})
            line_ids = {line["id"] for line in scenes[i].get("lines", [])}
            if bid is not None and (not isinstance(bid, str) or bid not in allowed[i]):
                fallback_scenes.append(i)
                pool = [card for card in indexed if card["id"] in allowed[i]]
                bid = self.usable_background(scenes[i], pool)
            if not isinstance(changes, dict):
                changes = {}
            changes = {lid: choice for lid, choice in changes.items() if lid in line_ids and isinstance(choice, str) and choice in allowed[i]}
            plans[i] = dict(background=bid, background_changes=changes)
            if bid is None:
                candidates = [card for card in indexed if card["id"] in allowed[i]]
                plans[i]["background"] = self.usable_background(scenes[i], candidates)
        if not selector_fallback:
            save_json(cache, raw)
        for i, plan in plans.items():
            scenes[i].update(plan)
        doc["background_selection"] = dict(model=self.adapter.model, source="local-fallback" if selector_fallback else "model",
                                           fallback_scenes=sorted(set(fallback_scenes)))
        return [scene.get("background") for scene in scenes]
