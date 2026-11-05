import sys
import unittest

if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from src.services.logistics_engine import (
    TimelineValidator,
    FairPriceCalculator,
    TradeoffAnalyzer,
    BookingCartAssembler,
    LogisticsAndTradeoffEngine,
)
from src.services.agent_orchestrator import run_agent_turn


class TestLogisticsAndTradeoffEngine(unittest.TestCase):
    def setUp(self):
        self.sample_hotel_a = {
            "id": "hotel_sochi_01",
            "name": "Radisson Collection Paradise Resort & Spa",
            "destination_id": "sochi",
            "destination_name": "Сочи",
            "stars": 5,
            "rating": 9.6,
            "reviews_count": 1240,
            "price_per_night": 21000,
            "currency": "RUB",
            "address": "г. Сочи, ул. 65 Лет Победы, 50",
            "distance_to_center_km": 30.0,
            "distance_to_beach_m": 50,
            "checkin_time": "15:00",
            "checkout_time": "12:00",
            "early_checkin_available": True,
            "late_checkout_available": True,
            "pet_friendly": {"allowed": False, "fee_per_stay": 0, "max_weight_kg": 0, "description": "Без животных"},
            "deposit": {"required": True, "amount": 10000, "currency": "RUB", "description": "Депозит 10 000 руб."},
            "cancellation_policy": {"type": "free_cancellation", "free_cancellation_days_before": 1, "description": "Бесплатная отмена за 24 часа."},
            "meal_type": "BB",
            "meal_description": "Премиальный завтрак включен",
            "amenities": ["first_line_beach", "heated_pool", "spa"],
        }
        self.sample_hotel_b = {
            "id": "hotel_sochi_03",
            "name": "Отель Бридж Резорт Сочи",
            "destination_id": "sochi",
            "destination_name": "Сочи",
            "stars": 4,
            "rating": 8.9,
            "reviews_count": 2100,
            "price_per_night": 8900,
            "currency": "RUB",
            "address": "г. Сочи, ул. Фигурная, 45",
            "distance_to_center_km": 32.0,
            "distance_to_beach_m": 250,
            "checkin_time": "14:00",
            "checkout_time": "12:00",
            "early_checkin_available": True,
            "late_checkout_available": False,
            "pet_friendly": {"allowed": True, "fee_per_stay": 2000, "max_weight_kg": 8, "description": "Можно с питомцем до 8 кг"},
            "deposit": {"required": False, "amount": 0, "currency": "RUB", "description": "Без залога."},
            "cancellation_policy": {"type": "free_cancellation", "free_cancellation_days_before": 2, "description": "Бесплатная отмена за 2 дня."},
            "meal_type": "AI",
            "meal_description": "Все включено (All Inclusive)",
            "amenities": ["pool", "all_inclusive", "kids_club"],
        }
        self.night_flight = {
            "flight_number": "DP-301",
            "airline": "Победа",
            "origin": "Москва (VKO)",
            "destination": "Сочи (AER)",
            "departure_time": "23:40",
            "arrival_time": "03:00",
            "duration_hours": 3.5,
            "is_direct": True,
            "baggage": {"included": False, "weight_kg": 0, "carry_on_kg": 10},
            "price_per_passenger": 6600,
            "total_price": 13200,
        }
        self.day_flight = {
            "flight_number": "SU-1120",
            "airline": "Аэрофлот",
            "origin": "Москва (SVO)",
            "destination": "Сочи (AER)",
            "departure_time": "09:10",
            "arrival_time": "12:50",
            "duration_hours": 3.6,
            "is_direct": True,
            "baggage": {"included": True, "weight_kg": 23, "carry_on_kg": 10},
            "price_per_passenger": 8500,
            "total_price": 17000,
        }
        self.transfer = {
            "type": "Комфорт+ (Седан)",
            "vehicle": "Toyota Camry",
            "duration_minutes": 45,
            "price_rub": 2200,
            "description": "Встреча с табличкой",
        }

    def test_night_arrival_conflict_detected(self):
        res = TimelineValidator.validate_timeline(
            flight=self.night_flight,
            transfer=self.transfer,
            hotel=self.sample_hotel_a,
        )
        self.assertEqual(res["status"], "night_arrival_conflict")
        self.assertTrue(res["early_checkin_needed"])
        self.assertGreater(res["early_checkin_fee_rub"], 0)
        self.assertTrue(res["conflict_resolved"])

    def test_perfect_day_arrival(self):
        res = TimelineValidator.validate_timeline(
            flight=self.day_flight,
            transfer=self.transfer,
            hotel=self.sample_hotel_b,
        )
        self.assertEqual(res["status"], "perfect_match")
        self.assertFalse(res["early_checkin_needed"])

    def test_fair_price_calculator_includes_hidden_fees(self):
        pricing = FairPriceCalculator.calculate_fair_price(
            hotel=self.sample_hotel_b,
            flight=self.night_flight,
            transfer=self.transfer,
            nights=4,
            passengers=2,
            with_pet=True,
            has_meal_addon=True,
        )
        self.assertEqual(pricing["hotel_base_rub"], 8900 * 4)
        self.assertEqual(pricing["flight_base_rub"], 13200)
        self.assertEqual(pricing["baggage_fee_rub"], 3600)
        self.assertEqual(pricing["pet_fee_rub"], 2000)
        self.assertEqual(pricing["resort_fee_rub"], 800)
        self.assertEqual(pricing["meal_addon_rub"], 5200)
        expected_total = 35600 + 13200 + 2200 + 3600 + 2000 + 800 + 5200
        self.assertEqual(pricing["grand_total_rub"], expected_total)

    def test_tradeoff_analyzer_generates_pros_cons_risks(self):
        t_a = TimelineValidator.validate_timeline(self.day_flight, self.transfer, self.sample_hotel_a)
        t_b = TimelineValidator.validate_timeline(self.night_flight, self.transfer, self.sample_hotel_b)
        p_a = FairPriceCalculator.calculate_fair_price(self.sample_hotel_a, self.day_flight, self.transfer, nights=4, passengers=2)
        p_b = FairPriceCalculator.calculate_fair_price(self.sample_hotel_b, self.night_flight, self.transfer, nights=4, passengers=2, with_pet=True)

        analysis_b = TradeoffAnalyzer.analyze_option(
            option_key="B",
            hotel=self.sample_hotel_b,
            flight=self.night_flight,
            transfer=self.transfer,
            timing=t_b,
            pricing=p_b,
            other_pricing=p_a,
            other_hotel=self.sample_hotel_a,
        )
        self.assertIn("экономит", analysis_b["why_this"])
        self.assertTrue(len(analysis_b["pros"]) >= 2)
        self.assertTrue(len(analysis_b["cons"]) >= 2)
        self.assertTrue(len(analysis_b["risks"]) >= 1)

    def test_voucher_and_receipt_assembly(self):
        turn = run_agent_turn(
            session_id="test_role3_session",
            message="Хочу в Сочи вдвоём с корги на 4 ночи",
            selected_option="A",
        )
        opt_a = turn["updatedOptions"]["A"]
        booking = BookingCartAssembler.create_voucher_and_receipt(trip=opt_a, total_price=turn["total_price_rub"])
        self.assertEqual(booking["status"], "confirmed")
        self.assertTrue(booking["voucherId"].startswith("OST-"))
        self.assertTrue(booking["pnr"].startswith("AERO-"))
        self.assertIn("receipt", booking)
        self.assertIn("voucher", booking)
        self.assertEqual(booking["receipt"]["grand_total_rub"], turn["total_price_rub"])


if __name__ == "__main__":
    unittest.main()