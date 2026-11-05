"""Bounded OpenRouter -> Groq failover for the same server-side travel tools."""
import json
import logging
import os
import time

import httpx
from src.services.chat_context import is_corrupt_text as _corrupt_narrative

logger = logging.getLogger(__name__)
DEFAULT_OPENROUTER_FALLBACKS = (
    "google/gemini-2.0-flash-001,google/gemma-4-31b-it:free,"
    "google/gemma-4-26b-a4b-it:free,nvidia/nemotron-3.5-lightning:free,openrouter/free"
)


class AgentUnavailable(RuntimeError):
    pass


def is_configured():
    return any(os.getenv(key, "").strip() for key in ("OPENROUTER_API_KEY", "GROQ_API_KEY"))


def _ids(value):
    return list(dict.fromkeys(m.strip() for m in value.split(",") if m.strip()))


def _free(model):
    return model.endswith(":free") or model == "openrouter/free"


def _targets(preferred_model, preferred_provider):
    router, groq = [], []
    if os.getenv("OPENROUTER_API_KEY", "").strip():
        primary = os.getenv("OPENROUTER_MODEL", "google/gemini-3.5-flash-lite")
        models = _ids(primary + "," + os.getenv("OPENROUTER_FALLBACK_MODELS", DEFAULT_OPENROUTER_FALLBACKS))
        free = _free
        if free(primary) and any(not free(m) for m in models):
            raise AgentUnavailable("Для бесплатной основной модели разрешены только бесплатные резервные модели.")
        if preferred_provider != "groq" and preferred_model and (preferred_model in models or (free(primary) and free(preferred_model))):
            models = list(dict.fromkeys([preferred_model, *models]))
        # OpenRouter rejects more than three model IDs in a request with 400.
        router = [("openrouter", models[i:i + 3]) for i in range(0, len(models), 3)]
    if os.getenv("GROQ_API_KEY", "").strip():
        models = _ids(os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b") + "," +
                      os.getenv("GROQ_FALLBACK_MODELS", "openai/gpt-oss-20b,openai/gpt-oss-120b"))
        if preferred_provider == "groq" and preferred_model in models:
            models = [preferred_model, *[m for m in models if m != preferred_model]]
        groq = [("groq", [m]) for m in models]
    targets = []
    if preferred_provider == "groq" and groq:
        targets.append(groq.pop(0))
    for i in range(max(len(router), len(groq))):
        if i < len(router):
            targets.append(router[i])
        if i < len(groq):
            targets.append(groq[i])
    return targets


def _portable_messages(messages, service):
    # Reasoning signatures belong to the model/provider that produced them.
    allowed = {"role", "content", "tool_calls", "tool_call_id"}
    if service == "openrouter":
        allowed.add("reasoning_details")
    portable = []
    for message in messages:
        item = {k: v for k, v in message.items() if k in allowed}
        if service != "openrouter" and item.get("tool_calls"):
            item["tool_calls"] = [{"id": call["id"], "type": "function", "function": {
                "name": call["function"]["name"], "arguments": call["function"]["arguments"]}}
                for call in item["tool_calls"]]
        portable.append(item)
    return portable


def _wire_schema(value):
    if isinstance(value, list):
        return [_wire_schema(v) for v in value]
    if not isinstance(value, dict):
        return value
    result = {k: _wire_schema(v) for k, v in value.items() if k not in ("title", "default", "examples")}
    return result


def _wire_tools(tools):
    return [{"type": "function", "function": {
        "name": tool["function"]["name"],
        **({"description": tool["function"]["description"][:180]} if "description" in tool["function"] else {}),
        "parameters": _wire_schema(tool["function"]["parameters"])}} for tool in tools]


def _fit_groq_history(messages, tools, byte_limit=24000):
    # Free Groq quotas are small. Drop complete old dialogue turns from this
    # request only; preserve the system state and the entire active tool turn.
    # This is a conservative size heuristic, not a tokenizer or a quota promise.
    fitted = list(messages)
    while len(json.dumps({"messages": fitted, "tools": tools}, ensure_ascii=False).encode("utf-8")) > byte_limit:
        users = [i for i, m in enumerate(fitted) if m.get("role") == "user"]
        if len(users) < 2:
            break
        del fitted[users[0]:users[1]]
    return fitted


def complete(messages, tools, timeout, *, preferred_model=None, preferred_provider=None, tool_choice="auto"):
    tools = _wire_tools(tools)
    targets = _targets(preferred_model, preferred_provider)
    if not targets:
        raise AgentUnavailable("Добавьте OPENROUTER_API_KEY или GROQ_API_KEY в .env и перезапустите приложение.")
    deadline = time.monotonic() + timeout
    last_status = None
    blocked_services = set()
    for index, (service, models) in enumerate(targets):
        if service in blocked_services:
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        # Reserve time for the independent provider instead of spending the
        # entire chat deadline on an unavailable first endpoint.
        window = remaining if len(targets) == 1 else min(20, remaining / min(len(targets) - index, 3))
        endpoint_deadline = time.monotonic() + window
        key = os.environ["OPENROUTER_API_KEY" if service == "openrouter" else "GROQ_API_KEY"]
        base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1") if service == "openrouter" else os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        payload = {"messages": _fit_groq_history(_portable_messages(messages, service), tools, 32000), "tools": tools,
                   "tool_choice": tool_choice, "max_tokens": 2000}
        if service == "openrouter":
            payload.update(provider={"require_parameters": True})
            payload["models" if len(models) > 1 else "model"] = models if len(models) > 1 else models[0]
        else:
            payload.update(model=models[0], parallel_tool_calls=False, max_tokens=1500,
                           messages=_fit_groq_history(payload["messages"], tools))
            if models[0].startswith("openai/gpt-oss-"):
                payload["reasoning_effort"] = "low"
        for attempt in range(2):
            remaining = min(endpoint_deadline, deadline) - time.monotonic()
            if remaining <= 0:
                break
            try:
                response = httpx.post(base.rstrip("/") + "/chat/completions",
                    headers={"Authorization": "Bearer " + key, "X-OpenRouter-Title": "TravelAIChatbot"} if service == "openrouter" else {"Authorization": "Bearer " + key},
                    json=payload, timeout=httpx.Timeout(remaining, connect=min(3, remaining)))
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                error = body.get("error") if isinstance(body, dict) else None
                status = response.status_code
                if isinstance(error, dict) and isinstance(error.get("code"), int):
                    status = error["code"]
                if not error and status < 400:
                    answer = body["choices"][0]["message"]
                    if not isinstance(answer, dict) or not (answer.get("tool_calls") or (isinstance(answer.get("content"), str) and answer["content"].strip())):
                        raise ValueError("empty response")
                    if isinstance(tool_choice, dict) and not answer.get("tool_calls"):
                        raise ValueError("required tool action missing")
                    if not answer.get("tool_calls") and (_corrupt_narrative(answer.get("content", "")) or
                        body["choices"][0].get("finish_reason") == "length"):
                        raise ValueError("corrupt or truncated narrative")
                    calls = answer.get("tool_calls") or []
                    if not isinstance(calls, list) or any(not isinstance(call, dict) or
                        not isinstance(call.get("id"), str) or not isinstance(call.get("function"), dict) or
                        not isinstance(call["function"].get("name"), str) or not isinstance(call["function"].get("arguments"), str)
                        for call in calls):
                        raise ValueError("invalid tool call structure")
                    usage = body.get("usage") or {}
                    return {**answer, "_model": body.get("model", models[0]), "_provider": service,
                            "_request_bytes": len(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
                            "_usage": {k: usage.get(k, 0) if isinstance(usage, dict) else 0 for k in ("prompt_tokens", "completion_tokens")}}
                last_status = status
                metadata = error.get("metadata") if isinstance(error, dict) else None
                raw = str(metadata.get("raw", "")) if isinstance(metadata, dict) else ""
                if isinstance(error, dict):
                    raw += " " + str(error.get("message", ""))
                hints = [hint for hint in ("tool_choice", "reasoning", "schema", "messages", "context", "max_tokens") if hint in raw.lower()]
                # Never log headers, prompts, provider raw errors or the key.
                logger.warning("LLM rejection: service=%s status=%s hints=%s", service, status, hints)
                if status == 402 and service == "openrouter" and any(not _free(m) for m in models):
                    # A paid model's lack of credit must not hide free reserves,
                    # including a free model in the very same <=3-model batch.
                    remaining_targets = []
                    free_here = [m for m in models if _free(m)]
                    if free_here:
                        remaining_targets.append((service, free_here))
                    for target_service, target_models in targets[index + 1:]:
                        eligible = [m for m in target_models if _free(m)] if target_service == "openrouter" else target_models
                        if eligible:
                            remaining_targets.append((target_service, eligible))
                    targets[index + 1:] = remaining_targets
                    break
                if status in (401, 402, 403):
                    blocked_services.add(service)
                    break
                if attempt == 0 and status == 400 and (isinstance(payload["tool_choice"], dict) or (service == "openrouter" and len(models) > 1)):
                    portable = _portable_messages(payload["messages"], "groq")
                    instruction = ""
                    if isinstance(payload["tool_choice"], dict):
                        function = payload["tool_choice"]["function"]["name"]
                        instruction = f"\nВ этом ходе выполни действие инструментом {function}. Не заменяй вызов описанием или обещанием в тексте."
                    if portable and portable[0].get("role") == "system":
                        portable[0]["content"] += instruction
                    else:
                        portable.insert(0, {"role": "system", "content": instruction})
                    payload = {**payload, "tool_choice": "auto", "messages": portable}
                    if service == "openrouter" and len(models) > 1:
                        # Do not repeat the same failing head of the model chain.
                        payload.pop("model", None)
                        payload["models"] = models[1:]
                    continue
                if attempt == 0 and len(targets) == 1 and status in (400, 408, 500, 502, 503, 504):
                    continue
                break
            except (httpx.RequestError, KeyError, IndexError, TypeError, ValueError):
                last_status = None
                logger.warning("LLM request failed: service=%s category=network_or_response", service)
                break
    if last_status == 429:
        raise AgentUnavailable("Достигнут лимит запросов доступных ИИ-провайдеров (HTTP 429). Повторите позже.")
    if last_status in (401, 402, 403):
        raise AgentUnavailable(f"ИИ-провайдеры отклонили доступ (HTTP {last_status}). Проверьте настройки ключей и доступность моделей.")
    if last_status == 400:
        raise AgentUnavailable("Провайдеры не смогли обработать запрос (HTTP 400). История и ваш план сохранены; попробуйте отправить сообщение ещё раз.")
    raise AgentUnavailable("Не удалось получить ответ доступных ИИ-провайдеров. История и ваш план сохранены; повторите позже.")
