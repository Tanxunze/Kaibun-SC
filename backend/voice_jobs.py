"""Explicit audio-only repair jobs. Never regenerate script, outfits or backgrounds."""
import asyncio
import uuid
from copy import deepcopy
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel

from production import cached_audio, voice_lines


def coverage(store, adapter, doc, line_id=None):
    targets = voice_lines(doc, adapter)
    missing = [line['id'] for line in targets if not cached_audio(store, adapter, doc['id'], line)]
    current = [line for line in targets if line['id'] == line_id or line['id'].startswith((line_id or '') + '~')] if line_id else []
    return dict(total=len(targets), ready=len(targets)-len(missing), missing=len(missing), missing_ids=missing,
                current_required=len(current), current_missing=sum(line['id'] in missing for line in current),
                job=doc.get('voice_job'), revision=doc.get('voice_revision', ''))


def install_voice_routes(app, store, adapter, author, exports, get_story):
    @app.get('/stories/{id}/voices')
    async def status(id: str, line_id: str | None = None):
        return coverage(store, adapter, get_story(id), line_id)

    class Generate(BaseModel):
        mode: Literal['missing', 'current']
        line_id: str | None = None

    @app.post('/stories/{id}/voices', status_code=202)
    async def generate(id: str, body: Generate):
        doc = get_story(id)
        if id in author.tasks or doc.get('revision_proposal'):
            raise HTTPException(409, '请先完成或暂停当前制作，并处理修改预览')
        if any(job.get('status') == 'working' for key, job in exports.jobs.items() if key == id or key.startswith(id+'-scene-')):
            raise HTTPException(409, '请先暂停视频导出')
        if not getattr(adapter, 'tts_key', ''):
            raise HTTPException(422, '还没有配置语音服务')
        targets = voice_lines(doc, adapter)
        if body.mode == 'current':
            if not body.line_id or not any(line['id'] == body.line_id for s in doc['scenes'] for line in s['lines']):
                raise HTTPException(404, '没有这句台词')
            targets = [line for line in targets if line['id'] == body.line_id or line['id'].startswith(body.line_id+'~')]
            if not targets:
                raise HTTPException(422, '这句没有可用的配音人物；制作人需先配置音色')
        else:
            targets = [line for line in targets if not cached_audio(store, adapter, id, line)]
        if any(line.get('imported_untranslated') for line in targets):
            raise HTTPException(422, '请先整理并确认导入台词的日文和中文')
        job = dict(id=uuid.uuid4().hex, mode=body.mode, status='working' if targets else 'done', total=len(targets), completed=0, failed=0, errors=[], message='正在生成配音' if targets else '没有缺失语音')
        doc['voice_job'] = job
        store.save(doc)
        if not targets:
            return coverage(store, adapter, doc, body.line_id)

        async def work():
            # Targets are frozen for this job, and all mutating endpoints use
            # author.tasks as the same per-story exclusion mechanism.
            queue = asyncio.Queue()
            for line in targets:
                queue.put_nowait(deepcopy(line))

            def checkpoint():
                latest = store.get(id)
                if latest is None:
                    return
                latest['voice_job'] = deepcopy(job)
                state = coverage(store, adapter, latest)
                if isinstance(latest.get('production'), dict):
                    latest['production'].update(voices_done=state['ready'], voices_total=state['total'])
                store.save(latest)

            async def worker():
                while not queue.empty():
                    line = queue.get_nowait()
                    try:
                        await author.production.ensure_voice(id, line, force=body.mode == 'current')
                        latest = store.get(id)
                        if latest:
                            base_id = line['id'].split('~')[0]
                            saved = next(l for s in latest['scenes'] for l in s['lines'] if l['id'] == base_id)
                            saved['audio_revision'] = uuid.uuid4().hex
                            latest['voice_revision'] = uuid.uuid4().hex
                            store.save(latest)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # Do not expose provider details; finish other lines.
                        job['failed'] += 1
                        job['errors'].append(line['id'])
                    job['completed'] += 1
                    job['message'] = f"已处理 {job['completed']}/{job['total']}，失败 {job['failed']}"
                    checkpoint()

            workers = [asyncio.create_task(worker()) for _ in range(min(2, len(targets)))]
            try:
                await asyncio.gather(*workers)
                job.update(status='failed' if job['failed'] else 'done', message='部分配音失败，已完成部分已保存，可再次补齐' if job['failed'] else '配音已完成')
            except asyncio.CancelledError:
                for worker_task in workers:
                    worker_task.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                job.update(status='interrupted', message='配音已暂停，完成部分已保存')
                raise
            except Exception:
                for worker_task in workers:
                    worker_task.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                job.update(status='failed', message='配音任务未完成，可重试；已保存的配音保留')
            finally:
                checkpoint()

        task = asyncio.create_task(work())
        author.tasks[id] = task
        task.add_done_callback(lambda _: author.tasks.pop(id, None))
        return coverage(store, adapter, doc, body.line_id)
