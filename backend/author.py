"""Scene-by-scene fiction generation with checkpoints and compact continuity."""

import asyncio
import json
import logging
import re
from pathlib import Path

from production import Production, ProductionError
from character_names import identity, name_reference, NAME_RULES

EMOTIONS = {"calm", "happy", "shy", "surprised", "sad", "angry", "thinking"}
def creative_guidance(stage="script"):
    """Read every request; outline and dialogue have separate output contracts."""
    if stage not in ('script', 'outline'):
        raise ValueError('未知创作阶段')
    text = Path(__file__).with_name("CREATIVE_GUIDE.md").read_text(encoding="utf-8")
    common, marker, specific = text.partition('## 剧本输出约定')
    script, outline_marker, outline = specific.partition('## 大纲输出约定')
    if not marker or not outline_marker:
        raise ValueError('创作指导缺少大纲或剧本约定')
    return common + ('## 大纲输出约定' + outline if stage == 'outline' else marker + script)


DIALOGUE_FORMAT = (
    "同一speaker可以在lines中连续出现。长发言包含回忆、列举或心情转折时，按完整意思与自然停顿拆成连续多条台词，"
    "每条分别填写对应的ja、zh、emotion和kind=dialogue，接续原有语气与情绪，保留完整措辞和连贯语气。"
    "每条用于各自的配音和立绘演出，只包含本条内容，不能保留整段全文后再重复追加切分台词。"
    "微调中的句内演出区间仍在选中台词内部设置，不复制台词；台词不夹动作、旁白、心理或场景描写。"
)



CHARACTER_NOTES = json.loads(Path(__file__).with_name("character_notes.json").read_text(encoding="utf-8"))
log = logging.getLogger(__name__)
LENGTHS = {
    "short": dict(scale="几分钟的短篇", scenes="约1至3场", lines="15—25", speech="日语正文约800至1500字"),
    "standard": dict(scale="约十分钟的故事", scenes="约3至5场", lines="25—40", speech="日语正文约2000至3000字"),
    "half_hour": dict(scale="约三十分钟的故事", scenes="约7至12场", lines="30—45", speech="日语正文约6000至9000字"),
    "hour_plus": dict(scale="一小时以上的故事", scenes="约16至28场", lines="35—55", speech="日语正文约14000至20000字"),
}


class StoryFormatError(ValueError):
    """A locally written, safe explanation of an invalid story response."""


def story_character_sheet(sheet):
    """Keep character material while omitting instructions for live private chats."""
    sections = re.split(r"(?m)(?=^##\s)", sheet)
    return "\n".join(section.strip() for section in sections
                     if not re.match(r"^##\s+(?:硬性规则|自然对话与日常)\s*(?:\n|$)", section)).strip()


def json_object(text):
    start = text.find("{")
    if start < 0:
        raise StoryFormatError("模型回复中缺少剧本JSON对象")
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        raise StoryFormatError("模型回复的剧本JSON不完整或格式有误") from None
    if not isinstance(value, dict):
        raise StoryFormatError("模型返回的剧本格式不正确")
    return value


def validate_outline(raw, known, requested, length):
    if isinstance(raw, dict) and "scenes" not in raw and isinstance(raw.get("outline"), dict):
        raw = raw["outline"]
    cast = raw.get("cast", requested)
    if not isinstance(cast, list) or not cast or any(not isinstance(c, str) or c not in known for c in cast):
        raise StoryFormatError("大纲出场人物需为资料中的角色id")
    if requested and not set(requested).issubset(cast):
        raise StoryFormatError("大纲遗漏了指定人物")
    scenes = raw.get("scenes")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 64:
        raise StoryFormatError("大纲需要包含1至64个场景")
    clean_scenes = []
    for scene in scenes:
        if not isinstance(scene, dict) or not all(isinstance(scene.get(k), str) and scene[k].strip() for k in ("place", "direction")):
            raise StoryFormatError("大纲场景的place与direction需要非空文本")
        clean_scenes.append(dict(place=scene["place"].strip()[:160], direction=scene["direction"].strip()[:2400], transition=scene.get("transition") if scene.get("transition") in ("cut", "pause", "fade") else "cut"))
    guests = raw.get("guests", [])
    if not isinstance(guests, list):
        raise StoryFormatError("大纲guests需要数组，未用配角时填写空数组")
    clean_guests = []
    for guest in guests:
        if isinstance(guest, dict) and isinstance(guest.get("id"), str) and guest["id"].isascii() and guest["id"].replace("_", "").isalnum() and guest["id"] not in {*known, "producer", "narrator"} and isinstance(guest.get("name"), str):
            clean_guests.append({"id": guest["id"][:30], "name": guest["name"][:40]})
    return dict(cast=list(dict.fromkeys(cast)),
                opening=raw.get("opening", "").strip()[:500] if isinstance(raw.get("opening", ""), str) else "",
                guests=clean_guests, direction=str(raw.get("direction", ""))[:1800], scenes=clean_scenes,
                length=length)


def validate_scene(raw, outline, index):
    allowed = {*outline["cast"], "producer", *(g["id"] for g in outline["guests"])}
    lines = raw.get("lines")
    if not isinstance(lines, list) or not lines or len(lines) > 100:
        raise StoryFormatError("场景需要包含1至100句对白")
    clean = []
    for i, line in enumerate(lines):
        if not isinstance(line, dict) or not isinstance(line.get("speaker"), str) or line.get("speaker") not in allowed or not isinstance(line.get("zh"), str) or not line["zh"].strip():
            raise StoryFormatError("场景speaker需为出场角色id、producer或已定义配角id，zh需为非空文本")
        ja = line.get("ja", "")
        if not isinstance(ja, str) or not ja.strip():
            raise StoryFormatError("角色对白缺少日语ja")
        if len(ja) > 1200 or len(line["zh"]) > 1600:
            raise StoryFormatError("单句台词过长")
        emotion = line.get("emotion")
        direction = dict(id=f"{index}-{i}", speaker=line["speaker"], ja=ja.strip(), zh=line["zh"].strip(),
                         emotion=emotion if isinstance(emotion, str) and emotion in EMOTIONS else "calm")
        kind = line.get("kind", "dialogue")
        if kind not in ("dialogue", "thought"):
            raise StoryFormatError("kind需要填写dialogue对白或thought心声")
        direction["kind"] = kind
        if line["speaker"] == "fuyuko" and "voice_style" in line:
            if line["voice_style"] not in ("natural", "idol"):
                raise StoryFormatError("冬优子声线需要填写natural或idol")
            direction["voice_style"] = line["voice_style"]
        if "speakers" in line:
            speakers = line["speakers"]
            if not isinstance(speakers, list) or not 2 <= len(speakers) <= 7 or any(not isinstance(cid, str) or cid not in outline["cast"] for cid in speakers):
                raise StoryFormatError("异口同声需提供2至7位出场角色")
            direction["speakers"] = list(dict.fromkeys(speakers))
        if "onstage" in line:
            onstage = line["onstage"]
            if not isinstance(onstage, list) or any(not isinstance(cid, str) or cid not in outline["cast"] for cid in onstage):
                raise StoryFormatError("onstage需要由本篇偶像id组成的数组")
            direction["onstage"] = list(dict.fromkeys(onstage))
        if "focus" in line:
            focus = line["focus"]
            if not isinstance(focus, list) or len(focus) > 7 or any(not isinstance(cid, str) or cid not in outline["cast"] for cid in focus):
                raise StoryFormatError("focus需要包含至多7个当前交流人物的偶像id")
            direction["focus"] = list(dict.fromkeys(focus))
        if 'actor_states' in line:
            states = line['actor_states']
            if not isinstance(states, dict):
                raise StoryFormatError('actor_states需要按人物id保存表情与动作')
            checked = {}
            for cid, state in states.items():
                if cid not in outline['cast'] or not isinstance(state, dict):
                    raise StoryFormatError('actor_states包含未知人物或无效状态')
                if any(key not in ('emotion', 'body_mood') or (value not in EMOTIONS and not (key == 'body_mood' and value is None)) for key, value in state.items()):
                    raise StoryFormatError('人物表情或动作无效')
                checked[cid] = dict(state)
            direction['actor_states'] = checked
        if 'listener_state_persist' in line:
            if not isinstance(line['listener_state_persist'], bool):
                raise StoryFormatError('listener_state_persist需要布尔值')
            direction['listener_state_persist'] = line['listener_state_persist']
        if 'body_mood' in line:
            if line['body_mood'] is not None and line['body_mood'] not in EMOTIONS:
                raise StoryFormatError('身体动作无效')
            direction['body_mood'] = line['body_mood']
        clean.append(direction)
    memory = raw.get("memory")
    if not isinstance(memory, str) or not memory.strip():
        raise StoryFormatError("场景缺少非空文本memory连续性记录")
    return dict(index=index, title=f"第{index + 1}幕", place=outline["scenes"][index]["place"],
                lines=clean, memory=memory.strip()[:2800], transition=outline["scenes"][index].get("transition", "cut"))


class Author:
    def __init__(self, store, adapter):
        self.store, self.adapter = store, adapter
        self.tasks = {}
        self.gate = asyncio.Semaphore(1)
        self.production = Production(store, adapter)

    def enqueue(self, id):
        if id in self.tasks:
            return
        task = asyncio.create_task(self.generate(id))
        self.tasks[id] = task
        task.add_done_callback(lambda _: self.tasks.pop(id, None))

    async def stop(self, id):
        task = self.tasks.get(id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        doc = self.store.get(id)
        if doc and doc["status"] != "ready":
            doc.update(status="interrupted", phase="已暂停，可以继续")
            self.store.save(doc)

    def extend(self, id, instruction):
        doc = self.store.get(id)
        if not doc or id in self.tasks:
            raise ValueError("请先停止当前创作")
        if not doc["scenes"]:
            raise ValueError("写完一幕后可以续写")
        doc.update(status="queued", continuation=instruction.strip(), phase="准备续写", error=None)
        self.store.save(doc)
        self.enqueue(id)

    async def request(self, system, user, *, validate, doc, stage):
        last = None
        correction = ""
        for attempt in range(2):
            reply = await self.adapter.complete(system, user + correction)
            try:
                parsed = json_object(reply)
                return validate(parsed)
            except StoryFormatError as error:
                last = error
                directory = self.store.directory / "diagnostics"
                directory.mkdir(exist_ok=True)
                diagnostic = dict(stage=stage, model=self.adapter.model, attempt=attempt + 1,
                                  reason=str(error), response=reply)
                # A cancelled to_thread write could recreate a deleted story's
                # diagnostic after author.stop() returned. This bounded write
                # finishes before the task can be cancelled.
                (directory / f"{doc['id']}-{stage}-{attempt + 1}.json").write_text(
                    json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
                log.warning("story=%s stage=%s attempt=%s reason=%s", doc["id"], stage, attempt + 1, error)
                correction = ("\n上一版未通过格式检查：" + str(error) +
                              "\n请保留本篇构思，按上述格式返回修正后的完整JSON。上一版：\n" + reply)
        raise last

    async def generate(self, id):
        async with self.gate:
            doc = self.store.get(id)
            if not doc or doc["status"] == "ready":
                return
            stage = "outline"
            length = LENGTHS.get(doc["length"], LENGTHS["short"])
            try:
                doc.update(status="generating", phase="正在构思故事", error=None, model=self.adapter.model)
                self.store.save(doc)
                if not doc["outline"] or doc.get("continuation"):
                    catalog = [{"id": c.id, **identity(c), "intro": c.intro,
                                "relationship": CHARACTER_NOTES.get(c.id, "")} for c in self.adapter.characters.values()]
                    raw = await self.request(
                        "你是《偶像大师 闪耀色彩》的剧本编剧。构思一个适合私人观看的对白剧大纲。\n" + creative_guidance("outline") + "\n" + NAME_RULES,
                        "用户想法：" + doc["premise"] + "\n指定角色：" + json.dumps(doc["requested_cast"]) +
                        "\n规模：" + length["scale"] + "，" + length["speech"] + "，可参考" + length["scenes"] + "，随情境自然分场。" +
                        "\n按情境选择人物，简短交代这次发生的事、关系与松散走向，再自然分场。"
                        "大纲、开头、场次地点与场次说明均用简体中文；日文名称保留原文时附中文解释。"
                        "本篇的趣味留在情境里，具体心意、回应和后续行动由人物在正文中自由展开。"
                        "cast选资料中的角色id，人物数量随故事需要决定，指定人物均需包含。场景为1至64场，每场place与direction填写非空文本。"
                        "制作人的speaker是producer，cast填写偶像id；guests填写配角数组，未用配角时填写空数组。"
                        "场次数量随故事发展自行决定。每幕transition选择cut（剧情场景连续）、pause（时间空间小变化）或fade（时间空间大变化）。允许P和必要的虚构配角。"
                        '只输出JSON：{"cast":["偶像id"],"guests":[{"id":"friend","name":"配角称呼"}],'
                        '"opening":"供读者观看的故事开头，仅介绍起始处境，后续留给正文揭晓",'
                        '"direction":"整体情境与松散走向","scenes":[{"place":"地点","direction":"本场情境与可展开的线索"}]}。'
                        "\n补充内容：" + doc.get("details", "") +
                        "\n人物资料：" + json.dumps(catalog, ensure_ascii=False) + ("\n续写要求：" + doc["continuation"] + "\n原故事记录：" + doc["story_memory"] + "\n原大纲：" + json.dumps(doc["outline"], ensure_ascii=False) if doc.get("continuation") else ""),
                        validate=lambda raw: validate_outline(raw, self.adapter.characters, doc["requested_cast"], doc["length"]),
                        doc=doc, stage=stage)
                    planned = raw
                    if doc.get("continuation"):
                        original = doc["outline"]
                        original["scenes"] = original["scenes"][:len(doc["scenes"])] + planned["scenes"]
                        original["cast"] = list(dict.fromkeys(original["cast"] + planned["cast"]))
                        original["guests"] = list({g["id"]: g for g in original["guests"] + planned["guests"]}.values())
                        doc["continuation_direction"] = planned["direction"]
                        doc["active_instruction"] = doc["continuation"]
                        doc.pop("continuation", None)
                    else:
                        doc["outline"] = planned
                    doc["title"] = doc["premise"]
                    self.store.save(doc)
                if doc.get("tuning") == "outline":
                    doc.update(status="tuning", phase="大纲已完成")
                    self.store.save(doc)
                    return
                outline = doc["outline"]
                for index in range(len(doc["scenes"]), len(outline["scenes"])):
                    stage = f"scene-{index + 1}"
                    doc["phase"] = f"正在写第 {index + 1} / {len(outline['scenes'])} 场"
                    self.store.save(doc)
                    cast = [{**identity(self.adapter.characters[cid]),
                             "sheet": story_character_sheet(self.adapter.characters[cid].sheet),
                             "relationship": CHARACTER_NOTES.get(cid, "")} for cid in outline["cast"]]
                    tail = doc["scenes"][-1]["lines"][-10:] if doc["scenes"] else []
                    raw = await self.request(
                        "你在编写偶像同人分幕剧本及具体人物对白。人物和此前已发生的事保持连续，"
                        "原人设承接人物身份、经历、称呼与说话习惯，人物补充提供本模块同人世界中的心意与相处，相关关系依此展开。"
                        "人物以符合年龄的方式表达亲近与回应，制作人也以自己的感受和意愿参与。"
                        "人物按各自性格与此刻心情自由交流，满足、迟疑、没说完的话和临时的主动都有自己的来处。"
                        "大纲提供情境和线索，具体反应与后续行动随人物的交流展开。"
                        "continuity与previous_ending承接已发生的事，outline与current提供接下来可展开的构思。"
                        "只编写人物实际说出的对白，不生成心理描写、内心独白、场景铺陈或旁白；表情与演出信息放在结构字段。"
                        "日语附中文字幕。本幕对白发生在current指定的实际地点，地点转移由大纲安排为下一幕。输出JSON。\n" + creative_guidance() + "\n" + DIALOGUE_FORMAT + "\n" + NAME_RULES,
                        json.dumps(dict(premise=doc["premise"], details=doc.get("details", ""), outline=outline, current=outline["scenes"][index],
                                        characters=cast, character_names=name_reference(self.adapter.characters), continuity=doc["story_memory"], previous_ending=tail,
                                        instruction=doc.get("active_instruction", ""),
                                        continuation_direction=doc.get("continuation_direction", ""),
                                        final_scene=index == len(outline["scenes"]) - 1), ensure_ascii=False) +
                        "\n整篇目标：" + length["scale"] + "，" + length["speech"] + "。本场可以约" + length["lines"] +
                        "条具体口语对白，长短随实际交流需要，允许闲话和停顿，参考条数不限制长发言按完整句意必要分段。"
                        '格式：{"lines":[{"speaker":"人物id或producer","ja":"日语对白",'
                        '"zh":"中文","kind":"dialogue","emotion":"calm/happy/shy/surprised/sad/angry/thinking","voice_style":"冬优子声线natural或idol，其他角色省略","onstage":["房间内在场的偶像id"],"focus":["本句画面里交流的1至7位偶像id"],"speakers":["异口同声时的2至7位偶像id，可省略"]}],'
                        '"memory":"合并后的简短故事记录：已发生的事、每人知道或误会什么、心意与回应带来的关系变化、约定和尚待回应的事情"}。'
                        'onstage记录现场人物；focus选择本次交流中的说话者与交谈对象，话题转向别人时切换画面，制作人以字幕呈现。'
                        '为非发言人物按其自身处境设置actor_states，例如{"hiori":{"emotion":"thinking","body_mood":"calm"}}。'
                        '人物反应发生变化时才更新，不跟随主说话人的情绪逐句变化；保持同镜头人物的独立情绪。'
                        '冬优子在外人面前维持可爱偶像形象的发言用idol声线，与熟人私下以本来语气说话用natural；根据实际情境逐句选择。'
                        '输出前核对称呼、说话者、人物已知信息和动作衔接，保留临场变化和自然的闲话。',
                        validate=lambda raw: validate_scene(raw, outline, index), doc=doc, stage=stage)
                    scene = raw
                    # Position is an outline index; identity must survive deleted/reordered scenes.
                    identity_index = max((s.get('index', -1) for s in doc['scenes']), default=-1) + 1
                    scene['index'] = identity_index
                    for number, line in enumerate(scene['lines']):
                        line['id'] = f'{identity_index}-{number}'
                    doc["scenes"].append(scene)
                    doc["story_memory"] = scene["memory"]
                    self.store.save(doc)
                    if doc.get("tuning") == "script":
                        continue
                    stage = "production"
                    await self.production.prepare(doc)
                    doc.update(status="generating", phase=f"第 {index + 1} 场已准备完成")
                    self.store.save(doc)
                doc.pop("active_instruction", None)
                if doc.get("tuning") == "script":
                    doc.update(status="tuning", phase="剧本已完成")
                    self.store.save(doc)
                    return
                stage = "production"
                await self.production.prepare(doc)
                doc.update(status="ready", phase="故事写好了", error=None)
                self.store.save(doc)
            except asyncio.CancelledError:
                doc.update(status="interrupted", phase="生成中断，可以继续")
                self.store.save(doc)
                raise
            except Exception as error:
                # Only locally written format errors reach the UI, never provider text or credentials.
                reason = str(error) if isinstance(error, (StoryFormatError, ProductionError)) else f"模型请求未完成（{type(error).__name__}）"
                where = "语音与演出" if stage == "production" else "大纲" if stage == "outline" else f"第{stage.split('-')[1]}幕"
                log.warning("story=%s stage=%s failed type=%s", doc["id"], stage, type(error).__name__)
                doc.update(status="failed", phase="暂时没能写完", failure_stage=stage,
                           error=f"{where}生成失败：{reason}。已保存进度，可以继续。")
                self.store.save(doc)

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
