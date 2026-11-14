from support.llm.anthropic import AnthropicLLM
from support.llm.openai_compat import OpenAICompatLLM
from support.llm.responses import ResponsesLLM
def open_llm(settings, client):
    provider = {"chat-completions": OpenAICompatLLM, "responses": ResponsesLLM, "anthropic": AnthropicLLM}[settings.protocol]
    return provider(settings.base_url, settings.api_key, settings.model, client=client,
                    max_tokens=settings.max_tokens, reasoning_effort=settings.reasoning_effort, extra_body=settings.extra_body)
