"""Deterministic alternatives and demo date moves, without a language model."""
import re
from copy import deepcopy
from datetime import date, timedelta

from src.services.agent_orchestrator import build_trip_response
from src.services.database import load_catalog
from src.services.weather_service import WeatherService
from src.services.catalog_locations import destination_id
from src.services.travel_preferences import matches_destination, style_label


def _rub(amount):
    return f"{amount:,}".replace(",", " ")


def is_alternative_request(message):
    t = message.lower()
    if re.match(r"\s*(?:а\s+)?(?:почему|зачем|объясни|расскажи)\b", t):
        return False
    return bool(re.search(r"(?:друг\w*|альтернатив\w*)\s+(?:направлен\w*|город\w*|стран\w*|мест\w*|вариант\w*)|куда\s+ещ[её]|\bальтернатив[аыуе]?\b", t))


def is_cheapest_request(message):
    return bool(re.fullmatch(r"\s*(?:(?:найди|подбери|выбери|покажи|хочу|собери)\s+)?(?:сам\w*\s+деш[её]в\w*|минимальн\w*\s+стоимост\w*)(?:\s+(?:поездк\w*|вариант\w*|путешестви\w*))?[.!?\s]*", message.lower()))


def cheapest_trip(session):
    state = session["state"]
    scope = state.get("destination")
    destinations = [d for d in load_catalog("destinations") if (not scope or destination_id(scope) == d["id"])
                    and matches_destination(d, state.get("travel_styles", []))]
    proposals = []
    for destination in destinations:
        patch = {"destination": destination["name"], "hotel_ids": [], "sort_by_price": True}
        result, candidate = build_trip_response("", state, intent=patch, preserve_hotels=False, preview=True)
        if result.get("trip_assembled"):
            proposals.append((result["minimum_price_rub"], destination["name"], candidate))
    if not proposals:
        where = f"в {scope}" if scope else "в каталоге"
        reply = f"Нет поездки {where} под сохранённые условия и диапазон бюджета. Измените диапазон, направление или другие ограничения."
        state.update(plan_status="unavailable", plan_message=reply, choosing_alternative=False)
        state.pop("alternative_quotes", None)
        state.pop("suggested_destinations", None)
        session["options"] = {}
        return {"trip_assembled": False}, reply
    minimum, name, candidate = min(proposals, key=lambda p: (p[0], p[1]))
    patch = {"destination": name, "hotel_ids": [], "sort_by_price": True}
    built, state = build_trip_response("", candidate, intent=patch, preserve_hotels=False)
    state.update(choosing_alternative=False)
    state.pop("alternative_quotes", None)
    state.pop("suggested_destinations", None)
    session.update(state=state, options=built.get("updatedOptions", {}), selected_option="A")
    if not built.get("trip_assembled"):
        return built, state.get("plan_message", built.get("reply", "Не удалось собрать поездку."))
    where = f"в {name}" if scope else f"по всему каталогу: {name}"
    avail_count = sum(1 for o in session["options"].values() if o.get("available", True))
    cards_label = "карточка справа" if avail_count == 1 else "карточки справа"
    reply = (f"Самая дешёвая поездка {where} под ваши условия — **{_rub(minimum)} ₽**. "
             f"Это полная сумма с обязательными расходами и возвратным депозитом, если он нужен. **Выбран вариант А**; {cards_label}.\n\n"
             f"Условия расчёта: выезд из {state['origin']}, {state['passengers']} чел., {state['nights']} ноч., "
             f"{date.fromisoformat(state['checkin_date']):%d.%m.%Y} — {date.fromisoformat(state['checkout_date']):%d.%m.%Y}. "
             "Если вы ещё не задавали эти условия, использованы демонстрационные значения. Цены и бронирование демонстрационные.")
    return built, reply


def alternative_destinations(session):
    state = session["state"]
    current = state.get("destination")
    scope = state.get("travel_scope")
    quotes, minima = [], []
    abroad_quotes, abroad_unaffordable = [], []
    russia_quotes = []
    for destination in load_catalog("destinations"):
        if not matches_destination(destination, state.get("travel_styles", [])):
            continue
        if destination["name"] == current or destination["id"] == destination_id(current):
            continue
        intent = {"destination": destination["name"], "hotel_ids": []}
        result, candidate = build_trip_response("", state, intent=intent, preserve_hotels=False, preview=True)
        minimum = result.get("minimum_price_rub")
        if minimum is not None:
            minima.append(minimum)
        is_abroad = destination.get("country") != "Россия"
        climate = destination.get("climate_by_month", {}).get(str(candidate["month"]), {})
        q_item = {"id": destination["id"], "name": destination["name"], "minimum_total_rub": minimum,
                  "nights": candidate["nights"], "passengers": candidate["passengers"],
                  "checkin_date": candidate["checkin_date"], "checkout_date": candidate["checkout_date"],
                  "day_temp": climate.get("avg_day_temp"), "country": destination.get("country", "")}
        if result.get("trip_assembled"):
            if is_abroad:
                abroad_quotes.append(q_item)
            else:
                russia_quotes.append(q_item)
            quotes.append(q_item)
        elif is_abroad and minimum is not None:
            abroad_unaffordable.append(q_item)

    abroad_unmet = False
    if scope == "abroad":
        if abroad_quotes:
            quotes = abroad_quotes
        else:
            abroad_unmet = True
            quotes = russia_quotes

    quotes.sort(key=lambda q: (q["minimum_total_rub"], q["name"]))
    quotes = quotes[:3]
    state["alternative_quotes"] = quotes
    state["suggested_destinations"] = [q["name"] for q in quotes]
    state["choosing_alternative"] = bool(quotes)
    cap = state.get("budget_rub")
    if not quotes:
        reply = "В каталоге нет других направлений под те же условия и бюджет. Можно изменить состав поездки, её длительность или бюджет."
        if scope == "abroad":
            reply = "Зарубежные направления в каталоге превышают указанный бюджет. Можно увеличить бюджет или посмотреть варианты по России."
        elif state.get("travel_styles"):
            reply = f"Для отдыха «{style_label(state['travel_styles'])}» в каталоге нет направлений под сохранённые условия и диапазон бюджета. Можно изменить диапазон, даты, длительность или тип отдыха."
        if minima:
            reply += f" Минимальная полная сумма для другого направления — {_rub(min(minima))} ₽."
        if not session["options"]:
            state.update(plan_status="unavailable", plan_message=reply)
        return reply
    first = quotes[0]
    rows = []
    if abroad_unmet and abroad_unaffordable:
        cheapest_abroad = min(abroad_unaffordable, key=lambda q: q["minimum_total_rub"])
        cap_str = f"{_rub(cap)} ₽" if cap is not None else "ваш бюджет"
        rows.append(f"По запросу **за границу**: к сожалению, зарубежные направления в каталоге (например, **{cheapest_abroad['name']}** — от **{_rub(cheapest_abroad['minimum_total_rub'])} ₽**) превышают {cap_str} из-за стоимости перелётов.\n\nПоэтому предлагаю отличные направления **по России** в вашем бюджете:")
    else:
        rows.append(f"Другие направления на {first['nights']} ноч., {first['passengers']} чел., "
                    f"{date.fromisoformat(first['checkin_date']):%d.%m.%Y} — {date.fromisoformat(first['checkout_date']):%d.%m.%Y}.")
    if state.get("travel_styles"):
        rows.append(f"Учитываю тип отдыха: **{style_label(state['travel_styles'])}**.")
    if cap is not None and not abroad_unmet:
        rows.append(f"Сохранил ваш максимум **{_rub(cap)} ₽ за всю поездку**. Указанные суммы включают обязательные расходы и возвратный депозит, если он нужен.")
    if state.get("budget_min_rub"):
        rows.append(f"Нижняя граница полной стоимости — **{_rub(state['budget_min_rub'])} ₽**.")
    for q in quotes:
        climate = f" Климатическая оценка: около {q['day_temp']:+g} °C днём." if q["day_temp"] is not None else ""
        rows.append(f"• **{q['name']}** — от **{_rub(q['minimum_total_rub'])} ₽**.{climate}")
    rows.append("Выберите направление кнопкой ниже — соберу карточки. Цены и бронирование демонстрационные.")
    if not session["options"]:
        state.update(plan_status="alternatives", plan_message="Есть направления в пределах бюджета. Выберите одно из предложенных в чате.")
    return "\n\n".join(rows)


def inspire_trip(session, styles):
    state = session["state"]
    missing = [label for field, label in (("origin", "город выезда"), ("passengers", "гости"),
               ("nights", "длительность"), ("checkin_date", "даты")) if not state.get(field)]
    state.update(travel_styles=styles, vibe_query=style_label(styles), plan_status="empty")
    for field in ("destination", "hotel_ids", "alternative_quotes", "suggested_destinations", "date_weather", "dates_conditional", "plan_message"):
        state.pop(field, None)
    session.update(options={}, selected_option="A")
    reply = alternative_destinations(session)
    if state.get("alternative_quotes"):
        reply = reply.replace("Другие направления на", "Подходящие направления на", 1)
        first = state["alternative_quotes"][0]
        reply += f"\n\nВыезд из {state.get('origin') or 'Москвы'}."
        if missing:
            reply += f" Расчёт предварительный: для незаданных полей ({', '.join(missing)}) использованы значения из примера. Даты, {first['passengers']} чел. и {first['nights']} ноч. указаны выше — их можно уточнить в чате."
        reply += " Направление выберете сами — карточки появятся после выбора."
    return reply


def reschedule_trip(session, checkin_date, checkout_date=None):
    if not checkin_date:
        raise ValueError("Укажите новую дату начала поездки.")
    start = date.fromisoformat(str(checkin_date))
    if not 2000 <= start.year <= 2100:
        raise ValueError("Выберите дату между 2000 и 2100 годом.")
    state = session["state"]
    nights = int(state.get("nights") or next((o["hotel"]["nights"] for o in session["options"].values()), 4))
    end = start + timedelta(days=nights)
    if checkout_date and date.fromisoformat(str(checkout_date)) != end:
        raise ValueError(f"Перенос сохраняет длительность {nights} ноч. Выезд должен быть {end:%d.%m.%Y}.")
    if end.year > 2100:
        raise ValueError("Выберите дату между 2000 и 2100 годом.")
    if not state.get("destination"):
        state.update(checkin_date=start.isoformat(), checkout_date=end.isoformat(), nights=nights, month=start.month)
        state.pop("alternative_quotes", None)
        state.pop("suggested_destinations", None)
        state["choosing_alternative"] = False
        reply = f"Сохранил даты: {start:%d.%m.%Y} — {end:%d.%m.%Y}, {nights} ноч. Оценка погоды появится после выбора направления."
        if state.get("travel_styles"):
            reply += "\n\n" + alternative_destinations(session)
        return reply
    weather = WeatherService.get_forecast(state["destination"], start.isoformat(), min(nights, 5))
    first_day = weather.get("forecast", [{}])[0]
    temperature = first_day.get("temp_max", 20)
    assessment = {"temp": f"{temperature:+g}°C", "cond": first_day.get("condition", "Климатическая оценка"),
                  "source": weather.get("source", "Offline Climate Fallback"), "verdict": weather.get("verdict", ""),
                  "date": start.isoformat()}
    options = deepcopy(session["options"])
    old_start = date.fromisoformat(state["checkin_date"]) if state.get("checkin_date") else None
    def shift_stamp(match):
        old = date.fromisoformat("-".join(reversed(match.group(0).split("."))))
        return (old + (start - old_start)).strftime("%d.%m.%Y") if old_start else match.group(0)
    for option in options.values():
        option["dates"] = f"{start:%d.%m.%Y} — {end:%d.%m.%Y} • {nights} ноч."
        option["weather"] = {**option.get("weather", {}), **assessment}
        transport = option.get("transport", {})
        if old_start:
            delta = start - old_start
            def shift_iso(value):
                from datetime import datetime
                return (datetime.fromisoformat(value) + delta).isoformat()
            for leg in transport.get("legs", []):
                for field in ("departure", "arrival"):
                    leg[field] = shift_iso(leg[field])
            for leg in (transport.get("returnFlight") or {}).get("legs", []):
                for field in ("departure", "arrival"):
                    leg[field] = shift_iso(leg[field])
            transport["scheduleConditional"] = True
        if old_start:
            shift = start - old_start
            transport = option.get("transport", {})
            for field in ("departureDate", "arrivalDate"):
                if transport.get(field):
                    transport[field] = (date.fromisoformat(transport[field]) + shift).isoformat()
            returning = transport.get("returnFlight") or {}
            for field in ("date", "arrival_date"):
                if returning.get(field):
                    returning[field] = (date.fromisoformat(returning[field]) + shift).isoformat()
        for step in option.get("timeline", []):
            step["time"] = re.sub(r"\b\d{2}\.\d{2}\.\d{4}\b", shift_stamp, step.get("time", ""))
            if old_start:
                step["desc"] = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", lambda m: (date.fromisoformat(m[0]) + (start - old_start)).isoformat(), step.get("desc", ""))
        option["datesConditional"] = True
    session["options"] = options
    state.update(checkin_date=start.isoformat(), checkout_date=end.isoformat(), month=start.month,
                 nights=nights, date_weather=assessment, dates_conditional=True, choosing_alternative=False)
    state.pop("alternative_quotes", None)
    state.pop("suggested_destinations", None)
    if options:
        state["plan_status"] = "ready"
        state.pop("plan_message", None)
    else:
        state["plan_status"] = "unavailable" if state.get("plan_status") in ("unavailable", "alternatives") else "empty"
        state["plan_message"] = "Даты сохранены. Подберите направление в пределах бюджета или повторите подбор."
    kind = "Климатическая оценка" if assessment["source"] == "Offline Climate Fallback" else "Прогноз погоды"
    return (f"Перенёс поездку на **{start:%d.%m.%Y} — {end:%d.%m.%Y}**, {nights} ноч. "
            "В этом демо отели, транспорт, услуги и суммы сметы при переносе дат не меняются.\n\n"
            f"**{kind} на новую дату:** {assessment['temp']}, {assessment['cond']}. "
            + ("Это оценка по сезону, а не точный прогноз." if kind == "Климатическая оценка" else "Прогноз может уточняться."))
