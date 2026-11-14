"""Read-only adapters for the existing project's models and character assets."""

import hashlib
import json
import os
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


def story_voice_text(line, model):
    text = line["ja"]
    if line.get("kind") == "thought":
        # Story thoughts put meaningful words inside parentheses, unlike chat stage directions.
        text = text.translate(str.maketrans("", "", "()（）"))
    return spoken_by(voiced(f"[{line['emotion']}] {text}"), model)


class BackgroundSelector:
    """A separate, small configured model; scene selection never calls the dialogue model."""

    def __init__(self, proxy):
        settings = LLMSettings._from_env("KAIBUN_BACKGROUND", fallback="CHAT")
        self.settings = replace(settings, model=os.environ.get("KAIBUN_BACKGROUND_LLM_MODEL") or settings.model,
                                max_tokens=settings.max_tokens or 4096,
                                reasoning_effort=settings.reasoning_effort or "low")
        self.model = self.settings.model
        self.client = open_client(proxy.proxy_for("chat_llm"), httpx.Timeout(180, connect=15))
        self.llm = open_llm(self.settings, self.client)

    async def complete(self, system, user):
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


class ProjectAdapter:
    def __init__(self):
        self.settings = LLMSettings.chat_from_env()
        self.model = self.settings.model
        self.proxy = proxy_from_env()
        self.client = open_client(self.proxy.proxy_for("chat_llm"), httpx.Timeout(180, connect=15))
        self.llm = open_llm(self.settings, self.client)
        self.characters = load_characters(characters_path_from_env())
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
        self.dictionary = pronunciation_dictionary(self.readings)
        self.tts_model = fish_audio_model_from_env()
        self.tts_key = os.environ.get("FISH_AUDIO_API_KEY", "")
        self.background_selector = BackgroundSelector(self.proxy)
        self.wardrobe = Wardrobe(WardrobeAdapter(self, self.background_selector), data_root() / 'wardrobe')
        self.backgrounds = Backgrounds(self.background_selector, data_root() / 'backgrounds')

    def has_voice(self, cid):
        character = self.characters.get(cid)
        return bool(self.tts_key and (getattr(character, 'voice_id', '') if character else os.environ.get('KAIBUN_PRODUCER_VOICE_ID')))

    async def complete(self, system, user):
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
            result.append(dict(**identity(c),
                               avatar_url=f"/api/kaibun/characters/{c.id}/avatar",
                               background_url=f"/api/kaibun/characters/{c.id}/background" if c.background else None,
                               stand=stand, stand_bounds=self.stand_bounds.get(c.id)))
        return result

    def voice_signature(self, line):
        character = self.characters.get(line["speaker"])
        voice = character.voice_id if character else os.environ.get("KAIBUN_PRODUCER_VOICE_ID", "")
        if line["speaker"] == "fuyuko" and line.get("voice_style") == "idol":
            voice = os.environ.get("KAIBUN_FUYUKO_IDOL_VOICE_ID") or voice
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
            raise ValueError("还没有配置语音服务")
        text = speech_names(story_voice_text(line, self.tts_model), self.characters)
        if not text.strip():
            raise ValueError("这句没有可朗读的剧本文字")
        body = dict(text=text, format="mp3", sample_rate=44100, mp3_bitrate=128, latency="normal")
        if voice:
            body["reference_id"] = voice
        if self.dictionary:
            body["pronunciation_dictionary"] = self.dictionary
        async with open_client(self.proxy.proxy_for("tts"), httpx.Timeout(90, connect=15)) as client:
            response = await client.post(FISH_TTS_HTTP_URL, headers={"Authorization": f"Bearer {self.tts_key}", "model": self.tts_model}, json=body)
        if not response.is_success or not response.content or response.headers.get("content-type", "").startswith("application/json"):
            raise ValueError("配音暂时失败，可关闭声音继续看")
        return response.content

    async def close(self):
        await self.wardrobe.close()
        await self.background_selector.close()
        await self.llm.aclose()
