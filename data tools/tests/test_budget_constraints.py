import unittest

from src.services.budget_constraints import extract_budget_bounds, apply_budget_bounds, is_budget_only_request
from src.services.trip_planner import select_affordable_options, required_option_funds, enforce_saved_budget
from unittest.mock import patch


class BudgetConstraintTests(unittest.TestCase):
    def test_ranges_and_independent_limits(self):
        examples = {
            "Бюджет от 80 000 до 150 000 ₽": {"budget_min_rub": 80000, "budget_rub": 150000},
            "от 80 до 150 тыс.": {"budget_min_rub": 80000, "budget_rub": 150000},
            "бюджет 80–150 тысяч": {"budget_min_rub": 80000, "budget_rub": 150000},
            "минимум 80 тыс.": {"budget_min_rub": 80000},
            "от 80000 рублей": {"budget_min_rub": 80000},
            "не меньше 80 тысяч, не больше 150 тысяч": {"budget_min_rub": 80000, "budget_rub": 150000},
            "минимальная стоимость поездки 80000": {"budget_min_rub": 80000},
            "максимум 1,5 млн": {"budget_rub": 1500000},
            "150 000 ₽": {"budget_rub": 150000},
            "бюджет тысяч 50": {"budget_rub": 50000},
            "тыс. 80": {"budget_rub": 80000},
            "50к": {"budget_rub": 50000},
            "120k": {"budget_rub": 120000},
            "бюджет около 50к": {"budget_rub": 50000},
            "убери нижнюю границу": {"budget_min_rub": 0},
            "убери верхний лимит": {"budget_rub": None},
            "без верхнего ограничения": {"budget_rub": None},
            "с 3 до 7 мая": {},
            "минимум 3 ночи, максимум 5 гостей": {},
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(extract_budget_bounds(text), expected)
        self.assertTrue(is_budget_only_request("Установи бюджет от 80000 до 150000 ₽ за всю поездку"))
        self.assertTrue(is_budget_only_request("минимум 80 тысяч"))
        self.assertFalse(is_budget_only_request("Хочу в Сочи от 80000 до 150000 ₽"))

    def test_invalid_interval_never_changes_state(self):
        state = {"budget_rub": 100000, "budget_min_rub": 20000}
        with self.assertRaises(ValueError):
            apply_budget_bounds(state, {"budget_min_rub": 150000})
        self.assertEqual(state, {"budget_rub": 100000, "budget_min_rub": 20000})

    def test_minimum_is_total_with_deposit_and_cheapest_ignores_hotel_rank(self):
        hotels = [{"id": "expensive", "total": 120000, "deposit": 0},
                  {"id": "cheap", "total": 50000, "deposit": 10000},
                  {"id": "middle", "total": 75000, "deposit": 10000}]
        with patch("src.services.trip_planner.FairPriceCalculator.calculate_fair_price",
                   side_effect=lambda hotel, *args, **kw: {"grand_total_rub": hotel["total"], "refundable_deposit_rub": hotel["deposit"]}):
            state = {"passengers": 2, "nights": 4, "budget_rub": 130000, "budget_min_rub": 80000, "sort_by_price": True}
            choices, minimum = select_affordable_options(hotels, [{}], [{}], state)
        self.assertEqual(minimum, 85000)
        self.assertEqual(choices[0]["hotel"]["id"], "middle")
        self.assertEqual(len(choices), 2)

    def test_saved_options_are_filtered_on_both_boundaries(self):
        option = lambda total: {"fairPriceBreakdown": {"grand_total_rub": total, "refundable_deposit_rub": 0}}
        session = {"state": {"budget_rub": 150000, "budget_min_rub": 80000},
                   "options": {"A": option(55460), "B": option(103860)}, "selected_option": "A"}
        self.assertTrue(enforce_saved_budget(session))
        self.assertEqual(list(session["options"]), ["B"])
        self.assertEqual(session["selected_option"], "B")
        self.assertEqual(required_option_funds(session["options"]["B"]), 103860)
