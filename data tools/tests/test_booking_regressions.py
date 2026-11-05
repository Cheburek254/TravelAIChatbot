import copy
import os
import unittest
from unittest.mock import patch

from tests import test_chat_and_database as fixtures
from src.services import database as db
from src.services.accommodation import requested_room_count, validate_room_count
from src.services.agent_orchestrator import build_trip_response
from src.services.logistics_engine import format_duration
from src.services.openrouter_agent import _build_plan
from src.services.trip_planner import required_option_funds


class BookingRegressionTests(unittest.TestCase):
    def setUp(self):
        fixtures.ChatDatabaseTests.setUp(self)

    def tearDown(self):
        fixtures.ChatDatabaseTests.tearDown(self)

    def seed(self, sid, adults=3, ages=None, rooms=3):
        built, state = build_trip_response('', {}, intent={
            'destination': 'Сочи', 'budget_rub': 500000, 'adults': adults,
            'children_ages': ages or [], 'room_count': rooms,
            'checkin_date': '2026-11-15', 'nights': 4,
        })
        self.assertTrue(built['trip_assembled'])
        session = db.load_session(sid)
        session.update(state=state, options=built['updatedOptions'])
        db.save_session(session)
        return session

    def chat(self, sid, message, **values):
        response = self.client.post('/api/chat', json={'session_id': sid, 'message': message, **values})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_duration_is_hours_and_minutes_with_carry(self):
        for hours, expected in ((3.83, '3 ч 50 мин'), (3.5, '3 ч 30 мин'),
                                (0.75, '0 ч 45 мин'), (1.999, '2 ч 0 мин'), (25.25, '25 ч 15 мин')):
            with self.subTest(hours=hours):
                self.assertEqual(format_duration(hours), expected)

    def test_duration_reaches_actual_cards(self):
        session = self.seed('duration-cards')
        for option in session['options'].values():
            self.assertRegex(option['transport']['duration'], r'^\d+ ч \d+ мин$')

    def test_room_request_targets_new_count_not_old(self):
        for text, count in (
            ('а можно в 2 номера заселиться а не в 3?', 2),
            ('Измени с 3 номеров на 2 номера', 2),
            ('Хочу три номера вместо двух номеров', 3),
            ('Оставь два номера', 2), ('Нужно 0 номеров', 0),
        ):
            self.assertEqual(requested_room_count(text), count)

    def test_room_discussion_and_negation_do_not_request_changes(self):
        for text in ('Почему нужны 3 номера?', 'Сколько стоят 2 номера?',
                     'Не меняй, оставь 3 номера', 'Расскажи про два номера', 'Не хочу 2 номера'):
            self.assertIsNone(requested_room_count(text))

    def test_room_count_uses_seats_not_infant_count(self):
        self.assertEqual(validate_room_count(2, [1], 1), 1)
        with self.assertRaises(ValueError):
            validate_room_count(2, [2], 1)
        for invalid in (0, 11, True, 1.5):
            with self.assertRaises(ValueError):
                validate_room_count(2, [], invalid)

    def test_room_preference_before_destination_is_retained(self):
        result = self.chat('rooms-first', 'Хочу 3 номера')
        self.assertFalse(result['updatedOptions'])
        self.assertEqual(result['chatState']['room_count'], 3)
        ready = self.chat('rooms-first', 'Хочу в Сочи на 4 ночи бюджет 500000 рублей')
        self.assertEqual(ready['updatedOptions']['A']['hotel']['rooms'], 3)

    def test_unaffordable_maldives_are_not_silently_replaced_with_sochi(self):
        result = self.chat('budget-no-substitute', 'Хочу на Мальдивы на неделю, бюджет 25000 рублей')
        self.assertEqual(result['chatState']['destination'], 'Мальдивы')
        self.assertFalse(result['updatedOptions'])
        self.assertIn('Мальдивы', result['reply'])

    def test_room_change_updates_cards_prices_history_and_reload_in_both_modes(self):
        for mode in ('demo', 'model'):
            sid = 'rooms-change-' + mode
            before = self.seed(sid)
            with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-key' if mode == 'model' else ''}), \
                    patch('src.services.openrouter_agent._completion', side_effect=AssertionError('No model needed')):
                result = self.chat(sid, 'а можно в 2 номера заселиться а не в 3?')
            self.assertTrue(result['trip_assembled'])
            self.assertIn('**2**', result['reply'])
            self.assertEqual(result['chatState']['adults'], 3)
            for key, option in result['updatedOptions'].items():
                self.assertEqual(option['hotel']['rooms'], 2)
                self.assertEqual(option['hotel']['id'], before['options'][key]['hotel']['id'])
                price = option['fairPriceBreakdown']
                self.assertEqual(price['rooms'], 2)
                self.assertEqual(price['hotel_base_rub'], option['hotel']['roomPricePerNight'] * 4 * 2)
                self.assertEqual(option['hotel']['pricePerNight'], option['hotel']['roomPricePerNight'] * 2)
                self.assertLess(price['grand_total_rub'], before['options'][key]['fairPriceBreakdown']['grand_total_rub'])
            reloaded = self.client.get('/api/trips/initial', params={'session_id': sid}).json()
            self.assertEqual(reloaded['A'], result['updatedOptions']['A'])
            self.assertIn('Количество номеров изменено', db.load_session(sid)['messages'][-1]['content'])

    def test_too_few_rooms_gives_reason_and_preserves_party_cards_and_state(self):
        before = self.seed('rooms-capacity', adults=5)
        result = self.chat('rooms-capacity', 'а можно в 2 номера заселиться а не в 3?')
        self.assertTrue(result['changeRejected'])
        self.assertIn('минимум 3', result['reply'])
        self.assertEqual(result['updatedOptions'], before['options'])
        self.assertEqual(db.load_session('rooms-capacity')['state'], before['state'])

    def test_more_rooms_cannot_exceed_saved_budget(self):
        session = self.seed('rooms-budget', adults=2, rooms=1)
        cap = max(required_option_funds(o) for o in session['options'].values())
        session['state'].update(budget_rub=cap, user_budget_rub=cap)
        db.save_session(session)
        before = copy.deepcopy(session)
        result = self.chat('rooms-budget', 'Хочу 10 номеров')
        self.assertTrue(result['changeRejected'])
        self.assertEqual(result['updatedOptions'], before['options'])
        self.assertEqual(db.load_session('rooms-budget')['state'], before['state'])

    def test_requested_rooms_survive_conditional_date_shift(self):
        self.seed('rooms-shift')
        changed = self.chat('rooms-shift', 'Хочу 2 номера')
        result = self.chat('rooms-shift', 'Перенести даты', action_id='change_dates',
                           checkin_date='2026-12-01', checkout_date='2026-12-05')
        self.assertEqual(result['chatState']['room_count'], 2)
        self.assertEqual(result['updatedOptions']['A']['hotel']['rooms'], 2)
        self.assertEqual(result['updatedOptions']['A']['fairPriceBreakdown'], changed['updatedOptions']['A']['fairPriceBreakdown'])

    def test_model_cannot_invent_room_count(self):
        session = self.seed('rooms-model-guard')
        before = copy.deepcopy(session)
        with self.assertRaisesRegex(ValueError, 'число номеров'):
            _build_plan(session, 'Хочу отель поближе к пляжу', {'room_count': 5}, {})
        self.assertEqual(session, before)

    def test_more_guests_increase_rooms_to_capacity(self):
        self.seed('rooms-guests', adults=2, rooms=1)
        result = self.chat('rooms-guests', 'Изменить гостей', action_id='change_guests', adults=5, children_ages=[])
        self.assertTrue(result['trip_assembled'])
        self.assertEqual(result['chatState']['room_count'], 3)
        self.assertEqual(result['updatedOptions']['A']['hotel']['rooms'], 3)

    def test_early_checkin_fee_uses_requested_rooms(self):
        built, _ = build_trip_response('', {}, intent={'destination': 'Калининград', 'budget_rub': 500000,
            'adults': 2, 'children_ages': [], 'room_count': 3, 'include_early_checkin': True,
            'checkin_date': '2026-11-15', 'nights': 4})
        self.assertTrue(built['trip_assembled'])
        for option in built['updatedOptions'].values():
            self.assertEqual(option['fairPriceBreakdown']['early_checkin_rub'],
                             round(option['hotel']['roomPricePerNight'] * 3 * 0.5, -2))


if __name__ == '__main__':
    unittest.main()
