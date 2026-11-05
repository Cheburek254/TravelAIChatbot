"""Regressions for hotel search, departure cities and flight times."""
import copy
import os
import unittest
from unittest.mock import patch

from tests import test_chat_and_database as fixtures
from tests import test_schedule_routes as schedules
from src.services import database as db
from src.services.agent_orchestrator import build_trip_response
from src.services.departure_cities import CITIES
from src.services.flight_preferences import extract_flight_preferences
from src.services.flight_service import FlightService


class NewIssueRegressionTests(unittest.TestCase):
    def setUp(self):
        fixtures.ChatDatabaseTests.setUp(self)

    def tearDown(self):
        fixtures.ChatDatabaseTests.tearDown(self)

    def seed(self, sid='new-issue-test', destination='Сочи'):
        built, state = build_trip_response('', {}, intent={'destination': destination,
            'budget_rub': 500000, 'adults': 2, 'children_ages': [],
            'checkin_date': '2026-11-15', 'nights': 4})
        self.assertTrue(built['trip_assembled'])
        session = db.load_session(sid)
        session.update(state=state, options=built['updatedOptions'])
        db.save_session(session)
        return session

    def chat(self, sid, message, **values):
        response = self.client.post('/api/chat', json={'session_id': sid, 'message': message, **values})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_unsupported_origin_lists_every_supported_city_without_changing_plan(self):
        session = self.seed()
        before = copy.deepcopy(session)
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-key'}), \
                patch('src.services.openrouter_agent._completion', side_effect=AssertionError('No model needed')):
            result = self.chat(session['id'], 'я лечу из Пензы')
        self.assertTrue(result['changeRejected'])
        for city in CITIES:
            self.assertIn(city, result['reply'])
        self.assertEqual(result['updatedOptions'], before['options'])
        self.assertEqual(db.load_session(session['id'])['state'], before['state'])

    def test_origin_information_uses_same_list_as_header(self):
        result = self.chat('origin-info-test', 'Из каких городов можно вылететь?')
        initial = self.client.get('/api/trips/initial', params={'session_id': 'origin-info-test'}).json()
        self.assertFalse(result['updatedOptions'])
        for city in initial['departureCities']:
            self.assertIn(city, result['reply'])
        self.assertFalse(result.get('changeRejected'))

    def test_known_origin_in_natural_text_reprices_the_cards(self):
        for city, phrase in (('Казань', 'Казани'), ('Калининград', 'Калининграда')):
            with self.subTest(city=city):
                session = self.seed(sid='origin-' + CITIES[city][0])
                result = self.chat(session['id'], 'я лечу из ' + phrase)
                self.assertEqual(result['chatState']['origin'], city)
                self.assertEqual(result['chatState']['destination'], 'Сочи')
                self.assertEqual(result['chatState']['budget_rub'], 500000)
                self.assertEqual(result['models_used'], [])
                self.assertTrue(all(o['transport']['depCity'] == city for o in result['updatedOptions'].values()))

    def test_initial_origin_and_destination_work_without_model(self):
        for city, phrase in (('Казань', 'Казани'), ('Калининград', 'Калининграда')):
            with self.subTest(city=city):
                result = self.chat('initial-origin-' + CITIES[city][0], 'Хочу лететь из ' + phrase + ' в Сочи на 4 ночи, бюджет 500000 рублей')
                self.assertTrue(result['updatedOptions'])
                self.assertEqual(result['chatState']['origin'], city)
                self.assertEqual(result['chatState']['destination'], 'Сочи')
                self.assertEqual(result['chatState']['budget_rub'], 500000)

    def test_other_hotels_excludes_both_displayed_hotels_and_keeps_budget(self):
        session = self.seed()
        before = {o['hotel']['id'] for o in session['options'].values() if o.get('available', True)}
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-key'}), \
                patch('src.services.openrouter_agent._completion', side_effect=AssertionError('No model needed')):
            result = self.chat(session['id'], 'выведи другие отели')
        after = {o['hotel']['id'] for o in result['updatedOptions'].values() if o.get('available', True)}
        self.assertTrue(after)
        self.assertTrue(before.isdisjoint(after), (before, after))
        self.assertEqual(result['chatState']['budget_rub'], 500000)
        self.assertEqual(result['chatState']['checkin_date'], '2026-11-15')
        self.assertEqual(result['models_used'], [])

    def test_exhausted_hotel_catalog_reports_unavailable_and_preserves_cards(self):
        session = self.seed(destination='Калининград')
        before = copy.deepcopy(session)
        result = self.chat(session['id'], 'покажи другие отели')
        self.assertTrue(result['changeRejected'])
        self.assertIn('Других подходящих отелей', result['reply'])
        self.assertEqual(result['updatedOptions'], before['options'])
        self.assertEqual(db.load_session(session['id'])['state'], before['state'])

    def test_arrival_clock_with_dot_is_not_a_departure_request(self):
        result = extract_flight_preferences('хочу время прилета до 12.30')
        self.assertEqual(result, {'arrival_before': '12:30'})
        self.assertEqual(extract_flight_preferences('Хочу прилететь до 12:30'), result)

    def test_arrival_deadline_changes_actual_flight_and_replaces_old_departure_window(self):
        session = self.seed()
        late = self.chat(session['id'], 'Вылет в 12:45')
        self.assertTrue(all(o['transport']['arrTime'] > '12:30' for o in late['updatedOptions'].values()))
        result = self.chat(session['id'], 'хочу время прилета до 12.30')
        self.assertFalse(result.get('changeRejected'))
        self.assertTrue(all(o['transport']['arrTime'] <= '12:30' for o in result['updatedOptions'].values()))
        self.assertEqual(result['chatState']['arrival_before'], '12:30')
        self.assertNotIn('departure_after', result['chatState'])
        before_ids = {o['hotel']['id'] for o in late['updatedOptions'].values()}
        self.assertEqual({o['hotel']['id'] for o in result['updatedOptions'].values()}, before_ids)

    def test_impossible_arrival_deadline_reports_no_tickets_and_preserves_plan(self):
        session = self.seed()
        before = copy.deepcopy(session)
        result = self.chat(session['id'], 'Хочу прилететь до 05.00')
        self.assertTrue(result['changeRejected'])
        self.assertIn('Нет подходящих билетов', result['reply'])
        self.assertEqual(result['updatedOptions'], before['options'])
        self.assertEqual(db.load_session(session['id'])['state'], before['state'])

    def test_before_lunch_means_home_arrival_unless_departure_is_explicit(self):
        arrival = extract_flight_preferences('хочу вернуться обратно до обеда')
        self.assertEqual(arrival['return_arrival_before'], '11:59')
        self.assertNotIn('return_departure_before', arrival)
        departure = extract_flight_preferences('Хочу обратный вылет до обеда')
        self.assertEqual(departure['return_departure_before'], '11:59')
        self.assertNotIn('return_arrival_before', departure)

    def test_earlier_home_arrival_replaces_previous_evening_return(self):
        session = self.seed()
        evening = self.chat(session['id'], 'Хочу вернуться вечером')
        self.assertTrue(all(o['transport']['returnFlight']['arrival_time'] >= '18:00' for o in evening['updatedOptions'].values()))
        result = self.chat(session['id'], 'Хочу вернуться обратно до 13.00')
        self.assertFalse(result.get('changeRejected'))
        self.assertTrue(all(o['transport']['returnFlight']['arrival_time'] <= '13:00' for o in result['updatedOptions'].values()))
        self.assertNotIn('return_arrival_after', result['chatState'])

    def test_before_lunch_return_selects_an_available_early_flight(self):
        session = self.seed()
        route = copy.deepcopy(FlightService._find_route('Сочи'))
        route['return_departures'] = ['18:30', '06:00']
        with patch.object(FlightService, '_find_route', return_value=route):
            result = self.chat(session['id'], 'Хочу вернуться обратно до обеда')
        self.assertFalse(result.get('changeRejected'))
        for option in result['updatedOptions'].values():
            self.assertEqual(option['transport']['returnFlight']['departure_time'], '06:00')
            self.assertLessEqual(option['transport']['returnFlight']['arrival_time'], '11:59')

    def test_before_lunch_return_can_reject_without_claiming_success(self):
        session = self.seed()
        before = copy.deepcopy(session)
        result = self.chat(session['id'], 'хочу вернуться обратно до обеда')
        self.assertTrue(result['changeRejected'])
        self.assertIn('Нет подходящих билетов', result['reply'])
        self.assertEqual(result['updatedOptions'], before['options'])

    def test_outbound_departure_arrival_and_return_are_separate_clauses(self):
        result = extract_flight_preferences('Вылет после 9, прилёт до 18.30, вернуться до 12.30')
        self.assertEqual(result['departure_after'], '09:00')
        self.assertEqual(result['arrival_before'], '18:30')
        self.assertEqual(result['return_arrival_before'], '12:30')
        self.assertNotIn('departure_before', result)

    def test_real_overnight_arrival_does_not_satisfy_same_day_deadline(self):
        overnight = schedules.leg('2026-11-15T20:00:00+03:00', '2026-11-16T00:30:00+03:00')
        with patch.dict(os.environ, {'OFFLINE_MODE': '0', 'YANDEX_RASP_ENABLED': 'true', 'YANDEX_RASP_API_KEYS': 'test-key'}), \
                patch.object(FlightService, '_fetch_yandex_segments', return_value=[overnight]):
            result = FlightService.search(destination='Сочи', date='2026-11-15', arrival_before='12:30')
        self.assertEqual(result['flights'], [])
