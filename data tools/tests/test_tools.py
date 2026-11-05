import sys
import unittest

if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from src.tools.travel_tools import (
    search_destinations,
    search_hotels,
    search_transfers_and_flights,
    get_weather_forecast
)
from src.tools.tool_definitions import OPENAI_TOOL_DEFINITIONS, execute_tool_call

class TestTravelTools(unittest.TestCase):

    def test_search_destinations_vibe(self):
        res = search_destinations(query="где тепло в ноябре с ребенком", limit=3)
        self.assertIn("destinations", res)
        self.assertTrue(len(res["destinations"]) > 0)
        # Дубай или Пхукет должны быть в топе из-за тепла в ноябре
        names = [d["name"] for d in res["destinations"]]
        self.assertTrue("Дубай" in names or "Пхукет" in names)

    def test_search_hotels_filters(self):
        # Поиск шале с камином и pet-friendly в Шерегеше
        res = search_hotels(
            destination="Шерегеш",
            vibe_query="камин шале",
            pet_friendly=True,
            limit=2
        )
        self.assertIn("hotels", res)
        self.assertTrue(len(res["hotels"]) > 0)
        h = res["hotels"][0]
        self.assertTrue(h["pet_friendly"]["allowed"])
        self.assertIsNotNone(h["total_price"])

    def test_search_hotels_no_deposit(self):
        res = search_hotels(
            destination="Сочи",
            no_deposit=True,
            limit=3
        )
        for h in res["hotels"]:
            self.assertFalse(h["deposit"]["required"])

    def test_search_transfers_and_flights(self):
        res = search_transfers_and_flights(
            origin="Москва",
            destination="Сочи",
            date="2026-11-20",
            passengers=2,
            hotel_checkin_time="14:00"
        )
        self.assertIn("flights", res)
        self.assertIn("transfers", res)
        self.assertIn("timing_analysis", res)
        self.assertTrue(len(res["flights"]) >= 2)
        self.assertEqual(res["flights"][0]["total_price"], res["flights"][0]["price_per_passenger"] * 2)

    def test_weather_forecast(self):
        res = get_weather_forecast(city="Дубай", days=3)
        self.assertIn("forecast", res)
        self.assertIn("verdict", res)
        self.assertEqual(len(res["forecast"]), 3)

    def test_execute_tool_call(self):
        call_res = execute_tool_call(
            "search_destinations",
            {"query": "лыжи", "month": 12, "limit": 1}
        )
        self.assertIn("destinations", call_res)
        self.assertEqual(len(call_res["destinations"]), 1)

    def test_tool_definitions_schema(self):
        self.assertEqual(len(OPENAI_TOOL_DEFINITIONS), 4)
        names = [t["function"]["name"] for t in OPENAI_TOOL_DEFINITIONS]
        self.assertIn("search_destinations", names)
        self.assertIn("search_hotels", names)
        self.assertIn("search_transfers_and_flights", names)
        self.assertIn("get_weather_forecast", names)

if __name__ == "__main__":
    unittest.main()
