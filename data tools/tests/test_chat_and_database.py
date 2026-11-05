import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import update

from src.api.app import app
from src.services import database as db
from src.services.agent_orchestrator import build_trip_response
from src.services.hotel_service import HotelService
from src.services.logistics_engine import FairPriceCalculator
from src.services.openrouter_agent import AgentUnavailable, _completion, run_openrouter_turn


def tool_message(name, arguments, call_id="call-1"):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {
            "name": name, "arguments": json.dumps(arguments),
        }},
    ]}


class ChatDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "DATABASE_URL": "sqlite:///" + str(Path(self.temp.name) / "test.db"),
            "OFFLINE_MODE": "1", "OPENROUTER_API_KEY": "", "GROQ_API_KEY": "",
        })
        self.env.start()
        self.old_engine = db._engine
        db._engine = None
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        db._engine.dispose()
        db._engine = self.old_engine
        self.env.stop()
        self.temp.cleanup()

    def test_sql_seed_is_idempotent_and_updates_reach_json(self):
        original = HotelService._load_data()
        first = original[0]
        with db.get_engine().begin() as conn:
            conn.execute(update(db.hotels).where(db.hotels.c.id == first["id"]).values(price_per_night=12345))
        db._engine.dispose()
        db._engine = None
        result = HotelService._load_data()
        self.assertEqual(len(result), len(original))
        self.assertEqual(next(h for h in result if h["id"] == first["id"])["price_per_night"], 12345)
        response = self.client.post("/api/tools/hotels", json={"destination": first["destination_name"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(next(h for h in response.json()["hotels"] if h["id"] == first["id"])["price_per_night"], 12345)

    def test_browser_sessions_and_reload_history_are_isolated(self):
        for sid in ("browser-a", "browser-b"):
            self.assertEqual(self.client.get("/api/trips/initial", params={"session_id": sid}).status_code, 200)
        response = self.client.post("/api/chat", json={
            "session_id": "browser-a", "message": "Хочу в Дубай на неделю вдвоём, бюджет 400 тыс", "selected_option": "A",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.load_session("browser-a")["state"]["destination"], "Дубай")
        self.assertEqual(db.load_session("browser-b")["state"], {})
        reloaded = self.client.get("/api/trips/initial", params={"session_id": "browser-a"}).json()
        self.assertEqual(len(reloaded["messages"]), 2)
        self.assertIn("Дубай", reloaded["A"]["title"])
        a = self.client.post("/api/chat", json={"message": "Хочу в Дубай"}).json()
        b = self.client.post("/api/chat", json={"message": "Хочу в Сочи"}).json()
        self.assertNotEqual(a["sessionId"], b["sessionId"])

    def test_openrouter_builds_then_selects_option_b(self):
        answers = [
            tool_message("build_trip_plan", {"destination": "Сочи", "checkin_date": "2027-01-30", "nights": 5, "pet_friendly": False}),
            tool_message("show_trip_option", {"selected_option": "B", "view_mode": "checkout"}, "call-2"),
            {"role": "assistant", "content": "Готово: вариант Б на пять ночей. Открываю демооформление."},
        ]
        answers[0]["tool_calls"] += answers[1]["tool_calls"]
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", side_effect=answers
        ) as completion:
            result = run_openrouter_turn("llm-browser", "Сочи на пять ночей с 30 января, выбери Б", "A")
        self.assertEqual(result["selectedOption"], "B")
        self.assertEqual(result["viewMode"], "checkout")
        self.assertIn("04.02.2027", result["updatedOptions"]["B"]["dates"])
        session = db.load_session("llm-browser")
        self.assertEqual(session["selected_option"], "B")
        self.assertEqual(session["state"]["nights"], 5)
        self.assertEqual(len(session["messages"]), 2)
        self.assertEqual(completion.call_count, 1)

    def test_successful_plan_does_not_need_another_model_request(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", side_effect=[
                tool_message("build_trip_plan", {"destination": "Сочи"}), AgentUnavailable("timeout"),
            ],
        ) as completion:
            response = self.client.post("/api/chat", json={"session_id": "failed-chat", "message": "Сочи"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(completion.call_count, 1)
        self.assertEqual(db.load_session("failed-chat")["state"]["destination"], "Сочи")
        self.assertTrue(response.json()["updatedOptions"])

    def test_groq_only_configuration_and_reported_provider(self):
        answer = {**tool_message("build_trip_plan", {"destination": "Сочи"}),
                  "_model": "qwen/qwen3.8-27b", "_provider": "groq"}
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "", "GROQ_API_KEY": "groq-test-key"}), patch(
            "src.services.openrouter_agent._completion", return_value=answer):
            initial = self.client.get("/api/trips/initial", params={"session_id": "groq-only-browser"}).json()
            self.assertEqual(initial["agent"], "groq")
            result = self.client.post("/api/chat", json={"session_id": "groq-only-browser", "message": "Собери Сочи до 100 тыс"}).json()
        self.assertEqual(result["agent"], "groq")
        self.assertEqual(result["providers_used"], ["groq"])
        self.assertTrue(result["updatedOptions"])
        self.assertEqual(result["budget_rub"], 100000)

    def test_openrouter_http_contract_and_secret_not_exposed(self):
        req = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        response = httpx.Response(200, request=req, json={"choices": [{"message": {"role": "assistant", "content": "Привет"}}]})
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("httpx.post", return_value=response) as post:
            self.assertEqual(_completion([], 3)["content"], "Привет")
            self.assertEqual(post.call_args.args[0], "https://openrouter.ai/api/v1/chat/completions")
            self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer test-key")
            self.assertEqual(len(post.call_args.kwargs["json"]["tools"]), 6)
        response = httpx.Response(401, request=req, json={"error": "secret-provider-detail"})
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("httpx.post", return_value=response):
            with self.assertRaises(AgentUnavailable) as caught:
                _completion([], 3)
        self.assertNotIn("secret-provider-detail", str(caught.exception))

    def test_constraints_and_replanning_keep_dates_and_hotels(self):
        result, state = build_trip_response("", {}, intent={"destination": "Сочи", "checkin_date": "2027-01-30", "nights": 4})
        changed, changed_state = build_trip_response("", state, intent={"nights": 7, "has_meal_addon": True})
        self.assertEqual(changed_state["checkout_date"], "2027-02-06")
        self.assertEqual(result["updatedOptions"]["A"]["hotel"]["id"], changed["updatedOptions"]["A"]["hotel"]["id"])
        self.assertEqual(changed["updatedOptions"]["A"]["fairPriceBreakdown"]["meal_addon_rub"], 5200)
        impossible, _ = build_trip_response("", {}, intent={"destination": "Неизвестный город", "pet_friendly": True})
        self.assertFalse(impossible["trip_assembled"])
        self.assertEqual(impossible["updatedOptions"], {})

    def test_400_retries_named_tool_as_auto_without_losing_context(self):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        rejected = httpx.Response(400, request=request, json={"error": {"code": 400,
            "metadata": {"provider_name": "test", "raw": "unsupported tool_choice secret-detail"}}})
        success = httpx.Response(200, request=request, json={"model": "test/free:free", "choices": [
            {"message": tool_message("build_trip_plan", {"destination": "Сочи"})}]})
        messages = [{"role": "system", "content": "Keep the budget"}, {"role": "user", "content": "Собери Сочи до 100000"}]
        forced = {"type": "function", "function": {"name": "build_trip_plan"}}
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("httpx.post", side_effect=[rejected, success]) as post:
            result = _completion(messages, 5, tool_choice=forced)
        self.assertEqual(post.call_count, 2)
        first, second = [call.kwargs["json"] for call in post.call_args_list]
        self.assertEqual(first["tool_choice"], forced)
        self.assertEqual(second["tool_choice"], "auto")
        self.assertEqual(second["messages"][1], messages[1])
        self.assertEqual(messages[0]["content"], "Keep the budget")
        self.assertEqual(first["tools"], second["tools"])
        self.assertEqual(result["tool_calls"][0]["function"]["name"], "build_trip_plan")

    def test_persistent_400_is_bounded_and_does_not_expose_provider_details(self):
        response = httpx.Response(400, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
            json={"error": {"code": 400, "message": "secret-provider-detail"}})
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_FALLBACK_MODELS": ""}), patch("httpx.post", return_value=response) as post:
            with self.assertRaises(AgentUnavailable) as caught:
                _completion([], 5)
        self.assertEqual(post.call_count, 2)
        self.assertNotIn("secret-provider-detail", str(caught.exception))
        self.assertNotIn("баланс", str(caught.exception))

    def test_temporary_non_json_error_retries(self):
        request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
        rejected = httpx.Response(503, request=request, text="Service unavailable")
        success = httpx.Response(200, request=request, json={"choices": [
            {"message": {"role": "assistant", "content": "ok"}}]})
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("httpx.post", side_effect=[rejected, success]) as post:
            self.assertEqual(_completion([], 5)["content"], "ok")
        self.assertEqual(post.call_count, 2)

    def test_auth_error_does_not_retry(self):
        response = httpx.Response(401, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
            json={"error": {"code": 401}})
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("httpx.post", return_value=response) as post:
            with self.assertRaises(AgentUnavailable):
                _completion([], 5)
        self.assertEqual(post.call_count, 1)

    def test_only_complete_prices_inside_budget_reach_cards(self):
        result, state = build_trip_response("", {}, intent={
            "destination": "Сочи", "budget_rub": 100000, "nights": 4, "passengers": 2})
        self.assertTrue(result["trip_assembled"])
        self.assertEqual(result["available_option_count"], 1)
        self.assertFalse(result["updatedOptions"]["B"]["available"])
        for option in result["updatedOptions"].values():
            price = option["fairPriceBreakdown"]
            self.assertLessEqual(price["grand_total_rub"] + price["refundable_deposit_rub"], 100000)

    def test_impossible_dubai_budget_clears_cards_instead_of_overspending(self):
        result, state = build_trip_response("", {}, intent={
            "destination": "Дубай", "budget_rub": 100000, "nights": 7, "passengers": 2})
        self.assertEqual(result["updatedOptions"], {})
        self.assertFalse(result["trip_assembled"])
        self.assertGreater(result["minimum_price_rub"], 100000)
        self.assertEqual(state["plan_status"], "unavailable")

    def test_budget_is_remembered_before_build_and_model_cannot_raise_it(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", return_value={"role": "assistant", "content": "Какое направление?"}):
            run_openrouter_turn("budget-memory", "Бюджет максимум 100 000 ₽", "A")
        self.assertEqual(db.load_session("budget-memory")["state"]["budget_rub"], 100000)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", return_value=tool_message("build_trip_plan", {
                "destination": "Дубай", "nights": 7, "passengers": 2, "budget_rub": 300000})):
            result = run_openrouter_turn("budget-memory", "Да, собери в Дубай", "A")
        self.assertEqual(result["budget_rub"], 100000)
        self.assertEqual(result["updatedOptions"], {})
        self.assertNotIn("budget_respected", result["reply"])

    def test_search_results_are_assembled_without_an_extra_model_round(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", return_value=tool_message("search_hotels", {
                "destination": "Сочи", "guests": 2, "limit": 2})) as completion:
            result = run_openrouter_turn("search-cards", "Подбери отели в Сочи, бюджет 100 тыс", "A")
        self.assertTrue(result["updatedOptions"])
        self.assertIn("справа", result["reply"])
        self.assertEqual(completion.call_count, 1)
        for option in result["updatedOptions"].values():
            price = option["fairPriceBreakdown"]
            self.assertLessEqual(price["grand_total_rub"] + price["refundable_deposit_rub"], 100000)

    def test_model_route_string_does_not_replace_explicit_destination(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", return_value=tool_message("build_trip_plan", {
                "destination": "Moscow → Sochi", "origin": "Moscow", "nights": 4})):
            result = run_openrouter_turn("route-string-destination", "Собери Сочи, максимум 100 000 рублей", "A")
        self.assertEqual(result["planStatus"], "ready")
        self.assertEqual(db.load_session("route-string-destination")["state"]["destination"], "Сочи")
        self.assertEqual(db.load_session("route-string-destination")["state"]["origin"], "Москва")

    def test_model_cannot_change_explicit_user_destination(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", return_value=tool_message("build_trip_plan", {
                "destination": "Дубай", "nights": 4})):
            result = run_openrouter_turn("explicit-destination", "Собери Сочи, максимум 100 000 рублей", "A")
        self.assertEqual(result["planStatus"], "ready")
        self.assertEqual(db.load_session("explicit-destination")["state"]["destination"], "Сочи")

    def test_english_catalog_id_from_model_is_normalized(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", return_value=tool_message("build_trip_plan", {
                "destination": "Moscow → Sochi", "nights": 4})):
            result = run_openrouter_turn("catalog-id-destination", "Собери этот вариант до 100 тысяч", "A")
        self.assertEqual(result["planStatus"], "ready")
        self.assertEqual(db.load_session("catalog-id-destination")["state"]["destination"], "Сочи")

    def test_model_cannot_lower_user_budget_or_prevent_affordable_altay_cards(self):
        session = db.load_session("altay-user-cap")
        session["state"] = {"budget_rub": 150000, "user_budget_rub": 150000}
        db.save_session(session)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", return_value=tool_message("build_trip_plan", {
                "destination": "Алтай", "nights": 4, "passengers": 2, "budget_rub": 58000})):
            result = run_openrouter_turn("altay-user-cap", "Собери Алтай на четыре ночи", "A")
        self.assertEqual(result["budget_rub"], 150000)
        self.assertEqual(result["planStatus"], "ready")
        self.assertTrue(result["updatedOptions"])
        self.assertEqual(result["planMessage"], "")
        self.assertEqual(db.load_session("altay-user-cap")["state"]["budget_rub"], 150000)

    def test_show_cards_repairs_legacy_budget_from_user_history_without_llm(self):
        failed, state = build_trip_response("", {}, intent={"destination": "Алтай", "budget_rub": 58000, "nights": 4})
        self.assertEqual(failed["updatedOptions"], {})
        session = db.load_session("altay-legacy-cards")
        session.update(state=state, messages=[
            {"role": "user", "content": "Мой бюджет максимум 150 000 ₽"},
            {"role": "assistant", "content": "Вариант A 178 600 ₽, вариант B 58 200 ₽"},
        ])
        db.save_session(session)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion") as completion:
            result = run_openrouter_turn("altay-legacy-cards", "покажи карточки", "A")
        completion.assert_not_called()
        self.assertEqual(result["budget_rub"], 150000)
        self.assertEqual(result["planStatus"], "ready")
        self.assertEqual(len(result["updatedOptions"]), 2)
        self.assertIn("справа", result["reply"])
        for option in result["updatedOptions"].values():
            self.assertIn(option["title"], result["reply"])
            price = option["fairPriceBreakdown"]
            self.assertLessEqual(price["grand_total_rub"] + price["refundable_deposit_rub"], 150000)
        restored = self.client.get("/api/trips/initial", params={"session_id": "altay-legacy-cards"}).json()
        self.assertEqual(restored["options"], result["updatedOptions"])
        self.assertEqual(restored["planMessage"], "")
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion") as completion:
            again = run_openrouter_turn("altay-legacy-cards", "Покажи варианты справа", "A")
        completion.assert_not_called()
        self.assertEqual(again["updatedOptions"], result["updatedOptions"])

    def test_text_without_action_cannot_claim_nonexistent_cards(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", return_value={"role": "assistant", "content":
                "Отлично, оба варианта уже справа — Вариант A (178 600 ₽) и Вариант B (58 200 ₽)."}):
            result = run_openrouter_turn("invented-cards", "Ну что там?", "A")
        self.assertEqual(result["updatedOptions"], {})
        self.assertNotIn("178 600", result["reply"])
        self.assertNotIn("уже справа", result["reply"])
        self.assertIn("направление", result["reply"])

    def test_reload_retains_affordable_b_when_legacy_a_exceeds_user_limit(self):
        built, state = build_trip_response("", {}, intent={"destination": "Алтай", "budget_rub": 300000, "nights": 4})
        self.assertGreater(built["updatedOptions"]["A"]["fairPriceBreakdown"]["grand_total_rub"], 150000)
        session = db.load_session("altay-partial-budget")
        session.update(state=state, options=built["updatedOptions"], messages=[
            {"role": "user", "content": "Максимум 150 000 ₽"}])
        db.save_session(session)
        result = self.client.get("/api/trips/initial", params={"session_id": "altay-partial-budget"}).json()
        self.assertEqual(list(result["options"]), ["B"])
        self.assertEqual(result["selectedOption"], "B")
        self.assertEqual(result["planStatus"], "ready")
        self.assertEqual(result["budget_rub"], 150000)
        self.assertEqual(result["planMessage"], "")

    def test_card_request_with_new_conditions_still_uses_model(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", return_value=tool_message("build_trip_plan", {
                "destination": "Алтай", "nights": 4})) as completion:
            result = run_openrouter_turn("new-card-conditions", "Покажи варианты в Алтай до 150 тысяч", "A")
        completion.assert_called_once()
        self.assertEqual(result["budget_rub"], 150000)
        self.assertEqual(result["planStatus"], "ready")

    def test_duplicate_read_tools_are_cached_and_exhaustion_asks_for_clarification(self):
        from src.tools.tool_definitions import execute_tool_call
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", side_effect=[
                tool_message("search_destinations", {"query": "море"}, str(i)) for i in range(6)
            ]), patch("src.services.openrouter_agent.execute_tool_call", wraps=execute_tool_call) as execute:
            result = run_openrouter_turn("repeated-tools", "Да, собери", "A")
        self.assertEqual(execute.call_count, 1)
        self.assertIn("направление", result["reply"])
        self.assertEqual(len(db.load_session("repeated-tools")["messages"]), 2)

    def test_provider_failure_before_any_action_is_not_saved(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", side_effect=AgentUnavailable("timeout")):
            response = self.client.post("/api/chat", json={"session_id": "provider-error", "message": "Собери Сочи"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(db.load_session("provider-error")["state"], {})

    def test_reload_hides_legacy_options_above_saved_budget(self):
        self.client.get("/api/trips/initial", params={"session_id": "old-budget"})
        session = db.load_session("old-budget")
        built, _ = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 100000})
        session["options"] = built["updatedOptions"]
        session["state"]["budget_rub"] = 1000
        db.save_session(session)
        response = self.client.get("/api/trips/initial", params={"session_id": "old-budget"}).json()
        self.assertEqual(response["options"], {})
        self.assertEqual(response["planStatus"], "unavailable")

    def test_new_session_has_no_trip_and_legacy_demo_is_removed(self):
        initial = self.client.get("/api/trips/initial", params={"session_id": "new-empty-chat"}).json()
        self.assertEqual(initial["options"], {})
        self.assertEqual(initial["messages"], [])
        self.assertEqual(initial["planStatus"], "empty")
        session = db.load_session("old-example-chat")
        built, _ = build_trip_response("", {}, intent={"destination": "Сочи"})
        session["options"] = built["updatedOptions"]
        db.save_session(session)
        restored = self.client.get("/api/trips/initial", params={"session_id": "old-example-chat"}).json()
        self.assertEqual(restored["options"], {})

    def test_empty_demo_chat_does_not_invent_sochi(self):
        result = self.client.post("/api/chat", json={"session_id": "empty-demo-chat", "message": "Привет"}).json()
        self.assertEqual(result["updatedOptions"], {})
        self.assertNotIn("destination", result["chatState"])

    def test_contextual_actions_use_no_model_and_preserve_history(self):
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 300000})
        session = db.load_session("context-actions")
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("src.services.openrouter_agent._completion") as model:
            compared = run_openrouter_turn("context-actions", "Сравни варианты", "A", action_id="compare")
            selected = run_openrouter_turn("context-actions", "Выбери Б", "A", action_id="select_b")
            meals = run_openrouter_turn("context-actions", "Добавь завтраки и ужины", "B", action_id="meal_on")
            checkout = run_openrouter_turn("context-actions", "Открой оформление", "B", action_id="checkout")
        model.assert_not_called()
        self.assertEqual(compared["viewMode"], "compare")
        self.assertEqual(selected["selectedOption"], "B")
        self.assertTrue(meals["chatState"]["has_meal_addon"])
        self.assertEqual(checkout["viewMode"], "checkout")
        self.assertEqual(len(db.load_session("context-actions")["messages"]), 8)

    def test_unavailable_b_is_not_selected_or_compared(self):
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 55460, "nights": 4})
        self.assertFalse(built["updatedOptions"]["B"]["available"])
        session = db.load_session("one-affordable-option")
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("src.services.openrouter_agent._completion") as model:
            selected = run_openrouter_turn("one-affordable-option", "Выбрать вариант Б", "A")
            compared = run_openrouter_turn("one-affordable-option", "Сравни варианты", "A")
        model.assert_not_called()
        self.assertEqual(selected["selectedOption"], "A")
        self.assertEqual(compared["viewMode"], "canvas")

    def test_comparison_with_new_conditions_goes_to_model(self):
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 300000})
        session = db.load_session("complex-comparison")
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", return_value=tool_message("build_trip_plan", {"destination": "Дубай", "nights": 7})) as model:
            result = run_openrouter_turn("complex-comparison", "Сравни варианты в Дубае на 7 ночей", "A")
        model.assert_called_once()
        self.assertEqual(db.load_session("complex-comparison")["state"]["nights"], 7)
        self.assertTrue(all("Дубай" in o["title"] for o in result["updatedOptions"].values()))

    def test_shortlist_filters_and_order_are_executed_in_sql(self):
        from sqlalchemy import event
        queries = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            queries.append(statement)
        event.listen(db.get_engine(), "before_cursor_execute", capture)
        try:
            with patch.object(HotelService, "_load_data", side_effect=AssertionError("full catalog load")):
                result = HotelService.search(destination="Сочи", min_rating=8, max_price_per_night=10000, no_deposit=True)
        finally:
            event.remove(db.get_engine(), "before_cursor_execute", capture)
        self.assertTrue(result["hotels"])
        self.assertTrue(any("WHERE" in q and "ORDER BY" in q and "LIMIT" in q for q in queries))
        self.assertTrue(all(h["price_per_night"] <= 10000 and not h["deposit"]["required"] for h in result["hotels"]))

    def test_destination_aliases_cannot_match_inside_unrelated_words(self):
        from src.services.flight_service import FlightService
        self.assertEqual(HotelService.search("Sorrento")["hotels"], [])
        self.assertIsNone(FlightService._find_route("Sorrento"))
        self.assertTrue(all(h["destination_id"] == "phuket" for h in HotelService.search("Phuket resort")["hotels"]))
        self.assertEqual(FlightService._find_route("Phuket resort")["city"], "Пхукет")

    def test_tool_results_sent_to_model_are_compact_but_keep_constraints(self):
        from src.services.chat_context import compact_tool_result, public_chat_state
        from src.services.destination_service import DestinationService
        result = DestinationService.search(query="море", limit=5)
        compact = compact_tool_result("search_destinations", result)
        self.assertLess(len(json.dumps(compact)), len(json.dumps(result)) / 2)
        self.assertLessEqual(len(compact["destinations"]), 3)
        self.assertNotIn("climate_by_month", compact["destinations"][0])
        self.assertIn("visa_requirements", compact["destinations"][0])
        result = HotelService.search("Сочи")
        compact = compact_tool_result("search_hotels", result)
        self.assertNotIn("photos", compact["hotels"][0])
        self.assertIn("deposit", compact["hotels"][0])
        self.assertIn("checkin_time", compact["hotels"][0])
        state = public_chat_state({"state": {"no_deposit": True, "pet_friendly": True, "min_rating": 9, "internal_flag": "ignore"}})
        self.assertEqual(state, {"no_deposit": True, "pet_friendly": True, "min_rating": 9})

    def test_model_cannot_invent_zero_distances_or_unrequested_meal_filter(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", return_value=tool_message("build_trip_plan", {
                "destination": "Сочи", "min_rating": 0, "meal_type": "RO", "max_distance_to_beach_m": 0,
                "max_distance_to_center_km": 0, "nights": 4})):
            result = run_openrouter_turn("unrequested-filters", "Собери Сочи на 4 ночи до 100 тысяч", "A")
        self.assertEqual(result["planStatus"], "ready")
        self.assertNotIn("meal_type", result["chatState"])
        self.assertNotIn("max_distance_to_beach_m", result["chatState"])

    def test_alternatives_exclude_current_and_preserve_budget_without_model_or_weather(self):
        failed, state = build_trip_response("", {}, intent={"destination": "Мальдивы", "budget_rub": 150000, "nights": 4, "checkin_date": "2027-11-15"})
        self.assertFalse(failed["trip_assembled"])
        session = db.load_session("maldives-alternatives")
        session.update(state=state, options={})
        db.save_session(session)
        with patch("src.services.openrouter_agent._completion") as model, patch("src.services.weather_service.WeatherService.get_forecast") as weather:
            first = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Предложи другие направления с сохранением моего бюджета", "action_id": "alternatives"}).json()
            second = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Предложи другие направления с сохранением моего бюджета"}).json()
        model.assert_not_called()
        weather.assert_not_called()
        quotes = first["chatState"]["alternative_quotes"]
        self.assertTrue(quotes)
        self.assertEqual(quotes, second["chatState"]["alternative_quotes"])
        self.assertEqual(first["budget_rub"], 150000)
        self.assertTrue(all(q["name"] != "Мальдивы" and q["minimum_total_rub"] <= 150000 for q in quotes))
        self.assertEqual(first["planStatus"], "alternatives")
        self.assertNotIn("304 600", first["reply"])
        choice = quotes[0]
        selected = self.client.post("/api/chat", json={"session_id": session["id"], "message": f"Выбираю {choice['name']}", "action_id": "choose_destination", "destination": choice["id"]}).json()
        self.assertEqual(selected["planStatus"], "ready")
        self.assertFalse(selected["chatState"]["choosing_alternative"])
        self.assertTrue(all(choice["name"] in o["title"] for o in selected["updatedOptions"].values()))
        self.assertEqual(selected["models_used"], [])

    def test_alternatives_do_not_raise_an_impossible_budget(self):
        session = db.load_session("tiny-budget-alternatives")
        session["state"] = {"destination": "Мальдивы", "budget_rub": 1000, "nights": 4}
        db.save_session(session)
        result = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Другие направления", "action_id": "alternatives"}).json()
        self.assertEqual(result["budget_rub"], 1000)
        self.assertEqual(result["chatState"]["alternative_quotes"], [])
        self.assertEqual(result["updatedOptions"], {})

    def test_budget_form_sets_range_before_destination_and_global_cheapest_respects_it(self):
        from src.services.trip_planner import required_option_funds
        session_id = "budget-global-cheapest"
        with patch("src.services.openrouter_agent._completion") as model:
            response = self.client.post("/api/chat", json={"session_id": session_id, "message": "Бюджет от 80000 до 150000 ₽",
                "action_id": "set_budget", "budget_min_rub": 80000, "budget_rub": 150000})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["updatedOptions"], {})
            response = self.client.post("/api/chat", json={"session_id": session_id, "message": "Найди самую дешёвую поездку", "action_id": "cheapest"})
            self.assertEqual(response.status_code, 200, response.text)
        model.assert_not_called()
        result = response.json()
        self.assertEqual(result["planStatus"], "ready")
        self.assertEqual(result["chatState"]["budget_min_rub"], 80000)
        self.assertEqual(result["budget_rub"], 150000)
        self.assertEqual(result["selectedOption"], "A")
        minima = []
        for destination in db.load_catalog("destinations"):
            preview, _ = build_trip_response("", result["chatState"], intent={"destination": destination["name"], "hotel_ids": []}, preview=True)
            if preview.get("trip_assembled"):
                minima.append(preview["minimum_price_rub"])
        self.assertEqual(required_option_funds(result["updatedOptions"]["A"]), min(minima))
        for option in result["updatedOptions"].values():
            if option.get("available", True):
                self.assertTrue(80000 <= required_option_funds(option) <= 150000)

    def test_typed_minimum_does_not_lower_upper_limit_and_cheapest_keeps_city_and_conditions(self):
        from src.services.trip_planner import required_option_funds
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 150000, "nights": 5,
            "passengers": 3, "pet_friendly": True, "has_meal_addon": True, "checkin_date": "2027-05-03"})
        session = db.load_session("range-keeps-conditions")
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        result = self.client.post("/api/chat", json={"session_id": session["id"], "message": "минимум 80 тыс."}).json()
        self.assertEqual(result["budget_rub"], 150000)
        self.assertEqual(result["chatState"]["budget_min_rub"], 80000)
        result = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Самая дешёвая поездка"}).json()
        for key in ("destination", "nights", "passengers", "pet_friendly", "has_meal_addon", "checkin_date", "checkout_date"):
            self.assertEqual(result["chatState"][key], state[key])
        self.assertTrue(80000 <= required_option_funds(result["updatedOptions"]["A"]) <= 150000)
        restored = self.client.get("/api/trips/initial", params={"session_id": session["id"]}).json()
        self.assertEqual(restored["chatState"]["budget_min_rub"], 80000)
        self.assertEqual(restored["options"], result["updatedOptions"])

    def test_invalid_budget_interval_returns_422_without_changing_saved_state(self):
        session_id = "invalid-budget-range"
        session = db.load_session(session_id)
        response = self.client.post("/api/chat", json={"session_id": session_id, "message": "Измени бюджет",
            "action_id": "set_budget", "budget_min_rub": 150000, "budget_rub": 80000})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(db.load_session(session_id), session)

    def test_budget_bounds_can_be_cleared_and_stay_cleared_on_reload(self):
        session_id = "clear-budget-range"
        for floor, cap in [(80000, 150000), (0, 0)]:
            response = self.client.post("/api/chat", json={"session_id": session_id, "message": "Измени бюджет",
                "action_id": "set_budget", "budget_min_rub": floor, "budget_rub": cap})
            self.assertEqual(response.status_code, 200, response.text)
        result = self.client.get("/api/trips/initial", params={"session_id": session_id}).json()
        self.assertIsNone(result["budget_rub"])
        self.assertEqual(result["chatState"]["budget_min_rub"], 0)

    def test_cheapest_does_not_change_impossible_limits_or_fabricate_price(self):
        session = db.load_session("cheapest-impossible")
        session["state"] = {"budget_rub": 1000, "budget_min_rub": 500}
        db.save_session(session)
        result = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Самая дешёвая поездка"}).json()
        self.assertEqual(result["planStatus"], "unavailable")
        self.assertEqual(result["updatedOptions"], {})
        self.assertEqual(result["budget_rub"], 1000)
        self.assertEqual(result["chatState"]["budget_min_rub"], 500)

    def test_model_cannot_remove_user_lower_boundary(self):
        from src.services.trip_planner import required_option_funds
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("src.services.openrouter_agent._completion",
            return_value=tool_message("build_trip_plan", {"destination": "Сочи", "budget_min_rub": 0, "budget_rub": 999999})):
            result = run_openrouter_turn("model-must-keep-range", "Собери Сочи, бюджет от 80 до 150 тыс.", "A")
        self.assertEqual(result["budget_rub"], 150000)
        self.assertEqual(result["chatState"]["budget_min_rub"], 80000)
        self.assertTrue(all(80000 <= required_option_funds(o) <= 150000 for o in result["updatedOptions"].values() if o.get("available", True)))

    def test_date_move_preserves_every_price_and_updates_weather_and_history(self):
        from copy import deepcopy
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 150000, "nights": 4, "checkin_date": "2026-11-15"})
        session = db.load_session("fixed-price-date-move")
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        original = deepcopy(session["options"])
        with patch("src.services.openrouter_agent._completion") as model, patch.object(FairPriceCalculator, "calculate_fair_price", side_effect=AssertionError("price recalculation")):
            response = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Перенеси даты", "action_id": "change_dates", "checkin_date": "2027-05-03", "checkout_date": "2027-05-07"})
        self.assertEqual(response.status_code, 200, response.text)
        model.assert_not_called()
        result = response.json()
        for key, before in original.items():
            after = result["updatedOptions"][key]
            for field in ("hotel", "extras", "fairPriceBreakdown", "timingValidation"):
                self.assertEqual(after[field], before[field])
            before_transport = {k: v for k, v in before["transport"].items() if k not in ("returnFlight", "departureDate", "arrivalDate", "scheduleConditional")}
            after_transport = {k: v for k, v in after["transport"].items() if k not in ("returnFlight", "departureDate", "arrivalDate", "scheduleConditional")}
            self.assertEqual(after_transport, before_transport)
            self.assertEqual(after["transport"]["returnFlight"]["date"], "2027-05-07")
            self.assertEqual(after["transport"]["returnFlight"]["departure_time"], before["transport"]["returnFlight"]["departure_time"])
            self.assertIn("03.05.2027 — 07.05.2027", after["dates"])
            self.assertIn("03.05.2027", after["timeline"][0]["time"])
            self.assertIn("07.05.2027", after["timeline"][-1]["time"])
            self.assertNotEqual(after["weather"]["temp"], before["weather"]["temp"])
            self.assertEqual(after["weather"]["source"], "Offline Climate Fallback")
        restored = self.client.get("/api/trips/initial", params={"session_id": session["id"]}).json()
        self.assertEqual(restored["options"], result["updatedOptions"])
        self.assertEqual(restored["chatState"]["checkin_date"], "2027-05-03")

    def test_mountain_inspiration_replaces_old_dubai_and_filters_subsequent_alternatives(self):
        from src.services.travel_preferences import matches_destination
        session = db.load_session("screenshot-mountains-dubai")
        session["state"] = {"destination": "Дубай", "nights": 4, "passengers": 2, "origin": "Москва",
            "checkin_date": "2026-11-15", "checkout_date": "2026-11-19", "budget_min_rub": 75000, "budget_rub": 125000}
        db.save_session(session)
        text = "Помоги выбрать направление для отдыха в горах. Сначала предложи направления и уточни условия."
        with patch("src.services.openrouter_agent._completion") as model, patch("src.services.weather_service.WeatherService.get_forecast") as weather:
            response = self.client.post("/api/chat", json={"session_id": session["id"], "message": text})
        self.assertEqual(response.status_code, 200, response.text)
        model.assert_not_called()
        weather.assert_not_called()
        result = response.json()
        self.assertEqual(result["updatedOptions"], {})
        self.assertNotIn("destination", result["chatState"])
        self.assertEqual(result["chatState"]["travel_styles"], ["mountains"])
        self.assertEqual(result["budget_rub"], 125000)
        self.assertEqual(result["chatState"]["budget_min_rub"], 75000)
        quotes = result["chatState"]["alternative_quotes"]
        self.assertTrue(quotes)
        destinations = {d["id"]: d for d in db.load_catalog("destinations")}
        self.assertTrue(all(matches_destination(destinations[q["id"]], ["mountains"]) and 75000 <= q["minimum_total_rub"] <= 125000 for q in quotes))
        self.assertFalse(any(name in result["reply"] for name in ("Стамбул", "Пхукет", "Дубай")))
        choice = quotes[0]
        response = self.client.post("/api/chat", json={"session_id": session["id"], "message": f"Выбираю {choice['name']}", "action_id": "choose_destination", "destination": choice["id"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["planStatus"], "ready")
        alternatives = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Предложи другие направления с сохранением моего бюджета", "action_id": "alternatives"}).json()
        self.assertTrue(all(q["id"] != choice["id"] and matches_destination(destinations[q["id"]], ["mountains"])
                            for q in alternatives["chatState"]["alternative_quotes"]))
        restored = self.client.get("/api/trips/initial", params={"session_id": session["id"]}).json()
        self.assertEqual(restored["chatState"]["travel_styles"], ["mountains"])

    def test_sea_button_replaces_mountains_without_model_and_retains_budget(self):
        session = db.load_session("style-switch-sea")
        session["state"] = {"destination": "Шерегеш", "travel_styles": ["mountains"], "budget_rub": 150000}
        db.save_session(session)
        result = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Хочу к морю", "action_id": "inspire_sea"}).json()
        self.assertEqual(result["chatState"]["travel_styles"], ["sea"])
        self.assertNotIn("destination", result["chatState"])
        self.assertEqual(result["updatedOptions"], {})
        self.assertEqual(result["budget_rub"], 150000)
        self.assertEqual(result["models_used"], [])
        self.assertTrue(result["chatState"]["alternative_quotes"])
        self.assertTrue(all(q["id"] not in ("sheregesh", "altay", "istanbul") for q in result["chatState"]["alternative_quotes"]))

    def test_no_matching_style_in_budget_does_not_suggest_unrelated_destination(self):
        session = db.load_session("style-impossible-budget")
        session["state"] = {"budget_min_rub": 0, "budget_rub": 1000}
        db.save_session(session)
        result = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Хочу в горы", "action_id": "inspire_mountains"}).json()
        self.assertEqual(result["planStatus"], "unavailable")
        self.assertEqual(result["chatState"]["alternative_quotes"], [])
        self.assertEqual(result["budget_rub"], 1000)
        self.assertIn("горы", result["reply"])
        self.assertEqual(result["updatedOptions"], {})

    def test_model_cannot_build_dubai_for_saved_mountain_preference(self):
        session = db.load_session("model-mountain-guard")
        session["state"] = {"travel_styles": ["mountains"], "budget_rub": 500000}
        db.save_session(session)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("src.services.openrouter_agent._completion",
            return_value=tool_message("build_trip_plan", {"destination": "Дубай"})):
            result = run_openrouter_turn(session["id"], "Собери поездку", "A")
        self.assertEqual(result["planStatus"], "unavailable")
        self.assertEqual(result["updatedOptions"], {})
        self.assertIn("не соответствует", result["reply"])

    def test_legacy_mountain_history_filters_bad_options_and_cheapest_matches_style(self):
        from src.services.travel_preferences import matches_destination, matches_hotel
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 500000})
        session = db.load_session("legacy-mountain-history")
        session.update(state=state, options=built["updatedOptions"])
        session["messages"] = [{"role": "user", "content": "Хочу в горы"}, {"role": "assistant", "content": "Предлагаю Пхукет"}]
        db.save_session(session)
        initial = self.client.get("/api/trips/initial", params={"session_id": session["id"]}).json()
        self.assertEqual(initial["chatState"]["travel_styles"], ["mountains"])
        hotels = {h["id"]: h for h in db.load_catalog("hotels")}
        self.assertTrue(all(matches_hotel(hotels[o["hotel"]["id"]], ["mountains"]) for o in initial["options"].values()))
        session = db.load_session(session["id"])
        session["state"].pop("destination", None)
        db.save_session(session)
        result = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Самая дешёвая поездка", "action_id": "cheapest"}).json()
        destination = next(d for d in db.load_catalog("destinations") if d["name"] == result["chatState"]["destination"])
        self.assertTrue(matches_destination(destination, ["mountains"]))
        self.assertTrue(matches_hotel(hotels[result["updatedOptions"]["A"]["hotel"]["id"]], ["mountains"]))

    def test_invalid_date_range_does_not_modify_saved_trip(self):
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "nights": 4})
        session = db.load_session("invalid-date-range")
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        response = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Перенеси даты", "action_id": "change_dates", "checkin_date": "2027-05-03", "checkout_date": "2027-05-06"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(db.load_session(session["id"])["options"], session["options"])

    def test_date_only_model_action_also_keeps_fixed_prices(self):
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "nights": 4})
        session = db.load_session("model-date-move")
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("src.services.openrouter_agent._completion", return_value=tool_message("build_trip_plan", {"checkin_date": "2027-05-03", "checkout_date": "2027-05-07"})):
            result = run_openrouter_turn(session["id"], "Перенеси поездку на 3 мая", "A")
        self.assertEqual(result["updatedOptions"]["A"]["fairPriceBreakdown"], built["updatedOptions"]["A"]["fairPriceBreakdown"])
        self.assertIn("03.05.2027", result["updatedOptions"]["A"]["dates"])

    def test_unverified_free_text_trip_prices_are_not_published(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("src.services.openrouter_agent._completion", return_value={"role": "assistant", "content": "Пхукет стоит 460 000 ₽. luxury-tier"}):
            result = run_openrouter_turn("unverified-text-prices", "Расскажи подробнее", "A")
        self.assertNotIn("460 000", result["reply"])

    def test_corrupt_assistant_history_is_repaired_without_changing_user_messages(self):
        session = db.load_session("corrupt-history")
        original_user = "Что значит 有效 в ответе?"
        session["messages"] = [{"role": "user", "content": original_user},
                               {"role": "assistant", "content": "cdnjs Пхукет ани有效"}]
        db.save_session(session)
        response = self.client.get("/api/trips/initial", params={"session_id": session["id"]}).json()
        self.assertEqual(response["messages"][0]["content"], original_user)
        self.assertNotIn("cdnjs", response["messages"][1]["content"])
        self.assertEqual(db.load_session(session["id"])["messages"], response["messages"])

    def test_free_fallbacks_are_sent_in_priority_order(self):
        response = httpx.Response(200, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
            json={"model": "google/gemma-4-26b-a4b-it:free", "choices": [{"message": {"role": "assistant", "content": "ok"}}]})
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key",
            "OPENROUTER_MODEL": "google/gemma-4-31b-it:free",
            "OPENROUTER_FALLBACK_MODELS": "google/gemma-4-26b-a4b-it:free,openrouter/free"}), patch("httpx.post", return_value=response) as post:
            result = _completion([], 3)
            self.assertEqual(post.call_args.kwargs["json"]["models"], [
                "google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free", "openrouter/free"])
            self.assertNotIn("model", post.call_args.kwargs["json"])
            self.assertEqual(result["_model"], "google/gemma-4-26b-a4b-it:free")

    def test_free_primary_cannot_fall_back_to_paid_model(self):
        with patch.dict(os.environ, {"OPENROUTER_MODEL": "google/gemma-4-31b-it:free",
                                    "OPENROUTER_FALLBACK_MODELS": "openai/gpt-4.1-mini"}), patch("httpx.post") as post:
            with self.assertRaises(AgentUnavailable):
                _completion([], 3)
            post.assert_not_called()

    def test_no_pet_fee_when_travelling_without_pet(self):
        price = FairPriceCalculator.calculate_fair_price(
            {"pet_friendly": {"allowed": True, "fee_per_stay": 5000}}, {}, {}, with_pet=False,
        )
        self.assertEqual(price["pet_fee_rub"], 0)

    def test_polite_plan_commands_require_build_tool(self):
        for index, message in enumerate(("Соберите поездку в Сочи", "Подберите поездку в Сочи", "Найдите поездку в Сочи")):
            with self.subTest(message=message), patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
                "src.services.openrouter_agent._completion", return_value=tool_message("build_trip_plan", {"destination": "Сочи"})) as model:
                result = run_openrouter_turn(f"polite-plan-{index}", message, "A")
                self.assertEqual(model.call_args.kwargs["tool_choice"]["function"]["name"], "build_trip_plan")
                self.assertEqual(result["planStatus"], "ready")

    def test_hotel_discussion_keeps_cards_and_budget_and_exposes_catalog_facts(self):
        from copy import deepcopy
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 150000, "passengers": 3})
        session = db.load_session("hotel-discussion")
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        before = deepcopy(session["options"])
        nightly = before["A"]["hotel"]["pricePerNight"]
        reply = f"В карточке справа выбран отель. Ночь стоит {nightly} ₽. Давайте обсудим питание и условия отмены."
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("src.services.openrouter_agent._completion",
            return_value={"role": "assistant", "content": reply}) as model:
            result = run_openrouter_turn(session["id"], f"Расскажи об отеле и его цене {nightly} ₽", "A")
        self.assertEqual(result["reply"], reply)
        self.assertEqual(result["updatedOptions"], before)
        self.assertEqual(result["budget_rub"], 150000)
        self.assertEqual(model.call_args.kwargs["tool_choice"], "auto")
        context = model.call_args.args[0][0]["content"]
        self.assertIn("cancellation_policy", context)
        self.assertIn("amenities", context)

    def test_discussion_prices_are_not_restored_as_user_budget(self):
        session = db.load_session("discussion-no-budget")
        session["messages"] = [{"role": "user", "content": "Почему море стоит 100 000 ₽?"},
                               {"role": "assistant", "content": "Давайте обсудим условия поездки."}]
        db.save_session(session)
        restored = self.client.get("/api/trips/initial", params={"session_id": session["id"]}).json()
        self.assertIsNone(restored["budget_rub"])
        self.assertNotIn("travel_styles", restored["chatState"])

    def test_question_tool_calls_cannot_modify_plan(self):
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 150000})
        session = db.load_session("read-only-discussion")
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        answers = [tool_message("build_trip_plan", {"destination": "Дубай"}),
                   tool_message("search_hotels", {"destination": "Сочи"}, "call-search"),
                   {"role": "assistant", "content": "Можно обсудить удобства и условия проживания. План сохранён."}]
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("src.services.openrouter_agent._completion", side_effect=answers):
            result = run_openrouter_turn(session["id"], "Какие удобства есть у отеля?", "A")
        self.assertEqual(result["updatedOptions"], built["updatedOptions"])
        self.assertEqual(result["chatState"]["destination"], "Сочи")
        self.assertNotIn("build_trip_plan", result["tools_called"])

    def test_unguarded_price_in_hotel_discussion_is_not_published(self):
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 150000})
        session = db.load_session("hotel-unverified-price")
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("src.services.openrouter_agent._completion",
            return_value={"role": "assistant", "content": "Скидка отеля — 9876543 ₽."}):
            result = run_openrouter_turn(session["id"], "Расскажи о скидках", "A")
        self.assertNotIn("9876543", result["reply"])
        self.assertEqual(result["updatedOptions"], built["updatedOptions"])

    def test_clarifying_suggestions_respect_small_budget(self):
        from src.services.openrouter_agent import _clarifying_reply
        session = db.load_session("clarify-small-budget")
        session["state"] = {"travel_styles": ["sea"], "budget_rub": 1000}
        reply = _clarifying_reply(session)
        self.assertNotIn("Мальдивы", reply)
        self.assertEqual(session["state"]["alternative_quotes"], [])

    def test_later_saturday_flight_and_monday_evening_return_update_actual_cards(self):
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "passengers": 1,
            "checkin_date": "2026-10-31", "nights": 1, "budget_rub": 150000})
        session = db.load_session("weekend-flight-edit")
        state.update(choosing_alternative=True, alternative_quotes=[{"id": "phuket", "name": "Пхукет", "minimum_total_rub": 100000}], suggested_destinations=["Пхукет"])
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        hotels = {k: o["hotel"]["id"] for k, o in session["options"].items()}
        with patch("src.services.openrouter_agent._completion") as model:
            response = self.client.post("/api/chat", json={"session_id": session["id"],
                "message": "А есть вариант не такого раннего полёта в сб? И можем вернуться вечером в понедельник"})
        self.assertEqual(response.status_code, 200, response.text)
        model.assert_not_called()
        result = response.json()
        self.assertEqual(result["chatState"]["nights"], 2)
        self.assertEqual(result["chatState"]["passengers"], 1)
        self.assertEqual(result["budget_rub"], 150000)
        self.assertEqual(result["chatState"]["checkout_date"], "2026-11-02")
        self.assertFalse(result["chatState"]["choosing_alternative"])
        self.assertNotIn("alternative_quotes", result["chatState"])
        self.assertEqual({k: o["hotel"]["id"] for k, o in result["updatedOptions"].items()}, hotels)
        for option in result["updatedOptions"].values():
            self.assertGreaterEqual(option["transport"]["depTime"], "09:00")
            returning = option["transport"]["returnFlight"]
            self.assertEqual(returning["arrival_date"], "2026-11-02")
            self.assertGreaterEqual(returning["arrival_time"], "18:00")
            self.assertIn(option["transport"]["depTime"], option["timeline"][0]["time"])
            self.assertIn(returning["departure_time"], option["timeline"][-1]["time"])
        reloaded = self.client.get("/api/trips/initial", params={"session_id": session["id"]}).json()
        self.assertEqual(reloaded["options"], result["updatedOptions"])

    def test_unavailable_flight_time_reports_no_tickets_and_preserves_plan(self):
        from copy import deepcopy
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 150000})
        session = db.load_session("no-late-flight")
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        before = deepcopy(session)
        with patch("src.services.openrouter_agent._completion") as model:
            result = run_openrouter_turn(session["id"], "А можно вылететь после 20:00?", "A")
        model.assert_not_called()
        self.assertIn("Нет подходящих билетов", result["reply"])
        self.assertEqual(result["updatedOptions"], before["options"])
        self.assertEqual(db.load_session(session["id"])["state"], before["state"])

    def test_flight_timing_limits_survive_guest_edits_and_budget_is_not_raised(self):
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 150000,
            "departure_after": "11:00", "return_arrival_after": "18:00", "return_arrival_before": "23:59"})
        session = db.load_session("saved-flight-times")
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        result = run_openrouter_turn(session["id"], "Измени гостей", "A", "change_guests", {"passengers": 3})
        for option in result["updatedOptions"].values():
            self.assertGreaterEqual(option["transport"]["depTime"], "11:00")
            self.assertGreaterEqual(option["transport"]["returnFlight"]["arrival_time"], "18:00")
            price = option["fairPriceBreakdown"]
            self.assertLessEqual(price["grand_total_rub"] + price["refundable_deposit_rub"], 150000)

    def test_overnight_return_is_not_presented_as_arriving_on_previous_evening(self):
        from src.services.flight_service import FlightService
        result = FlightService.search(destination="Бали", date="2026-10-31", return_date="2026-11-02",
            return_arrival_after="00:00", return_arrival_before="05:59")
        self.assertEqual(result["flights"], [])

    def test_invalid_flight_time_is_rejected_by_api_schema(self):
        response = self.client.post("/api/tools/transfers-flights", json={"destination": "Сочи", "date": "2026-10-31", "departure_after": "25:00"})
        self.assertEqual(response.status_code, 422)

    def test_text_only_destination_suggestions_become_persistent_shortcuts(self):
        reply = ("Для Юго-Восточной Азии предлагаю:\n\n"
                 "1. **Пхукет, Таиланд**: пляжи и дайвинг.\n\n"
                 "2. **Бали, Индонезия**: вулканы и рисовые террасы.\n\n"
                 "Какое направление вам больше по душе?")
        session = db.load_session("asia-shortcuts")
        session["state"] = {"budget_rub": 500000, "passengers": 3, "nights": 5}
        db.save_session(session)
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch(
            "src.services.openrouter_agent._completion", return_value={"role": "assistant", "content": reply}
        ) as model:
            result = run_openrouter_turn(session["id"], "Хочу куда-нибудь в Юго-Восточную Азию", "A")
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result["chatState"]["suggested_destinations"], ["Пхукет", "Бали"])
        self.assertEqual(result["updatedOptions"], {})
        restored = self.client.get("/api/trips/initial", params={"session_id": session["id"]}).json()
        self.assertEqual(restored["chatState"]["suggested_destinations"], ["Пхукет", "Бали"])
        with patch("src.services.openrouter_agent._completion") as model:
            selected = self.client.post("/api/chat", json={"session_id": session["id"],
                "message": "Выбираю Бали. Собери поездку в пределах моего бюджета.",
                "action_id": "choose_destination", "destination": "Бали"}).json()
        model.assert_not_called()
        self.assertEqual(selected["chatState"]["destination"], "Бали")
        self.assertEqual(selected["chatState"]["passengers"], 3)
        self.assertEqual(selected["chatState"]["nights"], 5)
        self.assertEqual(selected["budget_rub"], 500000)
        self.assertTrue(selected["updatedOptions"])

    def test_old_text_suggestions_restore_on_reload_without_a_model_request(self):
        session = db.load_session("restore-asia-shortcuts")
        session["messages"] = [{"role": "user", "content": "Хочу в Азию"},
                               {"role": "assistant", "content": "Можно рассмотреть Бали или Пхукет. Что выберете?"}]
        db.save_session(session)
        with patch("src.services.openrouter_agent._completion") as model:
            restored = self.client.get("/api/trips/initial", params={"session_id": session["id"]}).json()
        model.assert_not_called()
        self.assertEqual(restored["chatState"]["suggested_destinations"], ["Бали", "Пхукет"])

    def test_suggestion_shortcuts_exclude_rejected_unknown_and_incidental_places(self):
        from src.services.chat_context import sync_destination_suggestions
        session = db.load_session("safe-suggestion-shortcuts")
        reply = ("1. **Бали** — не подходит под ваши условия.\n"
                 "2. **Бангкок** — интересный город.\n"
                 "3. **Пхукет** — пляжи и дайвинг.\n"
                 "Отсюда иногда путешествуют через Дубай.")
        self.assertTrue(sync_destination_suggestions(session, reply))
        self.assertEqual(session["state"]["suggested_destinations"], ["Пхукет"])
        self.assertTrue(sync_destination_suggestions(session, "**Пхукет** — не подходит под условия."))
        self.assertEqual(session["state"]["suggested_destinations"], [])
        session["state"] = {"destination": "Сочи"}
        self.assertFalse(sync_destination_suggestions(session, "Предлагаю Бали и Пхукет."))
        self.assertNotIn("suggested_destinations", session["state"])

    def test_guest_action_reprices_trip_without_model_and_booking_uses_actual_guests(self):
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 500000, "passengers": 1, "pet_friendly": False})
        session = db.load_session("edit-guests")
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        with patch("src.services.openrouter_agent._completion") as model:
            response = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Измени гостей", "action_id": "change_guests", "passengers": 3})
        self.assertEqual(response.status_code, 200, response.text)
        model.assert_not_called()
        result = response.json()
        self.assertEqual(result["chatState"]["passengers"], 3)
        self.assertEqual(result["budget_rub"], 500000)
        option = result["updatedOptions"]["A"]
        self.assertEqual(option["travellers"], {"passengers": 3, "withPet": False, "adults": 3, "children_ages": []})
        self.assertGreater(option["fairPriceBreakdown"]["flight_base_rub"], built["updatedOptions"]["A"]["fairPriceBreakdown"]["flight_base_rub"])
        booked = self.client.post("/api/bookings", json={"trip": option}).json()
        self.assertEqual(booked["voucher"]["travellers"], option["travellers"])
        total = booked["total_price"]
        self.assertEqual(booked["loyalty_points_earned"], max(150, (total * 15 + 500) // 1000))
        for invalid in (0, 11):
            self.assertEqual(self.client.post("/api/chat", json={"session_id": session["id"], "message": "Измени гостей", "action_id": "change_guests", "passengers": invalid}).status_code, 422)
        self.assertEqual(db.load_session(session["id"])["state"]["passengers"], 3)

    def test_dates_and_guests_can_be_saved_before_destination(self):
        session_id = "early-date-guests"
        first = self.client.post("/api/chat", json={"session_id": session_id, "message": "Измени гостей", "action_id": "change_guests", "passengers": 1})
        self.assertEqual(first.status_code, 200, first.text)
        moved = self.client.post("/api/chat", json={"session_id": session_id, "message": "Перенеси даты", "action_id": "change_dates", "checkin_date": "2027-05-03", "checkout_date": "2027-05-07"})
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(moved.json()["chatState"]["passengers"], 1)
        self.assertEqual(moved.json()["updatedOptions"], {})

    def test_pet_presence_is_separate_from_hotel_permission(self):
        for with_pet in (False, True):
            built, _ = build_trip_response("", {}, intent={"destination": "Шерегеш", "budget_rub": 500000, "pet_friendly": with_pet})
            option = built["updatedOptions"]["A"]
            self.assertTrue(option["hotel"]["petFriendly"])
            self.assertEqual(option["travellers"]["withPet"], with_pet)
            self.assertIn("Можно с питомцем", option["hotel"]["tags"])

    def test_invalid_requests_are_rejected(self):
        self.assertEqual(self.client.post("/api/chat", json={"message": "   "}).status_code, 422)
        self.assertEqual(self.client.post("/api/chat", json={"message": "test", "selected_option": "C"}).status_code, 422)
