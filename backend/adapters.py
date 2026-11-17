"""Read-only adapters for the existing project's models and character assets."""

import hashlib
import json
import os
import asyncio
from dataclasses import replace
from pathlib import Path

import httpx

from support.characters import load_characters
from support.config import LLMSettings, fish_audio_model_from_env
from support.proxy import proxy_from_env
from paths import characters_path_from_env, data_root, project_path
from support.delivery_cues import spoken_by, voiced
FISH_TTS_HTTP_URL = 'https://api.fish.audio/v1/tts'
from support.llm import ChatMessage
from support.llm.providers import open_llm
from support.proxy import open_client
from support.readings import load_readings, pronunciation_dictionary, readings_path, used_in
from character_names import speech_names, identity
from wardrobe import Wardrobe, complete_with_images
from backgrounds import Backgrounds
from outfit_policy import AUTO_EXCLUDED, DAILY_DEFAULTS
from voice_errors import VoiceError


def story_voice_text(line, model):
    text = line["ja"]
    if line.get("kind") == "thought":
        # Story thoughts put meaningful words inside parentheses, unlike chat stage directions.
        text = text.translate(str.maketrans("", "", "()（）"))
    return spoken_by(voiced(f"[{line['emotion']}] {text}"), model)


class ModelConnection:
    def __init__(self, settings, proxy):
        self.settings = settings
        self.model = settings.model if settings else None
        self.client = open_client(proxy.proxy_for("chat_llm"), httpx.Timeout(180, connect=15)) if settings else None
        self.llm = open_llm(settings, self.client) if settings else None

    async def complete(self, system, user):
        if self.llm is None:
            raise RuntimeError("请在 .env 配置模型并重启后再使用此功能")
        chunks = []
        stream = self.llm.stream([ChatMessage("system", system), ChatMessage("user", user)])
        try:
            async for item in stream:
                if isinstance(item, str):
                    chunks.append(item)
        finally:
            await stream.aclose()
        return "".join(chunks)

    async def complete_with_images(self, system, user, images):
        return await complete_with_images(self, system, user, images)

    async def close(self):
        if self.llm:
            await self.llm.aclose()

class WardrobeAdapter:
    """Use the configured asset selector while retaining the project's local catalog."""
    def __init__(self, project, selector):
        self.project, self.selector = project, selector
        self.settings, self.model = selector.settings, selector.model
        self.characters, self.asset_root = project.characters, project.asset_root

    async def complete(self, system, user):
        return await self.selector.complete(system, user)

    async def complete_with_images(self, system, user, images):
        return await self.selector.complete_with_images(system, user, images)


ROOT = Path(__file__).resolve().parents[1]


class ProjectAdapter(ModelConnection):
    def __init__(self):
        self.proxy = proxy_from_env()
        super().__init__(LLMSettings.optional_from_env("CHAT"), self.proxy)
        self.characters = load_characters(characters_path_from_env())
        self.characters = {cid: replace(character, default_outfit=DAILY_DEFAULTS[cid]) if cid in DAILY_DEFAULTS and character.default_outfit in AUTO_EXCLUDED else character for cid, character in self.characters.items()}
        self.asset_root = project_path(os.environ.get("KAIBUN_ASSET_ROOT") or 'assets')
        self.stand_bounds = {}
        for c in self.characters.values():
            if c.default_outfit:
                path = self.asset_root / "spine" / "idols" / c.default_outfit / "data.json"
                try:
                    skeleton = json.loads(path.read_text(encoding="utf-8"))["skeleton"]
                    width, height = float(skeleton["width"]), float(skeleton["height"])
                    if width > 0 and height > 0:
                        self.stand_bounds[c.id] = dict(width=width, height=height)
                except (OSError, ValueError, KeyError, TypeError):
                    pass
        self.readings = load_readings(readings_path(characters_path_from_env()))
        # Name normalization precedes synthesis; the dictionary must match that normalized spelling.
        from support.readings import Reading
        natsuha = next((r for r in self.readings if r.written == '夏葉' and r.phonemes), None)
        if natsuha:
            self.readings = tuple(r for r in self.readings if r.written != 'ナツハ') + (Reading('ナツハ', 'なつは', natsuha.phonemes),)
        self.dictionary = pronunciation_dictionary(self.readings)
        self.tts_model = fish_audio_model_from_env()
        self.tts_key = os.environ.get("FISH_AUDIO_API_KEY", "")
        settings = LLMSettings.optional_from_env("KAIBUN_BACKGROUND", fallback="CHAT")
        if settings:
            settings = replace(settings, max_tokens=settings.max_tokens or 4096,
                               reasoning_effort=settings.reasoning_effort or "low")
        self.background_selector = ModelConnection(settings, self.proxy)
        self.wardrobe = Wardrobe(WardrobeAdapter(self, self.background_selector), data_root() / 'wardrobe')
        self.backgrounds = Backgrounds(self.background_selector, data_root() / 'backgrounds')

    def has_voice(self, cid):
        character = self.characters.get(cid)
        voice = getattr(character, 'voice_id', '') if character else (
            os.environ.get('KAIBUN_PRODUCER_VOICE_ID') if cid == 'producer' else '')
        return bool(self.tts_key and voice)

    def outfits(self, cid):
        return self.wardrobe.outfits(cid)

    def outfit(self, cid, outfit_id):
        return self.wardrobe.outfit(cid, outfit_id)

    def thumbnail_path(self, outfit_id):
        return self.wardrobe.thumbnail_path(outfit_id)

    async def ensure_thumbnail(self, outfit_id):
        return await self.wardrobe.ensure_thumbnail(outfit_id)

    async def prepare_outfits(self, doc):
        return await self.wardrobe.prepare(doc)

    async def prepare_backgrounds(self, doc):
        return await self.backgrounds.prepare(doc)

    def catalog(self):
        result = []
        for c in self.characters.values():
            outfit = c.default_outfit
            stand = None
            if outfit and (self.asset_root / "spine" / "idols" / outfit / "data.json").is_file():
                stand = {"id": outfit, "url": f"/api/kaibun/stand/{outfit}/"}
            result.append(dict(**identity(c), voice_id=c.voice_id,
                               retired_default_outfits=[oid for oid in AUTO_EXCLUDED if self.wardrobe.outfit(c.id, oid)],
                               avatar_url=f"/api/kaibun/characters/{c.id}/avatar",
                               background_url=f"/api/kaibun/characters/{c.id}/background" if c.background else None,
                               stand=stand, stand_bounds=self.stand_bounds.get(c.id)))
        return result

    def voice_signature(self, line):
        character = self.characters.get(line["speaker"])
        voice = line.get("guest_voice") or (character.voice_id if character else os.environ.get("KAIBUN_PRODUCER_VOICE_ID", ""))
        if line["speaker"] == "fuyuko" and line.get("voice_style") == "idol":
            voice = os.environ.get("KAIBUN_FUYUKO_IDOL_VOICE_ID") or voice
        if line['speaker'] == 'nichika' and line.get('nichika_voice_style') == 'idol':
            voice = os.environ.get('KAIBUN_NICHIKA_IDOL_VOICE_ID') or 'b3757a5a71ba4078be1e25b446190975'
        payload = "\n".join((line["ja"], line["emotion"], voice, self.tts_model))
        if line.get("kind") == "thought":
            payload += "\nstory-thought-v2"
        spoken = speech_names(story_voice_text(line, self.tts_model), self.characters)
        if spoken != story_voice_text(line, self.tts_model):
            payload += "\nname-kana-v1\n" + spoken
        relevant = used_in(spoken, getattr(self, 'readings', ()))
        if relevant:
            payload += "\nreadings-v1\n" + json.dumps([(r.written, r.phonemes) for r in relevant], ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()[:24], voice

    async def voice(self, line, voice):
        if not self.tts_key:
            raise VoiceError("还没有配置语音服务")
        text = speech_names(story_voice_text(line, self.tts_model), self.characters)
        if not text.strip():
            raise VoiceError("这句没有可朗读的剧本文字")
        body = dict(text=text, format="mp3", sample_rate=44100, mp3_bitrate=128, latency="normal")
        if voice:
            body["reference_id"] = voice
        if self.dictionary:
            body["pronunciation_dictionary"] = self.dictionary
        proxy = self.proxy.proxy_for('tts')
        for attempt in range(3):
            try:
                async with open_client(proxy, httpx.Timeout(90, connect=15)) as client:
                    response = await client.post(FISH_TTS_HTTP_URL, headers={"Authorization": f"Bearer {self.tts_key}", "model": self.tts_model}, json=body)
                break
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError):
                # These failures occur while establishing the connection, before synthesis.
                if attempt == 2:
                    route = '本机代理连接失败，请检查代理节点和网络' if proxy else '网络连接失败，请检查网络或语音代理配置'
                    raise VoiceError('无法连接 Fish Audio：' + route) from None
                await asyncio.sleep(.5 * (attempt + 1))
            except httpx.TimeoutException:
                raise VoiceError('Fish Audio 响应超时，本次未自动重发，请稍后检查配音后重试') from None
            except httpx.HTTPError:
                raise VoiceError('Fish Audio 连接中断，请稍后重试') from None
        if response.status_code in (401, 403):
            raise VoiceError(f'Fish Audio 拒绝访问（HTTP {response.status_code}），请检查密钥及音色访问权限')
        if response.status_code == 429:
            raise VoiceError('Fish Audio 请求受限（HTTP 429），请稍后重试并检查账户额度')
        if not response.is_success:
            raise VoiceError(f'Fish Audio 未完成配音（HTTP {response.status_code}），请检查服务状态、模型和音色配置')
        if not response.is_success or not response.content or response.headers.get("content-type", "").startswith("application/json"):
            raise VoiceError("Fish Audio 未返回有效音频，请稍后重试")
        return response.content

    async def close(self):
        await self.wardrobe.close()
        await self.background_selector.close()
        await super().close()
