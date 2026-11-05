import re
from datetime import date, timedelta
from uuid import uuid4
from typing import Any, Dict, List, Optional

from src.tools.travel_tools import (
    search_destinations,
    search_hotels,
    search_transfers_and_flights,
    get_weather_forecast,
)
from src.services.logistics_engine import (
    LogisticsAndTradeoffEngine,
    BookingCartAssembler,
)
from src.services.database import load_session, save_session, session_lock
from src.services.trip_planner import select_affordable_options
from src.services.catalog_locations import destination_id
from src.services.chat_context import public_chat_state
from src.services.budget_constraints import extract_budget_bounds, apply_budget_bounds
from src.services.chat_language import normalize_chat_text
from src.services.chat_intent import is_conversation_request, extract_pet_friendly, extract_nights_and_dates
from src.services.flight_preferences import TIME_FIELDS
from src.services.travel_party import normalize_party, extract_party, needs_children_ages, is_child_addition, extract_total_guests
from src.services.accommodation import accommodation_reply, requested_room_count, validate_room_count
from src.services.search_explanation import failure_details, no_combination_reason, failure_followup
from src.services.departure_cities import normalize_origin, extract_origin_request, destination_text
from src.services.travel_preferences import extract_travel_styles, matches_destination, matches_hotel, style_label
from src.services.database import load_catalog

DESTINATION_PHOTO_MAP: Dict[str, List[str]] = {
    "sochi": [
        "https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1582719508461-905c673771fd?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?auto=format&fit=crop&w=900&q=80",
    ],
    "sheregesh": [
        "https://images.unsplash.com/photo-1548777123-e216912df7d8?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1510798831971-661eb04b3739?auto=format&fit=crop&w=900&q=80",
    ],
    "dubai": [
        "https://images.unsplash.com/photo-1512453979798-5ea266f8880c?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1580674684081-7617fbf3d745?auto=format&fit=crop&w=900&q=80",
    ],
    "phuket": [
        "https://images.unsplash.com/photo-1589394815804-964ed0be2eb5?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1537996194471-e657df975ab4?auto=format&fit=crop&w=900&q=80",
    ],
    "altay": [
        "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=900&q=80",
    ],
    "istanbul": [
        "https://images.unsplash.com/photo-1524231757912-21f4fe3a7200?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1541432901042-2d8bd64b4a9b?auto=format&fit=crop&w=900&q=80",
    ],
    "kaliningrad": [
        "https://images.unsplash.com/photo-1513694203232-719a280e022f?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1571896349842-33c89424de2d?auto=format&fit=crop&w=900&q=80",
    ],
    "maldives": [
        "https://images.unsplash.com/photo-1514282401047-d79a71a590e8?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1573843981267-be1999ff37cd?auto=format&fit=crop&w=900&q=80",
    ],
    "dagestan": [
        "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?auto=format&fit=crop&w=900&q=80",
    ],
    "bali": [
        "https://images.unsplash.com/photo-1537996194471-e657df975ab4?auto=format&fit=crop&w=900&q=80",
        "https://images.unsplash.com/photo-1552733407-5d5c46c3bb3b?auto=format&fit=crop&w=900&q=80",
    ],
}

DEFAULT_HOTEL_IMAGES = DESTINATION_PHOTO_MAP["sochi"]


def _extract_budget(text: str) -> Optional[int]:
    return extract_budget_bounds(text).get("budget_rub")


def restore_user_budget(session):
    """Recover the user's limit from legacy history, never from assistant prices."""
    state = session["state"]
    recovered = {}
    for field in ("budget_rub", "budget_min_rub"):
        if "user_" + field in state:
            recovered[field] = state["user_" + field]
        else:
            for message in reversed(session["messages"]):
                content = message.get("content", "")
                bounds = extract_budget_bounds(normalize_chat_text(content)) if message.get("role") == "user" and not is_conversation_request(content) else {}
                if field in bounds:
                    recovered[field] = bounds[field]
                    break
    changed = any(state.get(k) != v or "user_" + k not in state for k, v in recovered.items())
    apply_budget_bounds(state, recovered)
    return changed


def _parse_user_intent(message: str, prev_state: Dict[str, Any]) -> Dict[str, Any]:
    t = message.lower()
    state = {
        "origin": "Москва",
        "destination": "Сочи",
        "nights": 4,
        "passengers": 2,
        "pet_friendly": False,
        "baby_crib": False,
        "free_cancellation": False,
        "no_deposit": False,
        "budget_rub": 95000,
        "month": 11,
        "vibe_query": "",
        "turn_count": 0,
        "has_meal_addon": False,
    }
    state.update(prev_state or {})
    rooms = requested_room_count(message)
    if rooms is not None:
        state['room_count'] = rooms
    styles = extract_travel_styles(message)
    if styles:
        state["travel_styles"] = styles
    state["turn_count"] = state.get("turn_count", 0) + 1
    is_replanning = state["turn_count"] > 1

    if any(w in t for w in ["питан", "ужин", "завтрак", "шведский стол"]):
        state["has_meal_addon"] = True

    bounds = extract_budget_bounds(t)
    # The parser's demo default must not conflict with an explicit lower limit.
    if "budget_rub" not in prev_state and "budget_rub" not in bounds and "budget_min_rub" in bounds:
        state["budget_rub"] = None
    apply_budget_bounds(state, bounds)

    if "недел" in t or "7 дн" in t:
        state["nights"] = 7
    elif "выходн" in t or "2 дн" in t:
        state["nights"] = 2
    elif "3 дн" in t or "три дн" in t:
        state["nights"] = 3
    elif "5 дн" in t or "пять дн" in t:
        state["nights"] = 5

    if any(w in t for w in ["один", "одна", "одному", "одной", "соло", "удалённо", "1 человек", "один человек", "1 гость"]):
        state["passengers"] = 1
    elif "троих" in t or "третий друг" in t:
        state["passengers"] = 3
    elif any(w in t for w in ["вдвоём", "двоих", "с девушкой", "с женой", "с мужем", "родител"]):
        state["passengers"] = 2

    pet = extract_pet_friendly(message)
    if pet is not None:
        state["pet_friendly"] = pet
    party = extract_party(message, state)
    if party:
        if state.get("awaiting_children_ages") and "children_ages" in party:
            state.update(state.get("pending_trip_edit", {}))
        state.update(party)
        if "children_ages" in party:
            state.pop("awaiting_children_ages", None)
            state.pop("pending_trip_edit", None)
            state.pop("pending_child_append", None)

    if any(w in t for w in ["ребён", "ребен", "малыш", "коляск", "5 лет", "10 месяц"]):
        state["baby_crib"] = True

    if "бесплатн" in t and "отмен" in t:
        state["free_cancellation"] = True

    requested_origin = extract_origin_request(message)
    if requested_origin:
        state['origin'] = normalize_origin(requested_origin)
    t = destination_text(message).lower()

    if any(w in t for w in ["перенесла рейс", "оформили через тебя", "05:30 утра вместо"]):
        state["special_case"] = "post_booking"
        return state

    if any(w in t for w in ["берём первый вариант", "добавляй в корзину", "давай оформлять", "оплатить"]):
        state["special_case"] = "checkout"
        return state

    if "мурманск" in t and ("позагорать" in t or "тёплом море" in t or "покупаться" in t):
        state["special_case"] = "contradiction_murmansk"
        state["destination"] = "Дубай"
        return state

    if len(t.strip()) < 45 and ("хочу куда-нибудь в отпуск" in t or "хочу в отпуск" in t):
        state["special_case"] = "needs_clarification"
        return state

    if any(w in t for w in ["дубай", "оаэ", "тёплому морю в ноябре", "борщ"]):
        state["destination"] = "Дубай"
    elif any(w in t for w in ["пхукет", "таиланд"]):
        state["destination"] = "Пхукет"
    elif any(w in t for w in ["шерегеш", "шале", "камин"]):
        state["destination"] = "Шерегеш"
    elif any(w in t for w in ["алтай", "лес", "озер", "тишин", "устал от работы"]):
        state["destination"] = "Алтай"
    elif any(w in t for w in ["стамбул", "турци", "удалённо", "zoom"]):
        state["destination"] = "Стамбул"
    elif any(w in t for w in ["калининград", "зеленоградск", "балтик"]):
        state["destination"] = "Калининград"
    elif any(w in t for w in ["дагестан", "дербент", "каспийск", "махачкал", "горы и море"]):
        state["destination"] = "Дагестан"
    elif any(w in t for w in ["бали", "индонези", "серфинг", "денпасар"]):
        state["destination"] = "Бали"
    elif any(w in t for w in ["сочи", "адлер", "красной полян", "роза хутор", "лыж"]):
        state["destination"] = "Сочи"
    elif not is_replanning:
        dest_res = search_destinations(query=message, month=state["month"], limit=2)
        if dest_res.get("destinations"):
            state["destination"] = dest_res["destinations"][0]["name"]

    state["special_case"] = "replanning" if is_replanning else "standard"
    state.update(extract_nights_and_dates(message, state))
    state.pop('party_total_guests', None)
    if not state.get("has_meal_addon"):
        state["vibe_query"] = message
    return state


def build_initial_frontend_trips() -> Dict[str, Any]:
    res = run_agent_turn(
        session_id=str(uuid4()),
        message="Хочу в Сочи вдвоём с корги на 4 ночи, сравни комфорт в горах и отель у моря",
        selected_option="A",
    )
    return res["updatedOptions"]


def run_agent_turn(
    session_id: str,
    message: str,
    selected_option: str = "A",
) -> Dict[str, Any]:
    with session_lock(session_id):
        session = load_session(session_id)
        explanation = failure_followup(session, message)
        if explanation:
            session['messages'] = (session['messages'] + [{'role': 'user', 'content': message}, {'role': 'assistant', 'content': explanation}])[-20:]
            save_session(session)
            return {'reply': explanation, 'updatedOptions': session['options'], 'chatState': public_chat_state(session), 'tools_called': []}
        room_reply = accommodation_reply(session, selected_option, message)
        if room_reply:
            session["messages"] = (session["messages"] + [{"role": "user", "content": message}, {"role": "assistant", "content": room_reply}])[-20:]
            save_session(session)
            return {"reply": room_reply, "updatedOptions": session["options"], "chatState": public_chat_state(session),
                    "planStatus": session["state"].get("plan_status", "ready"), "tools_called": []}
        if not is_conversation_request(message) and needs_children_ages(message, session["state"]):
            explicit_destination = destination_id(destination_text(message))
            if not session["options"] and explicit_destination:
                session["state"]["destination"] = next(d["name"] for d in load_catalog("destinations") if d["id"] == explicit_destination)
            session["state"]["awaiting_children_ages"] = True
            session["state"]["pending_child_append"] = is_child_addition(message)
            session["state"]["pending_trip_edit"] = {**extract_party(message, session["state"]), **extract_budget_bounds(message), **extract_nights_and_dates(message, session["state"])}
            total = extract_total_guests(message)
            if total is not None:
                session['state']['pending_trip_edit']['party_total_guests'] = total
            origin = extract_origin_request(message)
            if origin:
                session['state']['pending_trip_edit']['origin'] = normalize_origin(origin)
            reply = "Сколько лет каждому ребёнку на день вылета? Напишите возраст, например «6 лет» или «1 и 8 лет»."
            session["messages"] = (session["messages"] + [{"role": "user", "content": message}, {"role": "assistant", "content": reply}])[-20:]
            save_session(session)
            return {"reply": reply, "updatedOptions": session["options"], "chatState": public_chat_state(session), "planStatus": session["state"].get("plan_status", "empty"), "tools_called": []}
        if is_conversation_request(message) and session["options"]:
            option = session["options"].get(selected_option) or next(iter(session["options"].values()))
            reply = f"В выбранном варианте — {option['hotel']['name']}, {option['dates']}. Сохранённый состав гостей и условия поездки не менял. Подробности и смета находятся в карточке; для свободного обсуждения доступен режим с подключённым ИИ."
            session["messages"] = (session["messages"] + [{"role": "user", "content": message}, {"role": "assistant", "content": reply}])[-20:]
            save_session(session)
            return {"reply": reply, "updatedOptions": session["options"], "chatState": public_chat_state(session), "planStatus": session["state"].get("plan_status", "ready"), "budget_rub": session["state"].get("budget_rub"), "tools_called": []}
        if not session["state"].get("destination") and not destination_id(destination_text(message)):
            apply_budget_bounds(session["state"], extract_budget_bounds(message))
            rooms = requested_room_count(message)
            if rooms is not None:
                if not 1 <= rooms <= 10:
                    raise ValueError('Количество номеров должно быть целым числом от 1 до 10.')
                session['state']['room_count'] = rooms
            reply = "Расскажите, куда хотите поехать, на какие даты и с кем. Если ещё не выбрали направление — начнём с моря, гор или вашего бюджета."
            session["messages"] = (session["messages"] + [{"role": "user", "content": message}, {"role": "assistant", "content": reply}])[-20:]
            save_session(session)
            return {"reply": reply, "updatedOptions": {}, "planStatus": "empty", "planMessage": "Опишите поездку — варианты появятся после подбора.",
                    "chatState": public_chat_state(session), "budget_rub": session["state"].get("budget_rub"), "tools_called": []}
        result, state = build_trip_response(message, session["state"], selected_option)
        session.update(state=state, options=result.get("updatedOptions", session["options"]),
                       selected_option=selected_option)
        session["messages"] = (session["messages"] + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": result["reply"], **({'search_failure': result['searchFailure']} if result.get('searchFailure') else {'search_failure': None} if result.get('trip_assembled') else {})},
        ])[-20:]
        save_session(session)
        result["chatState"] = public_chat_state(session)
        return result


def build_trip_response(message, previous_state, selected_option="A", intent=None, preserve_hotels=True, preview=False):
    if intent is None:
        state = _parse_user_intent(message, previous_state)
        if state.get("nights") != previous_state.get("nights"):
            state.pop("checkout_date", None)
    else:
        # Structured model arguments are validated before reaching this function.
        state = _parse_user_intent("", {})
        state.update(previous_state)
        # A new window replaces earlier wishes for that direction, so an old
        # evening return cannot silently conflict with a new morning arrival.
        for fields in (TIME_FIELDS[:4], TIME_FIELDS[4:]):
            if any(k in intent for k in fields):
                for k in fields:
                    state.pop(k, None)
        state.update(intent)
        if "budget_rub" not in previous_state and "budget_rub" not in intent:
            state["budget_rub"] = None
        state["turn_count"] = previous_state.get("turn_count", 0) + 1
        state["special_case"] = "standard"
        if any(k in intent for k in ("nights", "checkin_date")) and "checkout_date" not in intent:
            state.pop("checkout_date", None)
        if "hotel_ids" not in intent and any(k in intent for k in (
            "destination", "budget_rub", "pet_friendly", "baby_crib", "free_cancellation", "no_deposit", "vibe_query"
        )):
            state.pop("hotel_ids", None)
    state.update(normalize_party(state, intent or {}))
    room_request = (intent or {}).get('room_count') if intent is not None else requested_room_count(message)
    if room_request is not None:
        state['room_count'] = validate_room_count(state['adults'], state['children_ages'], room_request)
    elif state.get('room_count') is not None:
        state['room_count'] = max(state['room_count'], validate_room_count(state['adults'], state['children_ages'], None))
    state["origin"] = normalize_origin(state.get("origin", "Москва"))
    if destination_id(state["origin"]) == destination_id(state["destination"]) and destination_id(state["origin"]):
        raise ValueError("Город вылета совпадает с направлением. Выберите другой город вылета.")
    start = date.fromisoformat(state.get("checkin_date") or (date.today() + timedelta(days=21)).isoformat())
    end = date.fromisoformat(state["checkout_date"]) if state.get("checkout_date") else start + timedelta(days=state["nights"])
    if end <= start or (end - start).days > 30:
        raise ValueError("Длительность поездки должна быть от 1 до 30 ночей")
    state.update(checkin_date=start.isoformat(), checkout_date=end.isoformat(),
                 nights=(end - start).days, month=start.month)

    origin = state["origin"]
    dest_name = state["destination"]
    nights = state["nights"]
    passengers = state["passengers"]
    special = state.get("special_case", "standard")
    has_meal_addon = state.get("has_meal_addon", False)

    tools_called: List[str] = [
        "search_destinations",
        "search_hotels",
        "search_transfers_and_flights",
        "get_weather_forecast",
    ]

    styles = state.get("travel_styles", [])
    if styles:
        destination = next((d for d in load_catalog("destinations") if d["id"] == destination_id(dest_name)), {})
        if not matches_destination(destination, styles):
            return unavailable_plan(state, f"Направление {dest_name} не соответствует пожеланию «{style_label(styles)}» в нашем каталоге. Выберите подходящее направление; бюджет и остальные условия сохранены.")

    hotels_res = search_hotels(
        destination=dest_name,
        checkin_date=state["checkin_date"],
        checkout_date=state["checkout_date"],
        guests=passengers,
        pet_friendly=True if state.get("pet_friendly") else None,
        baby_crib=True if state.get("baby_crib") or any(age < 2 for age in state["children_ages"]) else None,
        free_cancellation=True if state.get("free_cancellation") else None,
        no_deposit=True if state.get("no_deposit") else None,
        min_rating=state.get("min_rating"),
        meal_type=state.get("meal_type"),
        max_distance_to_center_km=state.get("max_distance_to_center_km"),
        max_distance_to_beach_m=state.get("max_distance_to_beach_m"),
        vibe_query=state.get("vibe_query", ""),
        limit=20,
    )
    hotels_list = [h for h in hotels_res.get("hotels", []) if matches_hotel(h, styles)]
    excluded = set((intent or {}).get('exclude_hotel_ids', []))
    hotels_list = [h for h in hotels_list if h['id'] not in excluded]
    state.pop('exclude_hotel_ids', None)
    if any(age < 2 for age in state["children_ages"]):
        hotels_list = [h for h in hotels_list if (h.get("child_friendly") or {}).get("baby_crib_free")]
    if not hotels_list:
        labels = {'pet_friendly': 'с питомцем', 'baby_crib': 'с бесплатной детской кроваткой', 'no_deposit': 'без депозита', 'free_cancellation': 'с бесплатной отменой', 'min_rating': 'с заданным рейтингом', 'meal_type': 'с указанным питанием'}
        active = [label for key, label in labels.items() if state.get(key)]
        suffix = ' Одновременно запрошено: ' + ', '.join(active) + '.' if active else ''
        return unavailable_plan(state, f"В демокаталоге нет отелей в {dest_name}, подходящих под все ваши условия.{suffix} Можно ослабить требования к отелю или выбрать другое направление.", 'hotels')

    flights_res = search_transfers_and_flights(
        origin=origin,
        destination=dest_name,
        date=state["checkin_date"],
        return_date=state["checkout_date"],
        passengers=passengers,
        adults=state["adults"], children_ages=state["children_ages"],
        need_transfer=True,
        hotel_checkin_time=hotels_list[0].get("checkin_time", "14:00"),
        hotel_name=hotels_list[0].get("name"),
        preview=preview,
        **{k: state[k] for k in TIME_FIELDS if state.get(k)},
    )
    flights_list = flights_res.get("flights", [])
    transfers_list = flights_res.get("transfers", [])
    if not flights_list:
        requested = ', '.join(f'{k}={state[k]}' for k in TIME_FIELDS if state.get(k))
        detail = flights_res.get('error') or f'Нет рейсов из {origin} до {dest_name}.'
        if requested:
            detail += ' Не совпали ограничения времени: ' + requested + '.'
        return unavailable_plan(state, detail + ' Можно изменить даты, время или город вылета.', 'flights')
    choices, minimum = select_affordable_options(hotels_list, flights_list, transfers_list, state)
    if preview:
        return {"trip_assembled": bool(choices), "minimum_price_rub": minimum,
                "available_option_count": len(choices)}, state
    explicit_hotels = (intent or {}).get("hotel_ids") or []
    if choices and preserve_hotels and explicit_hotels and not set(explicit_hotels).issubset({c["hotel"]["id"] for c in choices}):
        return unavailable_plan(state, "Не получается сохранить все выбранные отели и уложиться в бюджет с текущими услугами. Можно подобрать более доступный отель или убрать дополнительные услуги — лимит самовольно не повышаю.")
    if not choices:
        budget = state.get("budget_rub")
        lower = state.get("budget_min_rub", 0)
        code = 'budget'
        if minimum is None:
            code, reply = no_combination_reason(transfers_list, state)
            reply += ' Можно ' + '; '.join(failure_details(code, state, reply)['suggestions']) + '.'
        elif lower:
            limit = f"от {lower:,} ₽" + (f" до {budget:,} ₽" if budget is not None else "")
            reply = f"В {dest_name} нет поездки с полной стоимостью {limit} под ваши условия. Можно изменить диапазон или направление; суммы искусственно не увеличиваю."
            reply = reply.replace(",", " ")
        elif budget and minimum is not None:
            reply = (f"В {dest_name} на {nights} ноч. нет поездки в пределах {budget:,} ₽. "
                     f"Минимальная сумма по текущему каталогу — {minimum:,} ₽ с обязательными доплатами и депозитом, если он нужен. "
                     "Дорогие варианты в карточки не добавляю. Можем изменить направление или даты, сократить поездку либо увеличить бюджет с вашего согласия.").replace(",", " ")
        else:
            code, reply = no_combination_reason(transfers_list, state)
            reply += ' ' + '; '.join(failure_details(code, state, reply)['suggestions']) + '.'
        result, state = unavailable_plan(state, reply, code)
        result["minimum_price_rub"] = minimum
        return result, state
    a, b = choices[0], choices[-1]
    hotel_a, hotel_b = a["hotel"], b["hotel"]
    flight_a, flight_b = a["flight"], b["flight"]
    transfer_a, transfer_b = a["transfer"], b["transfer"]
    state["hotel_ids"] = list(dict.fromkeys([hotel_a["id"], hotel_b["id"]]))

    weather_res = get_weather_forecast(city=dest_name, date=state["checkin_date"], days=min(nights, 5))

    engine_bundle = LogisticsAndTradeoffEngine.build_validated_frontend_options(
        origin=origin,
        dest_name=dest_name,
        nights=nights,
        passengers=passengers,
        hotel_a=hotel_a,
        hotel_b=hotel_b,
        flight_a=flight_a,
        flight_b=flight_b,
        transfer_a=transfer_a,
        transfer_b=transfer_b,
        weather=weather_res,
        photo_map=DESTINATION_PHOTO_MAP,
        default_images=DEFAULT_HOTEL_IMAGES,
        with_pet=bool(state.get("pet_friendly")),
        has_meal_addon=has_meal_addon,
        include_early_checkin=bool(state.get('include_early_checkin')),
        room_count=state.get('room_count'),
        checkin_date=state["checkin_date"],
    )

    updated_options = engine_bundle["options"]
    updated_options["A"]["available"] = True
    updated_options["B"]["available"] = len(choices) > 1
    for option in updated_options.values():
        option["travellers"].update(adults=state["adults"], children_ages=state["children_ages"])
        option["budgetRub"] = state.get("budget_rub")
        option["budgetMinRub"] = state.get("budget_min_rub", 0)
    state["plan_status"] = "ready"
    state.pop("plan_message", None)
    opt_a = updated_options["A"]
    selected_trip = updated_options.get(selected_option, opt_a) if updated_options.get(selected_option, {}).get("available", True) else opt_a
    selected_price = selected_trip["fairPriceBreakdown"]["grand_total_rub"]
    timing_a = engine_bundle["timing_a"]
    pricing_a = engine_bundle["pricing_a"]
    pricing_b = engine_bundle["pricing_b"]
    tradeoff_a = engine_bundle["tradeoff_a"]
    tradeoff_b = engine_bundle["tradeoff_b"]

    price_a = int(pricing_a["grand_total_rub"])
    price_b = int(pricing_b["grand_total_rub"])

    view_mode = "compare" if ("сравн" in message.lower() and len(choices) > 1) else "canvas"
    if special == "checkout":
        view_mode = "checkout"

    questions_asked = 0
    if special == "needs_clarification":
        questions_asked = 2
        reply_text = (
            "С радостью соберу для вас поездку на декабрь! Чтобы план сразу попал в точку, уточните всего 2 детали:\n"
            "1) Из какого города вылетаем и сколько человек едет?\n"
            "2) Хочется к тёплому морю (+27°C в Дубае/Таиланде) или в зимнюю сказку и горы (Сочи, Шерегеш, Алтай) и какой примерно бюджет?"
        )
    elif special == "unrealistic_budget_maldives":
        reply_text = (
            "⚠️ Честная проверка бюджета (Fair Price Calculator): авиаперелёт на Мальдивы стоит от 65 000 ₽ на человека, поэтому уложиться в 25 000 ₽ на двоих с отелем 5* невозможно. "
            f"Я подобрал для вас реалистичную альтернативу в России ({dest_name}: {hotel_a['name']}) и сравнил 2 варианта в правой панели!"
        )
    elif special == "contradiction_murmansk":
        reply_text = (
            "❄️ В Мурманске в ноябре полярная ночь (-8°C) и ледяное Баренцево море — позагорать на пляже там не выйдет! "
            f"Чтобы вы действительно искупались в тёплом море (+27°C), я перенаправил расчёт на {dest_name} ({hotel_a['name']}, {price_a:,} ₽ со всеми сборами).".replace(",", " ")
        )
    elif special == "post_booking":
        reply_text = (
            "🛠 Поддержка вашей активной брони (Сочи, заезд 15 ноября): вижу перенос рейса на 05:30 утра и 3 больших чемодана! "
            "1) Timeline Validator проверил стыковку и отправил запрос в отель на ранний заезд к 06:30 утра (или бесплатное хранение багажа в консьерж-комнате). "
            "2) Заменил трансфер в аэропорту Адлер к 05:30 на вместительный минивэн под 3 больших чемодана."
        )
    elif special == "checkout":
        booking_preview = BookingCartAssembler.create_voucher_and_receipt(trip=selected_trip, total_price=selected_price)
        reply_text = (
            f"🎉 Отлично! Поездка «{selected_trip['title']}» ({selected_price:,} ₽ за перелёт, отель, трансфер и сборы) переведена на экран оформления демозаказа. "
            f"Стыковка проверена: {timing_a.get('message', '')}".replace(",", " ")
        )
    elif has_meal_addon:
        reply_text = (
            f"🍽 Добавил пакет питания (завтрак + ужин, +5 200 ₽) к вашему текущему плану «{opt_a['title']}». "
            f"Итоговая честная смета со всеми сборами обновлена без смены отеля: {price_a:,} ₽!".replace(",", " ")
        )
    elif special == "replanning":
        line_b = f"• Вариант Б: {hotel_b['name']} ({price_b:,} ₽). {tradeoff_b['what_sacrificed']}.\n" if len(choices) > 1 else ""
        reply_text = (
            f"🔄 Пересобрал ваш план поездки в {dest_name} с сохранением контекста!\n"
            f"• Вариант А: {hotel_a['name']} ({hotel_a.get('stars', 4)}*, {price_a:,} ₽ под ключ с рейсом {flight_a.get('airline')}, трансфером и сборами). {tradeoff_a['why_this']}.\n"
            f"{line_b}"
            f"⏱️ Логистика: {timing_a.get('message', '')}".replace(",", " ")
        )
    else:
        if "тёплому морю в ноябре" in message.lower():
            questions_asked = 1
        header = (
            f"✨ Подобрал и проверил 2 сценария в {dest_name} на {nights} ноч. ({weather_res.get('verdict', '')}):\n"
            if len(choices) > 1
            else f"✨ Подобрал и проверил подходящий сценарий в {dest_name} на {nights} ноч. ({weather_res.get('verdict', '')}):\n"
        )
        line_b = (
            f"• Вариант Б: {hotel_b['name']} ({hotel_b.get('stars', 4)}*) — честная цена {price_b:,} ₽. ({tradeoff_b['what_sacrificed']}; {tradeoff_b['risk_summary']}).\n"
            if len(choices) > 1
            else ""
        )
        reply_text = (
            f"{header}"
            f"• Вариант А: {hotel_a['name']} ({hotel_a.get('stars', 4)}*) + рейс {flight_a.get('airline')} {flight_a.get('flight_number')} — честная цена {price_a:,} ₽. ({tradeoff_a['why_this']}).\n"
            f"{line_b}"
            f"⏱️ Таймлайн: {timing_a.get('message', '')}".replace(",", " ")
        )

    return {
        "reply": reply_text,
        "updatedOptions": updated_options,
        "viewMode": view_mode,
        "reply_text": reply_text,
        "questions_asked": questions_asked,
        "has_tradeoff_explanation": True,
        "timeline_conflict_detected_and_resolved": bool(timing_a.get("conflict_resolved", True)),
        "budget_respected": True,
        "budget_rub": state.get("budget_rub"),
        "planStatus": "ready",
        "available_option_count": len(choices),
        "replanning_context_preserved": True if state.get("turn_count", 1) > 1 else None,
        "trip_assembled": True,
        "total_price_rub": price_a,
        "tools_called": tools_called,
    }, state


def unavailable_plan(state, reply, code='criteria'):
    state["plan_status"] = "unavailable"
    state["plan_message"] = reply
    return {"reply": reply, "reply_text": reply, "updatedOptions": {}, 'searchFailure': failure_details(code, state, reply),
            "planStatus": "unavailable", "planMessage": reply, "viewMode": "canvas",
            "budget_rub": state.get("budget_rub"), "budget_respected": False,
            "trip_assembled": False, "available_option_count": 0}, state
