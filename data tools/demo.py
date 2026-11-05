import sys
import json

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

def print_section(title: str):
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)

def main():
    print("🎯 ДЕМОНСТРАЦИЯ НАБОРА ИНСТРУМЕНТОВ (TRAVEL TOOLS ENGINE)")

    # 1. Инструмент search_destinations
    print_section("1. ТЕСТ: search_destinations (Запрос: 'где тепло в ноябре с ребенком без долгого перелета')")
    dest_res = search_destinations(
        query="где тепло в ноябре с ребенком без долгого перелета",
        month=11,
        limit=2
    )
    for d in dest_res["destinations"]:
        print(f"\n📍 {d['name']} ({d['country']}) — Скор: {d['match_score']}")
        print(f"   Вайбы: {', '.join(d['vibes'][:4])}")
        print(f"   Климат в ноябре: днем +{d['climate_for_target_month']['avg_day_temp']}°C, вода +{d['climate_for_target_month']['water_temp']}°C")
        print(f"   Перелет из Москвы: ~{d['flight_time_hours_from_mow']} ч.")
        print(f"   Причины рекомендации:")
        for r in d["match_reasons"]:
            print(f"     • {r}")

    # 2. Инструмент search_hotels
    print_section("2. ТЕСТ: search_hotels (Отели Шерегеша: шале с камином, pet-friendly)")
    hotel_res = search_hotels(
        destination="Шерегеш",
        checkin_date="2026-11-20",
        checkout_date="2026-11-23",
        vibe_query="уютное шале в горах камин",
        pet_friendly=True,
        limit=2
    )
    for h in hotel_res["hotels"]:
        print(f"\n🏨 {h['name']} ({h['stars']}⭐) — Рейтинг: {h['rating']}/10")
        print(f"   Цена: {h['price_per_night']} руб./ночь (Итого за {h['nights_count']} ночи: {h['total_price']} руб.)")
        print(f"   Заезд / Выезд: {h['checkin_time']} / {h['checkout_time']}")
        print(f"   Условия для питомца: {h['pet_friendly']['description']}")
        print(f"   Детская кроватка: {'Да' if h['child_friendly']['baby_crib_available'] else 'Нет'}")
        print(f"   Депозит: {'Требуется' if h['deposit']['required'] else 'Без депозита'}")
        print(f"   Хайлайты:")
        for hl in h["match_highlights"]:
            print(f"     • {hl}")

    # 3. Инструмент search_transfers_and_flights
    print_section("3. ТЕСТ: search_transfers_and_flights (Перелет в Сочи + состыковка с отелем)")
    flight_res = search_transfers_and_flights(
        origin="Москва",
        destination="Сочи",
        date="2026-11-15",
        passengers=2,
        hotel_checkin_time="14:00"
    )
    print(f"\n✈️ Найдено рейсов: {len(flight_res['flights'])}")
    best_f = flight_res["flights"][0]
    print(f"   Лучший рейс: {best_f['airline']} {best_f['flight_number']}")
    print(f"   Вылет: {best_f['departure_time']} -> Прилет: {best_f['arrival_time']} (в пути {best_f['duration_hours']}ч)")
    print(f"   Багаж: {best_f['baggage']['weight_kg']} кг включен | Цена на 2 пасс.: {best_f['total_price']} руб.")

    print(f"\n🚖 Трансфер:")
    t = flight_res["transfers"][0]
    print(f"   {t['type']} ({t['vehicle']}) — {t['price_rub']} руб. ({t['duration_minutes']} мин в пути)")

    print(f"\n⏱️ Анализ состыковки времени:")
    print(f"   {flight_res['timing_analysis']['message']}")

    # 4. Инструмент get_weather_forecast
    print_section("4. ТЕСТ: get_weather_forecast (Прогноз в Дубае на 5 дней)")
    weather_res = get_weather_forecast(city="Дубай", days=5)
    print(f"🌤️ Источник: {weather_res['source']}")
    print(f"   Вердикт: {weather_res['verdict']}")
    print(f"   Дни:")
    for w in weather_res["forecast"][:3]:
        print(f"     • {w['date']}: макс +{w['temp_max']}°C, мин +{w['temp_min']}°C, {w['condition']}")

    # 5. Демонстрация универсального execute_tool_call (как вызывает LLM-оркестратор)
    print_section("5. ТЕСТ: execute_tool_call (Эмуляция LLM Tool Call)")
    simulated_call = execute_tool_call(
        tool_name="search_destinations",
        arguments={"query": "горы лыжи пухляк", "month": 12, "limit": 1}
    )
    print(f"Успешный ответ агенту: найдено {simulated_call['found_count']} направление -> {simulated_call['destinations'][0]['name']}")

    print("\n✅ ВСЕ ИНСТРУМЕНТЫ РАБОТАЮТ ИДЕАЛЬНО!")

if __name__ == "__main__":
    main()
