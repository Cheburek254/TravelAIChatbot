import os
import unittest
from unittest.mock import patch

import httpx

from src.services.llm_gateway import AgentUnavailable, complete, is_configured


def response(status=200, model="qwen/qwen3.8-27b", *, content="Готово", error=None, tool=False):
    body = {"error": {"code": status, "message": error or "private-provider-error"}} if status >= 400 else {
        "model": model, "choices": [{"message": {"role": "assistant", "content": content}}]}
    if tool and status < 400:
        body["choices"][0]["message"] = {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call-1", "type": "function", "function": {"name": "build_trip_plan", "arguments": "{}"}}]}
    return httpx.Response(status, request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"), json=body)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "OPENROUTER_API_KEY": "router-secret", "OPENROUTER_MODEL": "google/gemma-4-31b-it:free",
            "OPENROUTER_FALLBACK_MODELS": "nvidia/nemotron-3.5-lightning:free,openrouter/free",
            "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
            "GROQ_API_KEY": "groq-secret", "GROQ_BASE_URL": "https://api.groq.com/openai/v1",
            "GROQ_MODEL": "qwen/qwen3.8-27b", "GROQ_FALLBACK_MODELS": "openai/gpt-oss-20b,openai/gpt-oss-120b",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.messages = [{"role": "system", "content": "Бюджет 100000"}, {"role": "user", "content": "Подбери Сочи"}]
        self.tools = [{"type": "function", "function": {"name": "build_trip_plan", "parameters": {"type": "object"}}}]

    def test_router_rate_limit_switches_to_independent_groq_key(self):
        messages = self.messages + [{"role": "assistant", "content": None, "tool_calls": [], "reasoning_details": [{"opaque": "signature"}]}]
        with patch("httpx.post", side_effect=[response(429), response()]) as post:
            result = complete(messages, self.tools, 40)
        self.assertEqual(result["_provider"], "groq")
        first, second = post.call_args_list
        self.assertEqual(first.args[0], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(second.args[0], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(second.kwargs["headers"]["Authorization"], "Bearer groq-secret")
        payload = second.kwargs["json"]
        self.assertNotIn("models", payload)
        self.assertNotIn("provider", payload)
        self.assertNotIn("reasoning_details", payload["messages"][-1])
        self.assertEqual(payload["messages"][:2], self.messages)
        self.assertEqual(payload["tools"], self.tools)

    def test_persistent_named_tool_400_falls_back_to_groq(self):
        forced = {"type": "function", "function": {"name": "build_trip_plan"}}
        with patch("httpx.post", side_effect=[response(400), response(400), response(tool=True)]) as post:
            result = complete(self.messages, self.tools, 40, tool_choice=forced)
        self.assertEqual(post.call_count, 3)
        self.assertEqual(post.call_args_list[1].kwargs["json"]["tool_choice"], "auto")
        self.assertEqual(result["_provider"], "groq")
        self.assertEqual(self.messages[0]["content"], "Бюджет 100000")

    def test_missing_required_tool_action_uses_reserve_instead_of_plain_promise(self):
        forced = {"type": "function", "function": {"name": "build_trip_plan"}}
        with patch("httpx.post", side_effect=[response(content="Всё собрал!"), response(tool=True)]) as post:
            result = complete(self.messages, self.tools, 40, tool_choice=forced)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(result["_provider"], "groq")
        self.assertTrue(result["tool_calls"])

    def test_groq_model_rate_limit_tries_next_model(self):
        with patch("httpx.post", side_effect=[response(503), response(429), response(model="openai/gpt-oss-20b")]) as post:
            result = complete(self.messages, self.tools, 40)
        self.assertEqual(post.call_count, 3)
        self.assertEqual(post.call_args.kwargs["json"]["model"], "openai/gpt-oss-20b")
        self.assertEqual(result["_model"], "openai/gpt-oss-20b")

    def test_failed_groq_key_is_not_retried_with_other_groq_models(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}), patch("httpx.post", return_value=response(401)) as post:
            with self.assertRaises(AgentUnavailable) as caught:
                complete(self.messages, self.tools, 40)
        self.assertEqual(post.call_count, 1)
        for secret in ("router-secret", "groq-secret", "private-provider-error"):
            self.assertNotIn(secret, str(caught.exception))

    def test_successful_groq_model_is_preferred_for_next_tool_step(self):
        with patch("httpx.post", return_value=response(model="openai/gpt-oss-120b")) as post:
            result = complete(self.messages, self.tools, 40,
                              preferred_provider="groq", preferred_model="openai/gpt-oss-120b")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[0], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "openai/gpt-oss-120b")
        self.assertEqual(result["_provider"], "groq")

    def test_network_failure_and_empty_response_do_not_prevent_failover(self):
        with patch("httpx.post", side_effect=[httpx.ConnectTimeout("private-network-detail"), response(content=""), response(model="openai/gpt-oss-20b")]) as post:
            result = complete(self.messages, self.tools, 40)
        self.assertEqual(post.call_count, 3)
        self.assertEqual(result["_provider"], "groq")

    def test_only_groq_key_also_enables_ai(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}), patch("httpx.post", return_value=response()) as post:
            self.assertTrue(is_configured())
            self.assertEqual(complete(self.messages, self.tools, 40)["_provider"], "groq")
        self.assertEqual(post.call_count, 1)

    def test_paid_router_402_retries_free_models_in_the_same_batch(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "", "OPENROUTER_MODEL": "google/gemini-2.5-flash",
            "OPENROUTER_FALLBACK_MODELS": "google/gemini-2.0-flash-001,google/gemma-4-31b-it:free,openrouter/free"}), patch(
            "httpx.post", side_effect=[response(402), response(model="google/gemma-4-31b-it:free")]) as post:
            result = complete(self.messages, self.tools, 40)
        self.assertEqual(result["_model"], "google/gemma-4-31b-it:free")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs["json"]["model"], "google/gemma-4-31b-it:free")

    def test_402_on_all_free_models_is_bounded(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "", "OPENROUTER_MODEL": "google/gemini-2.5-flash",
            "OPENROUTER_FALLBACK_MODELS": "google/gemma-4-31b-it:free,openrouter/free"}), patch("httpx.post", return_value=response(402)) as post:
            with self.assertRaises(AgentUnavailable):
                complete(self.messages, self.tools, 40)
        self.assertEqual(post.call_count, 2)

    def test_all_endpoints_failing_is_bounded_and_sanitized(self):
        with patch("httpx.post", return_value=response(400)) as post:
            with self.assertRaises(AgentUnavailable) as caught:
                complete(self.messages, self.tools, 40)
        self.assertEqual(post.call_count, 5)
        self.assertNotIn("private-provider-error", str(caught.exception))

    def test_400_rotates_router_models_and_strips_provider_tool_extensions(self):
        messages = self.messages + [{"role": "assistant", "content": None, "reasoning_details": [{"opaque": "signature"}],
            "tool_calls": [{"id": "call-1", "type": "function", "extra_content": {"google": "signature"},
                            "function": {"name": "build_trip_plan", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call-1", "content": "done"}]
        forced = {"type": "function", "function": {"name": "build_trip_plan"}}
        with patch("httpx.post", side_effect=[response(400), response(tool=True)]) as post:
            complete(messages, self.tools, 40, tool_choice=forced)
        retried = post.call_args.kwargs["json"]
        self.assertNotIn("google/gemma-4-31b-it:free", retried["models"])
        self.assertNotIn("reasoning_details", retried["messages"][-2])
        self.assertNotIn("extra_content", retried["messages"][-2]["tool_calls"][0])

    def test_wire_schema_is_smaller_but_preserves_nullable_semantics(self):
        from src.services.llm_gateway import _wire_tools
        import json
        tools = [{"type": "function", "function": {"name": "test", "description": "description " * 100,
                 "parameters": {"type": "object", "properties": {"budget": {"anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}], "default": None, "title": "Budget"}}}}}]
        compact = _wire_tools(tools)
        self.assertLess(len(json.dumps(compact)), len(json.dumps(tools)) / 2)
        self.assertEqual(compact[0]["function"]["parameters"]["properties"]["budget"]["anyOf"], [{"type": "integer", "minimum": 1}, {"type": "null"}])

    def test_large_router_pool_is_batched_to_api_limit_and_all_models_are_reachable(self):
        models = [f"vendor/model-{i}:free" for i in range(8)]
        with patch.dict(os.environ, {"GROQ_API_KEY": "", "OPENROUTER_MODEL": models[0],
                                    "OPENROUTER_FALLBACK_MODELS": ",".join(models[1:])}), patch(
            "httpx.post", side_effect=[response(503), response(503), response(model=models[-1])]) as post:
            result = complete(self.messages, self.tools, 40)
        self.assertEqual(post.call_count, 3)
        sent = [call.kwargs["json"].get("models", [call.kwargs["json"].get("model")]) for call in post.call_args_list]
        self.assertTrue(all(len(group) <= 3 for group in sent))
        self.assertEqual([model for group in sent for model in group], models)
        self.assertEqual(result["_model"], models[-1])

    def test_mixed_script_corruption_uses_another_provider(self):
        with patch("httpx.post", side_effect=[response(content="cdnjs Пхукет — ани有效 в плане цены"), response(content="Могу предложить подходящие направления.")]) as post:
            result = complete(self.messages, self.tools, 40)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(result["_provider"], "groq")
        self.assertNotIn("cdnjs", result["content"])

    def test_truncated_narrative_is_not_published(self):
        truncated = response(content="А вот Сочи в пределах бюджета за Pf")
        body = truncated.json()
        body["choices"][0]["finish_reason"] = "length"
        truncated = httpx.Response(200, request=truncated.request, json=body)
        with patch("httpx.post", side_effect=[truncated, response(content="Уточните пожелания к поездке.")]) as post:
            result = complete(self.messages, self.tools, 40)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(result["content"], "Уточните пожелания к поездке.")

    def test_groq_trims_whole_old_turns_preserving_active_tools_and_saved_messages(self):
        messages = [self.messages[0], {"role": "user", "content": "старый вопрос " * 1500},
                    {"role": "assistant", "content": "старый ответ " * 1500}, self.messages[1],
                    {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "build_trip_plan", "arguments": "{}"}}]},
                    {"role": "tool", "tool_call_id": "call-1", "content": "current result"}]
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}), patch("httpx.post", return_value=response()) as post:
            complete(messages, self.tools, 40)
        sent = post.call_args.kwargs["json"]["messages"]
        self.assertEqual(sent, [messages[0], *messages[3:]])
        self.assertEqual(len(messages), 6)
