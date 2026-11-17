import os, json, logging
from dataclasses import dataclass
from typing import Any, Literal, get_args
from urllib.parse import urlsplit
FishAudioModel = Literal["s2.1-pro-free", "s2.1-pro", "drama-3", "s2-pro", "s1"]

FISH_AUDIO_MODELS: tuple[FishAudioModel, ...] = get_args(FishAudioModel)

DEFAULT_FISH_AUDIO_MODEL: FishAudioModel = "s2.1-pro-free"

LLMProtocol = Literal["chat-completions", "responses", "anthropic"]

LLM_PROTOCOLS: tuple[LLMProtocol, ...] = get_args(LLMProtocol)

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]

REASONING_EFFORTS: tuple[ReasoningEffort, ...] = get_args(ReasoningEffort)

EFFORT_NAMES: dict[ReasoningEffort, str] = {
    "none": "关闭",
    "minimal": "极低",
    "low": "低",
    "medium": "中",
    "high": "高",
    "xhigh": "极高",
    "max": "最高",
}

NOT_ON_ANTHROPIC: frozenset[ReasoningEffort] = frozenset({"minimal"})

EXTRA_BODY_REFUSED = (
    "model", "stream", "stream_options", "messages", "input", "instructions", "system",
    "tools", "tool_choice",
)

def checked_extra_body(value: object) -> dict[str, Any]:
    """`value` as an extra request body, merged into each request last; raises ValueError
    saying why it is not one: it must be a JSON object, and not set what makes the
    request (`EXTRA_BODY_REFUSED`). What it sets of thinking is up to the deployer."""
    if not isinstance(value, dict):
        raise ValueError("额外请求参数需要是一个 JSON 对象，例如 {\"enable_thinking\": false}")
    if refused := [key for key in EXTRA_BODY_REFUSED if key in value]:
        keys = "、".join(f"「{key}」" for key in refused)
        raise ValueError(f"额外请求参数不能包含 {keys}：这些由服务器生成，改了会弄坏请求")
    return value

def effort_problem(effort: object, protocol: str) -> str | None:
    """Why `effort` is not one a model on `protocol` may be set to, if it is not."""
    if effort not in REASONING_EFFORTS:
        return f"思考强度只能是 {'、'.join(REASONING_EFFORTS)} 之一，而不是 {effort}"
    if protocol == "anthropic" and effort in NOT_ON_ANTHROPIC:
        return f"Anthropic 接口没有「{EFFORT_NAMES[effort]}」（{effort}）这一档"
    return None

@dataclass(frozen=True)
class LLMSettings:
    """One model slot: the protocol its service speaks, where it is, and which model."""

    base_url: str
    api_key: str
    model: str
    protocol: LLMProtocol = "chat-completions"
    max_tokens: int | None = None
    """A cap on each reply's length; the Anthropic protocol needs one and has a default."""
    reasoning_effort: ReasoningEffort | None = None
    """None to send none, leaving it to the model."""
    extra_body: dict[str, Any] | None = None
    """Merged into every request last (see `checked_extra_body`)."""

    @classmethod
    def optional_from_env(cls, slot: str, fallback: str | None = None) -> "LLMSettings | None":
        slots = [slot, fallback] if fallback else [slot]
        for field in ("BASE_URL", "API_KEY", "MODEL"):
            if not any(os.environ.get(f"{name}_LLM_{field}") for name in slots):
                return None
        return cls._from_env(slot, fallback)

    @classmethod
    def chat_from_env(cls) -> "LLMSettings":
        return cls._from_env("CHAT")

    @classmethod
    def background_from_env(cls) -> "LLMSettings":
        """The background model; each setting left unset is the chat model's."""
        return cls._from_env("BACKGROUND", fallback="CHAT")

    @classmethod
    def _from_env(cls, slot: str, fallback: str | None = None) -> "LLMSettings":
        def value(name: str) -> str | None:
            names = [f"{slot}_LLM_{name}"] + ([f"{fallback}_LLM_{name}"] if fallback else [])
            return next((v for n in names if (v := os.environ.get(n))), None)

        def required(name: str) -> str:
            if found := value(name):
                return found
            alternative = f"（或 {fallback}_LLM_{name}）" if fallback else ""
            raise RuntimeError(f"环境变量 {slot}_LLM_{name}{alternative}未设置")

        protocol = value("PROTOCOL") or "chat-completions"
        if protocol not in LLM_PROTOCOLS:
            raise RuntimeError(
                f"环境变量 {slot}_LLM_PROTOCOL 只能是 {'、'.join(LLM_PROTOCOLS)}，而不是 {protocol}"
            )
        # Each slot's own: a cap that suits the chat could cut a drafted sheet short.
        max_tokens = os.environ.get(f"{slot}_LLM_MAX_TOKENS") or None
        if max_tokens is not None and not (
            max_tokens.isascii() and max_tokens.isdigit() and int(max_tokens) > 0
        ):
            raise RuntimeError(f"环境变量 {slot}_LLM_MAX_TOKENS 需要是正整数，而不是 {max_tokens}")
        # So are the effort and the extra body: the chat's may not suit drafting a sheet.
        effort = effort_from_env(f"{slot}_LLM_REASONING_EFFORT", protocol)
        extra_body = None
        if text := os.environ.get(f"{slot}_LLM_EXTRA_BODY", "").strip():
            try:
                extra_body = checked_extra_body(json.loads(text))
            except json.JSONDecodeError as e:
                raise RuntimeError(f"环境变量 {slot}_LLM_EXTRA_BODY 不是合法的 JSON：{e}") from None
            except ValueError as e:
                raise RuntimeError(f"环境变量 {slot}_LLM_EXTRA_BODY 有误：{e}") from None
        return cls(
            base_url=required("BASE_URL"),
            api_key=required("API_KEY"),
            model=required("MODEL"),
            protocol=protocol,  # pyright: ignore[reportArgumentType]  # checked above
            max_tokens=int(max_tokens) if max_tokens else None,
            reasoning_effort=effort,
            extra_body=extra_body,
        )

def effort_from_env(name: str, protocol: str) -> ReasoningEffort | None:
    """The reasoning effort `.env` sets in `name` for a model on `protocol`; None if it sets
    none. Raises RuntimeError if it is not one such a model may be set to."""
    effort = os.environ.get(name, "").strip() or None
    if effort is not None and (problem := effort_problem(effort, protocol)):
        raise RuntimeError(f"环境变量 {name} 有误：{problem}")
    return effort

def fish_audio_model_from_env() -> FishAudioModel:
    model = (os.environ.get("FISH_AUDIO_MODEL") or "").strip() or DEFAULT_FISH_AUDIO_MODEL
    if model not in FISH_AUDIO_MODELS:
        raise RuntimeError(
            f"环境变量 FISH_AUDIO_MODEL 只能是 {'、'.join(FISH_AUDIO_MODELS)}，而不是 {model}"
        )
    return model
