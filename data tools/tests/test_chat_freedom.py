import copy
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from tests import test_chat_and_database as fixtures
from src.services import database as db
from src.services.agent_orchestrator import build_trip_response
from src.services.chat_language import normalize_chat_text
from src.services.openrouter_agent import _build_plan
from src.services.departure_cities import CITIES, normalize_origin


class ChatFreedomTests(unittest.TestCase):
    def setUp(self):
        fixtures.ChatDatabaseTests.setUp(self)
        class Calendar(date):
            @classmethod
            def today(cls):
                return cls(2026, 10, 29)
        self.calendar = patch('src.services.chat_intent.date', Calendar)
        self.calendar.start()

    def tearDown(self):
        self.calendar.stop()
        fixtures.ChatDatabaseTests.tearDown(self)

    def chat(self, sid, message, **values):
        response = self.client.post('/api/chat', json={'session_id': sid, 'message': message, **values})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def seed(self, sid='free-chat', destination='Сочи', adults=2, ages=None):
        built, state = build_trip_response('', {}, intent={'destination': destination, 'budget_rub': 500000,
            'adults': adults, 'children_ages': ages or [], 'checkin_date': '2026-11-01', 'nights': 4})
        self.assertTrue(built['updatedOptions'])
        session = db.load_session(sid)
        session.update(state=state, options=built['updatedOptions'])
        db.save_session(session)
        return session

    def test_common_city_aliases_are_supported(self):
        for alias, city in {'спб':'Санкт-Петербург','санкт петербург':'Санкт-Петербург',
            'мск':'Москва','екб':'Екатеринбург','нск':'Новосибирск','нн':'Нижний Новгород',
            'минводы':'Минеральные Воды','крд':'Краснодар','владик':'Владивосток'}.items():
            self.assertEqual(normalize_origin(alias), city)
            self.assertIn(city, CITIES)

    def test_shorthand_family_budget_and_history_are_preserved(self):
        raw = 'пж собери Сочи из мск, 2взр + реб8, 4н, до 300 штук'
        # Explicit build tool demonstrates normalisation in the existing model call.
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-key'}), \
            patch('src.services.openrouter_agent._completion', return_value=fixtures.tool_message('build_trip_plan', {'destination':'Сочи'})):
            result = self.chat('shorthand-history', raw)
        self.assertEqual(result['chatState']['budget_rub'], 300000)
        self.assertEqual(result['chatState']['adults'], 2)
        self.assertEqual(result['chatState']['children_ages'], [8])
        self.assertEqual(result['chatState']['nights'], 4)
        self.assertEqual(db.load_session('shorthand-history')['messages'][-2]['content'], raw)

    def test_slang_hundred_thousand_is_a_hard_limit(self):
        normalized = normalize_chat_text('бюджет до сотки')
        result = self.chat('slang-budget', normalized)
        self.assertEqual(result['budget_rub'], 100000)

    def test_total_four_includes_child_and_keeps_origin_and_date_during_clarification(self):
        message = 'я еду учетвером, я брат взрослый и жена его, также мой сын, едем из спб, 1 ноября, хотим в сочи'
        for mode in ('demo', 'model'):
            with self.subTest(mode=mode), patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-key' if mode == 'model' else ''}), \
                patch('src.services.openrouter_agent._completion', side_effect=AssertionError('Clarification needs no model')):
                sid = 'total-four-' + mode
                first = self.chat(sid, message)
                self.assertIn('Сколько лет', first['reply'])
                result = self.chat(sid, '8')
                self.assertEqual(result['chatState']['passengers'], 4)
                self.assertEqual(result['chatState']['adults'], 3)
                self.assertEqual(result['chatState']['children_ages'], [8])
                self.assertEqual(result['chatState']['origin'], 'Санкт-Петербург')
                self.assertEqual(result['chatState']['checkin_date'], '2026-11-01')

    def test_explicit_adults_are_not_confused_with_total_group_size(self):
        result = self.chat('four-adults-child', 'Хочу Сочи, 4 взрослых и ребёнок 8 лет, максимум 500000 рублей')
        self.assertEqual(result['chatState']['adults'], 4)
        self.assertEqual(result['chatState']['passengers'], 5)

    def test_ordinal_dates_and_slang_budget(self):
        result = self.chat('ordinal-date', 'Хочу в Сочи из Екб с первого по четвёртое ноября, 2 взрослых, бюджет 300 штук')
        self.assertEqual(result['chatState']['origin'], 'Екатеринбург')
        self.assertEqual(result['chatState']['checkin_date'], '2026-11-01')
        self.assertEqual(result['chatState']['checkout_date'], '2026-11-04')
        self.assertEqual(result['chatState']['nights'], 3)
        self.assertEqual(result['chatState']['budget_rub'], 300000)

    def test_model_can_interpret_colloquial_preferences_in_one_call(self):
        session = self.seed()
        message = 'А можно что-нибудь без заморозки денег?'
        answer = fixtures.tool_message('build_trip_plan', {'no_deposit':True, 'request_quote':message,
            'interpretation':'Подобрать отели без возвратного депозита.'})
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-key'}), patch('src.services.openrouter_agent._completion', return_value=answer) as model:
            result = self.chat(session['id'], message)
        self.assertEqual(model.call_count, 1)
        self.assertTrue(result['chatState']['no_deposit'])
        self.assertTrue(all(o['fairPriceBreakdown']['refundable_deposit_rub'] == 0 for o in result['updatedOptions'].values()))
        self.assertIn('Понял пожелание', result['reply'])

    def test_unexplained_model_guess_is_corrected_before_any_change(self):
        for index, (message, values) in enumerate((('А можно без заморозки денег?', {'no_deposit':True}),
                ('Подбери что-нибудь без заморозки денег', {'no_deposit':True}),
                ('Хачу без адских падъёмов?', {'departure_after':'10:00'}))):
            session = self.seed('quote-retry-' + str(index))
            answers = [fixtures.tool_message('build_trip_plan', values),
                fixtures.tool_message('build_trip_plan', {**values, 'request_quote':message, 'interpretation':'Применить указанное пожелание.'}, 'corrected')]
            with patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-key'}), patch('src.services.openrouter_agent._completion', side_effect=answers) as model:
                result = self.chat(session['id'], message)
            self.assertEqual(model.call_count, 2)
            self.assertEqual(result['budget_rub'], 500000)
            if 'no_deposit' in values:
                self.assertTrue(result['chatState']['no_deposit'])
            else:
                self.assertTrue(all(o['transport']['depTime']=='12:45' for o in result['updatedOptions'].values()))

    def test_semantic_hotel_search_keeps_family_instead_of_search_defaults(self):
        session = self.seed('search-family', adults=3, ages=[8])
        message = 'А можно без заморозки денег?'
        answers = [fixtures.tool_message('search_hotels', {'destination':'Сочи','no_deposit':True}),
            {'role':'assistant','content':'Нашёл отели без депозита.'}]
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-key'}), patch('src.services.openrouter_agent._completion', side_effect=answers):
            result = self.chat(session['id'], message)
        self.assertTrue(result['chatState']['no_deposit'])
        self.assertEqual(result['chatState']['adults'], 3)
        self.assertEqual(result['chatState']['children_ages'], [8])
        self.assertEqual(result['chatState']['passengers'], 4)

    def test_model_can_interpret_nonstandard_flight_wish_but_only_select_existing_flights(self):
        session = self.seed()
        message = 'Хочу без адских подъёмов'
        answer = fixtures.tool_message('build_trip_plan', {'departure_after':'10:00', 'request_quote':message,
            'interpretation':'Вылет не раньше 10:00.'})
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-key'}), patch('src.services.openrouter_agent._completion', return_value=answer):
            result = self.chat(session['id'], message)
        self.assertTrue(all(o['transport']['depTime']=='12:45' for o in result['updatedOptions'].values()))
        self.assertEqual(result['budget_rub'], 500000)

    def test_model_can_understand_typos_without_a_template_match(self):
        session = self.seed('typo-model')
        message = 'Хачу без адских падъёмов?'
        answer = fixtures.tool_message('build_trip_plan', {'departure_after':'10:00',
            'request_quote':message, 'interpretation':'Вылет после 10:00.'})
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-key'}), patch('src.services.openrouter_agent._completion', return_value=answer):
            result = self.chat(session['id'], message)
        self.assertTrue(all(o['transport']['depTime']=='12:45' for o in result['updatedOptions'].values()))
        self.assertEqual(result['budget_rub'], 500000)

    def test_interpretation_cannot_increase_budget_or_invent_child_ages(self):
        session = self.seed()
        message = 'Хочу что-нибудь потише'
        built = _build_plan(session, message, {'budget_rub':900000,'request_quote':message,'vibe_query':'тихий отель'}, None)
        self.assertTrue(built['trip_assembled'])
        self.assertEqual(session['state']['budget_rub'], 500000)
        with self.assertRaisesRegex(ValueError, 'Возраст нельзя угадывать'):
            _build_plan(session, message, {'children_ages':[7], 'request_quote':message}, None)

    def test_discussion_cannot_be_turned_into_edit_with_a_quote(self):
        session = self.seed()
        before = copy.deepcopy(session)
        with self.assertRaises(ValueError):
            _build_plan(session, 'Расскажи про отель, ничего не меняй',
                {'no_deposit':True, 'request_quote':'Расскажи про отель'}, None)
        with self.assertRaises(ValueError):
            _build_plan(session, 'Привет!', {'destination':'Дубай', 'request_quote':'Привет!'}, None)
        self.assertEqual(session, before)

    def test_failed_semantic_edit_preserves_actual_plan(self):
        session = self.seed()
        before = copy.deepcopy(session)
        result = _build_plan(session, 'Хочу вообще без подъёмов',
            {'departure_after':'23:59','request_quote':'Хочу вообще без подъёмов'}, None)
        self.assertTrue(result['changeRejected'])
        self.assertEqual(session, before)

    def test_plain_model_reply_cannot_claim_real_changes(self):
        session = self.seed()
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-key'}), patch('src.services.openrouter_agent._completion', return_value={'role':'assistant','content':'Подключил вам услугу.'}):
            result = self.chat(session['id'], 'Хочу услугу получше')
        self.assertIn('ещё не применено', result['reply'])
        self.assertEqual(result['updatedOptions'], session['options'])

    def test_early_checkin_changes_timeline_receipt_and_can_be_removed(self):
        session = self.seed('early-service', destination='Калининград')
        original = session['options']['A']
        result = self.chat(session['id'], 'оформи ранний заезд')
        self.assertFalse(result.get('changeRejected'))
        option = result['updatedOptions']['A']
        self.assertGreater(option['fairPriceBreakdown']['early_checkin_rub'], 0)
        checkin = next(step for step in option['timeline'] if step['tag']=='Отель')
        self.assertLess(checkin['time'][-5:], '14:00')
        booked = self.client.post('/api/bookings', json={'trip':option}).json()
        self.assertTrue(any('ранний' in line['title'].lower() for line in booked['receipt']['line_items']))
        removed = self.chat(session['id'], 'убери ранний заезд')
        self.assertEqual(removed['updatedOptions']['A']['fairPriceBreakdown']['early_checkin_rub'], 0)
        self.assertEqual(removed['updatedOptions']['A']['fairPriceBreakdown']['grand_total_rub'], original['fairPriceBreakdown']['grand_total_rub'])

    def test_early_checkin_does_not_exceed_saved_budget(self):
        session = self.seed('early-budget', destination='Калининград')
        total = session['options']['A']['fairPriceBreakdown']
        session['state']['budget_rub'] = total['grand_total_rub'] + total['refundable_deposit_rub']
        db.save_session(session)
        result = self.chat(session['id'], 'добавь ранний заезд')
        self.assertTrue(result['changeRejected'])
        self.assertEqual(result['updatedOptions'], session['options'])

    def test_voucher_timestamp_is_explicit_moscow_time(self):
        option = self.seed()['options']['A']
        booked = self.client.post('/api/bookings', json={'trip':option}).json()
        issued = datetime.fromisoformat(booked['issued_at_iso'])
        self.assertEqual(issued.utcoffset(), timedelta(hours=3))
        self.assertLess(abs((issued-datetime.now(timezone.utc)).total_seconds()), 10)
        self.assertEqual(booked['issued_at'], issued.strftime('%d.%m.%Y %H:%M (МСК)'))

    def test_short_later_request_uses_recent_flight_context_and_keeps_raw_history(self):
        session = self.seed('later-context')
        self.chat(session['id'], 'Вылет в 07:30')
        result = self.chat(session['id'], 'а попозже?')
        self.assertTrue(all(o['transport']['depTime'] > '07:30' for o in result['updatedOptions'].values()))
        self.assertEqual(db.load_session(session['id'])['messages'][-2]['content'], 'а попозже?')
        later = self.chat(session['id'], 'ещё позже?')
        self.assertTrue(later['changeRejected'])
        self.assertEqual(later['updatedOptions'], result['updatedOptions'])

    def test_unavailable_early_checkin_reports_specific_reason_without_changing_cards(self):
        session = self.seed('unavailable-early', destination='Калининград')
        from sqlalchemy import update
        hotel_id = session['options']['A']['hotel']['id']
        hotel = next(h for h in db.load_catalog('hotels') if h['id'] == hotel_id)
        hotel['early_checkin_available'] = False
        with db.get_engine().begin() as conn:
            conn.execute(update(db.hotels).where(db.hotels.c.id == hotel_id).values(data=hotel))
        result = self.chat(session['id'], 'оформи ранний заезд')
        self.assertTrue(result['changeRejected'])
        self.assertIn('ранним заездом', result['reply'])
        self.assertEqual(result['updatedOptions'], session['options'])

    def test_no_match_reason_and_followup_explain_transfer_capacity(self):
        session = self.seed('capacity-explanation')
        rejected = self.chat(session['id'], 'Измени гостей', action_id='change_guests', adults=10, children_ages=[])
        self.assertTrue(rejected['changeRejected'])
        self.assertIn('Не хватает мест в трансфере', rejected['reply'])
        reply = self.chat(session['id'], 'А в каком направлении нужно изменить вводные?')
        self.assertIn('вместимость', reply['reply'])
        self.assertIn('уменьшить состав', reply['reply'])
        self.assertEqual(reply['updatedOptions'], session['options'])

    def test_failure_metadata_is_not_sent_as_invalid_chat_message_fields(self):
        session = self.seed('failure-context')
        self.chat(session['id'], 'Хочу прилететь до 01.00')
        def answer(messages, *args, **kwargs):
            self.assertTrue(all(set(m) <= {'role','content','tool_calls','tool_call_id','reasoning_details'} for m in messages))
            self.assertIn('last_search_failure', messages[0]['content'])
            return {'role':'assistant','content':'В поездке можно обсудить прогулки и отдых.'}
        with patch.dict(os.environ, {'OPENROUTER_API_KEY':'test-key'}), patch('src.services.openrouter_agent._completion', side_effect=answer):
            self.chat(session['id'], 'Поговорим о прогулках')
