"""Regressions for family travel, hotel details and SQL persistence."""
import copy
import os
import unittest
from unittest.mock import patch

from sqlalchemy import update
from tests import test_chat_and_database as fixtures
from src.services import database as db
from src.services.agent_orchestrator import build_trip_response
from src.services.openrouter_agent import _option_context
from src.services.travel_party import extract_party, needs_children_ages


class IssueRegressionTests(unittest.TestCase):
    def setUp(self):
        fixtures.ChatDatabaseTests.setUp(self)

    def tearDown(self):
        fixtures.ChatDatabaseTests.tearDown(self)

    def chat(self, sid, message):
        response = self.client.post('/api/chat', json={'session_id': sid, 'message': message})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def seed(self, sid, ages):
        built, state = build_trip_response('', {}, intent={'destination': 'Сочи', 'budget_rub': 500000,
            'adults': 2, 'children_ages': ages, 'checkin_date': '2026-11-15', 'nights': 4})
        session = db.load_session(sid)
        session.update(state=state, options=built['updatedOptions'])
        db.save_session(session)
        return session

    def test_spouse_and_child_without_age_wait_for_clarification(self):
        for provider in ('demo', 'model'):
            with self.subTest(provider=provider), patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-key' if provider == 'model' else ''}), \
                    patch('src.services.openrouter_agent._completion', side_effect=AssertionError('No model needed')):
                sid = 'missing-age-' + provider
                first = self.chat(sid, 'Хочу в Сочи с мужем и сыном на 4 ночи, бюджет 500000 рублей')
                self.assertFalse(first['updatedOptions'])
                self.assertIn('Сколько лет', first['reply'])
                ready = self.chat(sid, '8 лет')
                self.assertEqual(ready['chatState']['adults'], 2)
                self.assertEqual(ready['chatState']['children_ages'], [8])
                self.assertEqual(ready['chatState']['budget_rub'], 500000)
                self.assertEqual(ready['updatedOptions']['A']['travellers']['passengers'], 3)

    def test_multiple_siblings_reach_cards_prices_and_voucher(self):
        result = self.chat('siblings-review', 'Хочу в Сочи с женой, сыном 8 лет и дочкой 6 лет на 4 ночи, бюджет 500000 рублей')
        self.assertEqual(result['chatState']['children_ages'], [8, 6])
        self.assertEqual(result['chatState']['passengers'], 4)
        option = result['updatedOptions']['A']
        self.assertEqual(option['hotel']['rooms'], 2)
        self.assertEqual(option['fairPriceBreakdown']['hotel_base_rub'], option['hotel']['pricePerNight'] * 4)
        voucher = self.client.post('/api/bookings', json={'trip': option}).json()['voucher']
        self.assertEqual(voucher['travellers']['children_ages'], [8, 6])
        restored = self.client.get('/api/trips/initial', params={'session_id': 'siblings-review'}).json()
        self.assertEqual(restored['chatState']['children_ages'], [8, 6])

    def test_partially_known_siblings_and_plural_counts_require_all_ages(self):
        for text in ('С женой, сыном 8 лет и дочкой', 'Двое детей 8 лет', 'С мужем и двумя детьми'):
            with self.subTest(text=text):
                self.assertTrue(needs_children_ages(text, {}))
                self.assertNotIn('children_ages', extract_party(text))

    def test_child_age_parser_does_not_take_nights_or_budget_as_age(self):
        for text in ('С сыном на 4 ночи до 500000 рублей', 'С детьми 4 ночи', 'Ребёнок 15000 рублей'):
            with self.subTest(text=text):
                self.assertNotIn('children_ages', extract_party(text))
                self.assertTrue(needs_children_ages(text, {}))
        self.assertFalse(needs_children_ages('Нужна детская кроватка', {}))

    def test_explicit_adult_count_precedes_spouse_inference(self):
        for number, text in ((4, 'Едем четверо взрослых: я с женой и друзья'),
                             (3, 'Трое взрослых, включая меня с мужем'), (4, '4 взрослых, я с женой')):
            with self.subTest(text=text):
                self.assertEqual(extract_party(text)['adults'], number)

    def test_add_son_or_daughter_after_age_question_preserves_existing_child(self):
        for provider in ('demo', 'model'):
            for child in ('сына', 'дочь'):
                with self.subTest(provider=provider, child=child), patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-key' if provider == 'model' else ''}), \
                        patch('src.services.openrouter_agent._completion', side_effect=AssertionError('No model needed')):
                    sid = f'append-{provider}-{"daughter" if child == "дочь" else "son"}'
                    self.seed(sid, [6])
                    first = self.chat(sid, 'Добавь ' + child)
                    self.assertIn('Сколько лет', first['reply'])
                    second = self.chat(sid, '8 лет')
                    self.assertEqual(second['chatState']['children_ages'], [6, 8])
                    self.assertEqual(second['updatedOptions']['A']['travellers']['passengers'], 4)

    def test_add_child_with_age_is_applied_without_model(self):
        self.seed('append-known-age', [6])
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-key'}), \
                patch('src.services.openrouter_agent._completion', side_effect=AssertionError('No model needed')):
            result = self.chat('append-known-age', 'Добавь дочь 8 лет')
        self.assertEqual(result['chatState']['children_ages'], [6, 8])

    def test_room_answer_matches_card_in_both_chat_modes(self):
        for provider in ('demo', 'model'):
            sid = 'shared-room-' + provider
            session = self.seed(sid, [2])
            before = copy.deepcopy(session['options'])
            with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-key' if provider == 'model' else ''}), \
                    patch('src.services.openrouter_agent._completion', side_effect=AssertionError('No model needed')):
                result = self.chat(sid, 'можно ребенка с нами в 1 номер')
            self.assertIn('**2 номера**', result['reply'])
            self.assertIn('не подтверждено', result['reply'])
            self.assertEqual(result['updatedOptions'], before)
            context = _option_context(before)
            self.assertEqual(context['A']['hotel']['rooms'], 2)

    def test_infant_already_in_one_room_is_not_promised_extra_bed(self):
        self.seed('infant-shared-room', [1])
        result = self.chat('infant-shared-room', 'Можно ребёнка с нами в один номер?')
        self.assertIn('**1 номер**', result['reply'])
        self.assertIn('по запросу', result['reply'])
        self.assertEqual(result['updatedOptions']['A']['hotel']['rooms'], 1)

    def test_sql_route_edits_survive_application_restart(self):
        route_id = 'dubai'
        original = db.load_catalog('routes')[route_id]
        edited = {**original, 'base_price_rub': 12345, 'custom_note': 'SQL edit'}
        with db.get_engine().begin() as conn:
            conn.execute(update(db.routes).where(db.routes.c.id == route_id).values(data=edited))
        db._engine.dispose()
        db._engine = None
        after = db.load_catalog('routes')[route_id]
        self.assertEqual(after['base_price_rub'], 12345)
        self.assertEqual(after['custom_note'], 'SQL edit')

    def test_known_old_demo_route_receives_only_the_targeted_migration(self):
        original = db.load_catalog('routes')['dubai']
        legacy = copy.deepcopy(original)
        for transfer in legacy['transfers']:
            transfer['pet_friendly'] = False
        with db.get_engine().begin() as conn:
            conn.execute(update(db.routes).where(db.routes.c.id == 'dubai').values(data=legacy))
        db._engine.dispose()
        db._engine = None
        migrated = db.load_catalog('routes')['dubai']
        self.assertTrue(all(t['pet_friendly'] for t in migrated['transfers']))
        self.assertEqual(migrated['base_price_rub'], original['base_price_rub'])

    def test_tariff_copy_has_correct_spelling(self):
        option = self.seed('tariff-spelling', [1])['options']['A']
        text = option['fairPriceBreakdown']['demo_party_tariff']
        self.assertIn('авиатарифа', text)
        self.assertNotIn('авиатарфа', text)
