import unittest

from src.services.flight_preferences import extract_flight_preferences


class FlightPreferenceTests(unittest.TestCase):
    def test_weekday_edits_are_based_on_the_outbound_date(self):
        result = extract_flight_preferences("Вылет в воскресенье после 11, вернуться вечером в пятницу",
                                            {"checkin_date": "2026-10-28"})
        self.assertEqual(result["checkin_date"], "2026-11-01")
        self.assertEqual(result["checkout_date"], "2026-11-06")
        self.assertEqual(result["departure_after"], "11:00")
        self.assertEqual(result["return_arrival_after"], "18:00")

    def test_flight_questions_do_not_silently_edit_the_plan(self):
        for text in ("Во сколько обратный вылет?", "Почему рейс утром?", "Расскажи про вечерний рейс"):
            self.assertEqual(extract_flight_preferences(text), {})

    def test_return_departure_and_home_arrival_are_distinct(self):
        self.assertEqual(extract_flight_preferences("Хочу обратный вылет вечером")["return_departure_after"], "18:00")
        self.assertEqual(extract_flight_preferences("Хочу вернуться вечером")["return_arrival_after"], "18:00")

    def test_exact_flight_time_is_not_rounded_to_available_departure(self):
        result = extract_flight_preferences("Вылет в 13:00")
        self.assertEqual(result, {"departure_after": "13:00", "departure_before": "13:00"})

    def test_not_later_is_an_upper_bound_not_a_request_for_a_later_flight(self):
        result = extract_flight_preferences("Вылет не позже 08:00", options={"A": {"transport": {"depTime": "06:10"}}})
        self.assertEqual(result, {"departure_before": "08:00"})
