"""Prepare voice files and scene staging before a story becomes ready."""

import asyncio
import os

from wardrobe import WardrobeError
from backgrounds import BackgroundError


class ProductionError(RuntimeError):
    """Safe, locally written production failure shown to the story's owner."""


def voice_lines(doc, adapter):
    return [dict(line, speaker=cid, id=line["id"] + "~" + cid) if line.get("speakers") else line
            for scene in doc["scenes"] for line in scene["lines"]
            for cid in (line.get("speakers") or [line["speaker"]])
            if (adapter.has_voice(cid) if hasattr(adapter, 'has_voice') else cid in adapter.characters or (cid == "producer" and bool(os.environ.get("KAIBUN_PRODUCER_VOICE_ID"))))]


def cached_audio(store, adapter, story_id, line):
    signature, _ = adapter.voice_signature(line)
    path = store.audio_path(story_id, line["id"], signature)
    if path.is_file() and path.stat().st_size > 0:
        return path
    # A revised copy reuses only an exact content/voice match. Copy it into the
    # destination so deleting the original does not break the revised work.
    import shutil
    import uuid
    doc = store.get(story_id)
    seen = {story_id}
    while doc and doc.get('revision_of') and doc['revision_of'] not in seen:
        source_id = doc['revision_of']
        seen.add(source_id)
        source = store.get(source_id)
        if not source:
            break
        original = next((l for l in voice_lines(source, adapter) if l['id'] == line['id']), None)
        if original and adapter.voice_signature(original)[0] == signature:
            cached = store.audio_path(source_id, line['id'], signature)
            if cached.is_file() and cached.stat().st_size:
                temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
                try:
                    shutil.copyfile(cached, temp)
                    temp.replace(path)
                    return path
                finally:
                    temp.unlink(missing_ok=True)
        doc = source
    return None


class Production:
    def __init__(self, store, adapter):
        self.store, self.adapter = store, adapter
        self.voice_gate = asyncio.Semaphore(2)

    async def ensure_voice(self, story_id, line, *, force=False):
        if not force and cached_audio(self.store, self.adapter, story_id, line):
            return
        async with self.voice_gate:
            if not force and cached_audio(self.store, self.adapter, story_id, line):
                return
            signature, voice_id = self.adapter.voice_signature(line)
            audio = await self.adapter.voice(line, voice_id)
            if not audio:
                raise ValueError('empty audio')
            path = self.store.audio_path(story_id, line['id'], signature)
            import uuid
            temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                temp.write_bytes(audio)
                temp.replace(path)
            finally:
                temp.unlink(missing_ok=True)

    async def prepare(self, doc):
        lines = voice_lines(doc, self.adapter)
        progress = dict(voices_done=sum(cached_audio(self.store, self.adapter, doc["id"], line) is not None for line in lines),
                        voices_total=len(lines), staging_done=False)
        doc.update(status="preparing", phase="正在准备语音与演出", production=progress)
        self.store.save(doc)

        def checkpoint():
            doc["phase"] = f"正在准备语音与演出 · 配音 {progress['voices_done']} / {progress['voices_total']}"
            self.store.save(doc)

        async def prepare_voices():
            async def one(line):
                if cached_audio(self.store, self.adapter, doc["id"], line):
                    return
                try:
                    await self.ensure_voice(doc['id'], line)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    raise ProductionError("部分语音未能完成，继续准备会使用已完成的配音") from None
                progress["voices_done"] += 1
                checkpoint()
            await together([one(line) for line in lines])

        async def prepare_staging():
            try:
                await self.adapter.prepare_outfits(doc)
                if hasattr(self.adapter, "prepare_backgrounds"):
                    await self.adapter.prepare_backgrounds(doc)
            except asyncio.CancelledError:
                raise
            except (WardrobeError, BackgroundError) as error:
                raise ProductionError(str(error)) from None
            except Exception:
                raise ProductionError("服装与演出准备未完成，请检查服装图片和对话模型的看图服务后继续") from None
            progress["staging_done"] = True
            checkpoint()

        await together([prepare_voices(), prepare_staging()])
        doc["production_version"] = 1


async def together(coroutines):
    tasks = [asyncio.create_task(coro) for coro in coroutines]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
