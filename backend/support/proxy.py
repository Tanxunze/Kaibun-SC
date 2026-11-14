import os
import httpx
class ProxySettings:
    def proxy_for(self, service):
        services = os.environ.get("KAIBUN_PROXY_SERVICES", "chat_llm,tts").split(",")
        return os.environ.get("KAIBUN_PROXY_URL") or None if service in services or "all" in services else None
def proxy_from_env():
    return ProxySettings()
def open_client(proxy, timeout):
    return httpx.AsyncClient(proxy=proxy, timeout=timeout, trust_env=False)
