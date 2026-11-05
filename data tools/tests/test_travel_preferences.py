import unittest

from src.services.travel_preferences import (extract_travel_styles, inspiration_styles, matches_destination,
    matches_hotel, restore_travel_styles)


class TravelPreferenceTests(unittest.TestCase):
    def test_explicit_styles_and_negation(self):
        self.assertEqual(extract_travel_styles("Отдых в горах"), ["mountains"])
        self.assertEqual(extract_travel_styles("Горы и море"), ["mountains", "sea"])
        self.assertEqual(extract_travel_styles("не хочу в горы, лучше к морю"), ["sea"])
        self.assertEqual(extract_travel_styles("в городе с собакой"), [])
        self.assertEqual(inspiration_styles("Помоги выбрать направление для отдыха в горах. Сначала предложи направления и уточни условия."), ["mountains"])
        self.assertIsNone(inspiration_styles("Хочу в горы на 7 ночей с собакой"))

    def test_catalog_tags_are_required_not_arbitrary_description_words(self):
        self.assertTrue(matches_destination({"vibes": ["горы", "море"]}, ["mountains"]))
        self.assertFalse(matches_destination({"vibes": ["пляж"], "description": "из города видны горы"}, ["mountains"]))
        self.assertTrue(matches_hotel({"vibe_tags": ["уютное шале в горах"]}, ["mountains"]))
        self.assertFalse(matches_hotel({"vibe_tags": ["первая линия", "море"]}, ["mountains"]))

    def test_legacy_style_comes_only_from_user_messages(self):
        session = {"state": {}, "messages": [{"role": "assistant", "content": "Хочу в горы"}]}
        self.assertFalse(restore_travel_styles(session))
        session["messages"].append({"role": "user", "content": "Хочу к морю"})
        self.assertTrue(restore_travel_styles(session))
        self.assertEqual(session["state"]["travel_styles"], ["sea"])
