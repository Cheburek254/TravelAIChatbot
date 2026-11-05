import copy
import os
import unittest
from unittest.mock import patch

from tests import test_chat_and_database as fixtures
from src.services import database as db
from src.services.agent_orchestrator import build_trip_response
from src.services.openrouter_agent import run_openrouter_turn, _grounded_prices, _build_plan
from src.services.travel_party import normalize_party


class TravelUpdatesTests(unittest.TestCase):
    def setUp(self):
        fixtures.ChatDatabaseTests.setUp(self)

    def tearDown(self):
        fixtures.ChatDatabaseTests.tearDown(self)

    def seed(self, sid="travel-update", pet=False):
        built, state = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 500000,
            "passengers": 2, "nights": 4, "checkin_date": "2026-11-15", "pet_friendly": pet})
        session = db.load_session(sid)
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        return session

    def action(self, session, action, **data):
        response = self.client.post("/api/chat", json={"session_id": session["id"],
            "message": "Измени условия поездки", "action_id": action, **data})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_api_pet_toggle_can_remove_pet_and_pet_fee(self):
        session = self.seed(pet=True)
        result = self.action(session, "change_guests", adults=2, children_ages=[], pet_friendly=False)
        self.assertFalse(result["chatState"]["pet_friendly"])
        for option in result["updatedOptions"].values():
            self.assertFalse(option["travellers"]["withPet"])
            self.assertEqual(option["fairPriceBreakdown"]["pet_fee_rub"], 0)

    def test_dates_form_uses_available_times_and_rejects_invented_time(self):
        session = self.seed()
        result = self.action(session, "edit_trip", checkin_date="2027-05-03", checkout_date="2027-05-07", departure_time="12:45")
        self.assertTrue(result["updatedOptions"])
        self.assertTrue(all(o["transport"]["depTime"] == "12:45" for o in result["updatedOptions"].values()))
        before = copy.deepcopy(db.load_session(session["id"]))
        failed = self.action(session, "change_dates", checkin_date="2027-05-03", checkout_date="2027-05-07", departure_time="15:00", arrival_time="19:00")
        self.assertTrue(failed["changeRejected"])
        self.assertIn("Нет подходящих билетов", failed["reply"])
        self.assertEqual(failed["updatedOptions"], before["options"])
        self.assertEqual(db.load_session(session["id"])["state"], before["state"])

    def test_duration_change_recalculates_instead_of_faking_fixed_price(self):
        session = self.seed()
        result = self.action(session, "edit_trip", checkin_date="2026-11-15", checkout_date="2026-11-21")
        self.assertEqual(result["chatState"]["nights"], 6)
        self.assertGreater(result["updatedOptions"]["A"]["fairPriceBreakdown"]["hotel_base_rub"], session["options"]["A"]["fairPriceBreakdown"]["hotel_base_rub"])

    def test_discussion_does_not_change_guests_dates_pet_or_budget(self):
        session = self.seed()
        before = copy.deepcopy(session)
        for question in ("Расскажи, как разместиться с собакой одному на 3 ночи?", "Почему доплата за собаку до 5000 рублей?"):
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("src.services.openrouter_agent._completion", return_value={"role": "assistant", "content": "Условия проживания зависят от правил выбранного отеля."}):
                result = run_openrouter_turn(session["id"], question, "A")
            self.assertEqual(result["updatedOptions"], before["options"])
            self.assertEqual(db.load_session(session["id"])["state"], before["state"])

    def test_no_magic_price_is_accepted_without_catalog_evidence(self):
        self.assertFalse(_grounded_prices("Этот отель стоит 57000 рублей.", {"state": {}, "options": {}}))

    def test_family_prices_rooms_baggage_and_adult_only_fees(self):
        session = self.seed()
        family = self.action(session, "change_guests", adults=2, children_ages=[1, 8], pet_friendly=False)
        self.assertEqual(family["chatState"]["passengers"], 4)
        option = family["updatedOptions"]["A"]
        price = option["fairPriceBreakdown"]
        self.assertEqual(option["hotel"]["rooms"], 2)
        self.assertEqual(price["resort_fee_rub"], 100 * 4 * 2)
        self.assertEqual(option["travellers"]["children_ages"], [1, 8])
        self.assertEqual(price["hotel_base_rub"], option["hotel"]["pricePerNight"] * 4)
        adults = self.action(session, "change_guests", adults=4, children_ages=[])
        self.assertGreater(adults["updatedOptions"]["A"]["fairPriceBreakdown"]["flight_base_rub"], price["flight_base_rub"])
        self.assertGreater(adults["updatedOptions"]["A"]["fairPriceBreakdown"]["baggage_fee_rub"], price["baggage_fee_rub"])

    def test_family_bookings_and_reload_keep_actual_composition(self):
        session = self.seed()
        family = self.action(session, "change_guests", adults=1, children_ages=[6], pet_friendly=False)
        restored = self.client.get("/api/trips/initial", params={"session_id": session["id"]}).json()
        self.assertEqual(restored["chatState"]["children_ages"], [6])
        voucher = self.client.post("/api/bookings", json={"trip": family["updatedOptions"]["A"]}).json()["voucher"]
        self.assertEqual(voucher["travellers"], {"adults": 1, "children_ages": [6], "passengers": 2, "withPet": False})

    def test_party_limits_and_unknown_ages_are_rejected(self):
        session = self.seed()
        for data in ({"adults": 0, "children_ages": [6]}, {"adults": 1, "children_ages": [0, 1]},
                     {"adults": 2, "children_ages": [18]}, {"adults": 10, "children_ages": [6]},
                     {"adults": 1, "children_ages": [True]}):
            response = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Измени гостей", "action_id": "change_guests", **data})
            self.assertEqual(response.status_code, 422, (data, response.text))
        with self.assertRaises(ValueError):
            _build_plan(session, "Еду с ребёнком", {"children_ages": [6]}, None)

    def test_budget_cannot_be_raised_by_family_or_origin_edit(self):
        session = self.seed()
        session["state"]["budget_rub"] = session["options"]["B"]["fairPriceBreakdown"]["grand_total_rub"] + 5000
        session["options"] = {"A": session["options"]["B"]}
        db.save_session(session)
        before = copy.deepcopy(db.load_session(session["id"]))
        result = self.action(session, "change_guests", adults=5, children_ages=[6, 7])
        self.assertTrue(result["changeRejected"])
        self.assertEqual(result["budget_rub"], before["state"]["budget_rub"])
        self.assertEqual(result["updatedOptions"], before["options"])

    def test_origin_editor_recalculates_and_relabels_departure(self):
        session = self.seed()
        result = self.action(session, "change_origin", origin="Казань")
        self.assertEqual(result["chatState"]["origin"], "Казань")
        for option in result["updatedOptions"].values():
            self.assertEqual(option["transport"]["depCity"], "Казань")
            self.assertIn("KZN", option["transport"]["depStation"])
            self.assertNotIn("VKO", option["transport"]["depStation"])
        self.assertNotEqual(result["updatedOptions"]["A"]["transport"]["price"], session["options"]["A"]["transport"]["price"])

    def test_unknown_origin_is_not_silently_mapped_to_moscow(self):
        session = self.seed()
        response = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Измени вылет", "action_id": "change_origin", "origin": "Неизвестный город"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(db.load_session(session["id"])["options"], session["options"])

    def test_origin_that_is_also_catalog_destination_does_not_replace_destination(self):
        session = self.seed()
        response = self.client.post("/api/chat", json={"session_id": session["id"],
            "message": "Измени город вылета на Калининград, остальные условия сохрани.",
            "action_id": "change_origin", "origin": "Калининград"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["chatState"]["destination"], "Сочи")
        self.assertEqual(response.json()["chatState"]["origin"], "Калининград")

    def test_explicit_budget_edit_question_still_applies_the_new_budget(self):
        session = self.seed()
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("src.services.openrouter_agent._completion", return_value={"role": "assistant", "content": "Условия сохранены."}):
            result = run_openrouter_turn(session["id"], "Можно ли увеличить бюджет до 600000 рублей?", "A")
        self.assertEqual(result["budget_rub"], 600000)

    def test_child_meals_are_recalculated_from_actual_party(self):
        session = self.seed()
        self.action(session, "change_guests", adults=2, children_ages=[1, 8])
        result = self.action(session, "meal_on")
        self.assertEqual(result["updatedOptions"]["A"]["fairPriceBreakdown"]["meal_addon_rub"], 6500)

    def test_public_flight_search_honors_family_and_time_filters(self):
        response = self.client.post("/api/tools/transfers-flights", json={
            "destination": "Сочи", "date": "2026-11-15", "return_date": "2026-11-19",
            "adults": 2, "children_ages": [1, 8],
            "departure_after": "12:45", "departure_before": "12:45"})
        self.assertEqual(response.status_code, 200, response.text)
        flights = response.json()["flights"]
        self.assertTrue(flights)
        for flight in flights:
            self.assertEqual(flight["departure_time"], "12:45")
            self.assertEqual(flight["party"]["adults"], 2)
            self.assertEqual(flight["party"]["children_ages"], [1, 8])

    def test_late_arrival_never_schedules_hotel_checkin_before_arrival(self):
        from datetime import datetime
        built, _ = build_trip_response("", {}, intent={"destination": "Сочи", "budget_rub": 500000,
            "checkin_date": "2026-11-15", "nights": 4, "departure_after": "11:00"})
        steps = built["updatedOptions"]["A"]["timeline"]
        parsed = [datetime.strptime(step["time"], "%d.%m.%Y, %H:%M") for step in steps]
        self.assertEqual(parsed, sorted(parsed))

    def test_adults_only_legacy_passenger_count_remains_supported(self):
        self.assertEqual(normalize_party({"passengers": 3}), {"adults": 3, "children_ages": [], "passengers": 3})

    def test_age_clarification_never_guesses_child_age_and_keeps_other_conditions(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("src.services.openrouter_agent._completion") as model:
            asked = run_openrouter_turn("family-clarify", "Хочу в Сочи: 3 взрослых с ребёнком, 4 ночи, бюджет 500000 рублей", "A")
            self.assertEqual(asked["updatedOptions"], {})
            self.assertIn("Сколько лет", asked["reply"])
            ready = run_openrouter_turn("family-clarify", "6 лет", "A")
        model.assert_not_called()
        self.assertEqual(ready["chatState"]["adults"], 3)
        self.assertEqual(ready["chatState"]["children_ages"], [6])
        self.assertEqual(ready["budget_rub"], 500000)
        self.assertTrue(ready["updatedOptions"])

    def test_demo_discussion_does_not_rebuild_and_demo_age_clarification_works(self):
        session = self.seed()
        result = self.client.post("/api/chat", json={"session_id": session["id"], "message": "Расскажи о собаке в поездке на 3 ночи?"}).json()
        self.assertEqual(result["updatedOptions"], session["options"])
        self.assertEqual(result["chatState"]["nights"], 4)
        asked = self.client.post("/api/chat", json={"session_id": "demo-child-clarify", "message": "Хочу в Сочи: 2 взрослых с ребёнком, бюджет 500000 рублей"}).json()
        self.assertIn("Сколько лет", asked["reply"])
        ready = self.client.post("/api/chat", json={"session_id": "demo-child-clarify", "message": "8 лет"}).json()
        self.assertEqual(ready["chatState"]["children_ages"], [8])
        self.assertEqual(ready["chatState"]["budget_rub"], 500000)

    def test_additional_child_age_clarification_preserves_existing_children(self):
        session = self.seed()
        self.action(session, "change_guests", adults=2, children_ages=[6])
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), patch("src.services.openrouter_agent._completion") as model:
            asked = run_openrouter_turn(session["id"], "Добавь ещё ребёнка", "A")
            self.assertIn("Сколько лет", asked["reply"])
            ready = run_openrouter_turn(session["id"], "8 лет", "A")
        model.assert_not_called()
        self.assertEqual(ready["chatState"]["children_ages"], [6, 8])

    def test_single_hotel_destination_never_duplicates_hotel_or_suggests_comparison(self):
        from src.services.openrouter_agent import _option_context, _hotel_context, _plan_reply
        built, state = build_trip_response("", {}, intent={"destination": "Калининград", "nights": 4, "passengers": 2})
        self.assertTrue(built["trip_assembled"])
        self.assertEqual(built["available_option_count"], 1)
        self.assertTrue(built["updatedOptions"]["A"]["available"])
        self.assertFalse(built["updatedOptions"]["B"]["available"])
        self.assertEqual(len(state["hotel_ids"]), 1)
        self.assertNotIn("Вариант Б", built["reply"])
        session = db.load_session("single-hotel-kaliningrad")
        session.update(state=state, options=built["updatedOptions"])
        db.save_session(session)
        self.assertEqual(list(_option_context(session["options"]).keys()), ["A"])
        self.assertEqual(len(_hotel_context(session)), 1)
        plan_text = _plan_reply(session, built)
        self.assertIn("Подходящий вариант уже показан справа", plan_text)
        self.assertNotIn("Вариант B", plan_text)
        self.assertNotIn("Два варианта", plan_text)

    def test_family_relations_recognition_with_children_ages_and_spouse(self):
        from src.services.travel_party import extract_party, needs_children_ages
        party = extract_party("Хотим с женой и сыном 8 лет к тёплому морю в ноябре на 4 ночи, с корги, бюджет до 180 000 рублей")
        self.assertEqual(party["adults"], 2)
        self.assertEqual(party["children_ages"], [8])
        self.assertEqual(party["passengers"], 3)
        self.assertFalse(needs_children_ages("Хотим с женой и сыном 8 лет", {}))

        party2 = extract_party("мы с мужем и дочкой 6 лет")
        self.assertEqual(party2["adults"], 2)
        self.assertEqual(party2["children_ages"], [6])

        built, state = build_trip_response(
            "Хотим с женой и сыном 8 лет к тёплому морю в ноябре на 4 ночи, с корги, бюджет до 250 000 рублей",
            {}
        )
        self.assertTrue(built["trip_assembled"])
        self.assertEqual(state["adults"], 2)
        self.assertEqual(state["children_ages"], [8])
        self.assertTrue(state["pet_friendly"])
        self.assertTrue(built["updatedOptions"]["A"]["available"])

        over_budget, _ = build_trip_response(
            "Хотим с женой и сыном 8 лет к тёплому морю в ноябре на 4 ночи, с корги, бюджет до 180 000 рублей",
            {}
        )
        self.assertFalse(over_budget["trip_assembled"])
        self.assertIn("нет поездки в пределах 180 000 ₽", over_budget["reply"])
        self.assertIn("Минимальная сумма по текущему каталогу — 225 180 ₽", over_budget["reply"])
