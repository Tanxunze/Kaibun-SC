"""Story-local casting. A guest keeps their script identity when assigned a voice or stand."""
import base64
import hashlib
import re
from io import BytesIO
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, Field


class CastingEdit(BaseModel):
    voice_id: str = Field(default='', max_length=150)
    outfit_owner: str = ''
    outfit: str = ''
    portrait: str = ''
    image_base64: str = Field(default='', max_length=7_000_000)


def guest_actors(doc, adapter):
    """Resolve the same wardrobe and portrait references for the player and video recorder."""
    actors = []
    for guest in (doc.get('outline') or {}).get('guests', []):
        setting = doc.get('guest_cast', {}).get(guest['id'], {})
        outfit = adapter.outfit(setting['outfit_owner'], setting['outfit']) if setting.get('outfit') else None
        portrait = setting.get('portrait')
        if outfit or portrait:
            actors.append(dict(**guest, stand=outfit, stand_bounds=outfit and outfit.get('bounds'),
                               portrait=portrait, short_name=guest['name'], avatar_url='', background_url=None))
    return actors


def store_portrait(encoded, directory):
    try:
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(raw), formats=['PNG', 'JPEG', 'WEBP']) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError('image too large')
            rgba = ImageOps.exif_transpose(image).convert('RGBA')
            rgba.thumbnail((2048, 2048))
            output = BytesIO()
            rgba.save(output, 'PNG')
    except (ValueError, OSError, Image.DecompressionBombError):
        raise HTTPException(422, '请选择有效的 PNG、JPEG 或 WebP 立绘（最多 2000 万像素）') from None
    data = output.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (digest + '.png')
    if not target.exists():
        part = target.with_suffix('.part')
        part.write_bytes(data)
        part.replace(target)
    return digest


def install_guest_routes(app, store, adapter, author, exports, get_story, presentation):
    portraits = store.directory / 'guest-portraits'

    @app.get('/guest-portraits/{digest}.png')
    async def portrait(digest: str):
        if not re.fullmatch('[a-f0-9]{64}', digest) or not (portraits / (digest + '.png')).is_file():
            raise HTTPException(404, '找不到这张立绘')
        return FileResponse(portraits / (digest + '.png'), media_type='image/png')

    @app.post('/stories/{id}/guests/{guest_id}')
    async def cast_guest(id: str, guest_id: str, body: CastingEdit):
        doc = get_story(id)
        if not any(g['id'] == guest_id for g in (doc.get('outline') or {}).get('guests', [])):
            raise HTTPException(404, '找不到本篇配角')
        if id in author.tasks or any(not task.done() and (k == id or k.startswith(id + '-scene-')) for k, task in exports.tasks.items()):
            raise HTTPException(409, '请等待当前制作或导出完成')
        if body.outfit and (body.portrait or body.image_base64 or not adapter.outfit(body.outfit_owner, body.outfit)):
            raise HTTPException(422, '请选择一套有效衣装或一张静态立绘')
        previous = doc.get('guest_cast', {}).get(guest_id, {})
        if body.portrait and body.portrait != previous.get('portrait'):
            raise HTTPException(422, '请重新选择立绘文件')
        portrait = store_portrait(body.image_base64, portraits) if body.image_base64 else body.portrait
        settings = dict(voice_id=body.voice_id.strip(), outfit_owner=body.outfit_owner if body.outfit else '',
                        outfit=body.outfit, portrait=portrait)
        doc.setdefault('guest_cast', {})[guest_id] = settings
        if settings['voice_id'] != previous.get('voice_id', ''):
            doc['voice_revision'] = uuid4().hex
            for scene in doc['scenes']:
                for line in scene['lines']:
                    if guest_id in (line.get('speakers') or [line['speaker']]):
                        line['audio_revision'] = doc['voice_revision']
        store.save(doc)
        return presentation(doc)
