import asyncio
from typing import Optional, Dict, Any, List

from src.services.destination_service import DestinationService
from src.services.hotel_service import HotelService
from src.services.flight_service import FlightService
from src.services.weather_service import WeatherService

def search_destinations(
    query: Optional[str] = None,
    month: Optional[int] = None,
    min_temp: Optional[float] = None,
    vibe: Optional[str] = None,
    max_flight_hours: Optional[float] = None,
    budget_tier: Optional[str] = None,
    limit: int = 5
) -> Dict[str, Any]:
    """
    Поиск туристических направлений по неявным критериям, 'вайбу', погоде, сезону и бюджету.

    Примеры использования:
    - 'где тепло в ноябре с ребенком'
    - 'хочу уютные шале в горах со снегом и камином'
    - 'недорого к морю без долгого перелета'

    :param query: Текстовый запрос или описание желаемого отдыха
    :param month: Номер месяца поездки (1-12), например 11 для ноября
    :param min_temp: Желаемая минимальная дневная температура (°C)
    :param vibe: Ключевой вайб (море, горы, лыжи, романтика, вечеринки, с детьми)
    :param max_flight_hours: Максимальное время прямого перелета из Москвы (в часах)
    :param budget_tier: Ценовой сегмент: 'budget', 'medium', 'luxury'
    :param limit: Количество рекомендуемых направлений
    :return: Словарь со списком направлений, климатической сводкой и причинами рекомендации
    """
    return DestinationService.search(
        query=query,
        month=month,
        min_temp=min_temp,
        vibe=vibe,
        max_flight_hours=max_flight_hours,
        budget_tier=budget_tier,
        limit=limit
    )

def search_hotels(
    destination: str,
    checkin_date: Optional[str] = None,
    checkout_date: Optional[str] = None,
    guests: int = 2,
    max_price_per_night: Optional[float] = None,
    min_rating: Optional[float] = None,
    pet_friendly: Optional[bool] = None,
    baby_crib: Optional[bool] = None,
    no_deposit: Optional[bool] = None,
    free_cancellation: Optional[bool] = None,
    meal_type: Optional[str] = None,
    max_distance_to_center_km: Optional[float] = None,
    max_distance_to_beach_m: Optional[float] = None,
    vibe_query: Optional[str] = None,
    limit: int = 5
) -> Dict[str, Any]:
    """
    Поиск отелей по каталогу с поддержкой реалистичных жизненных фильтров.

    Включает обогащенные атрибуты:
    - pet_friendly (разрешены ли животные, стоимость за ночь/весь заезд, ограничение по весу)
    - baby_crib (наличие детской кроватки, детский клуб, няня)
    - deposit (размер залога при заезде или его отсутствие)
    - checkin_time / checkout_time (время заезда и выезда для состыковки с рейсом)
    - cancellation_policy (бесплатная отмена до даты X или гибкий тариф)
    - meal_type ('RO' - без питания, 'BB' - завтрак, 'HB' - полупансион, 'AI' - все включено)

    :param destination: Город или курорт (например: 'Сочи', 'Шерегеш', 'Дубай', 'Пхукет', 'Алтай')
    :param checkin_date: Дата заезда (YYYY-MM-DD)
    :param checkout_date: Дата выезда (YYYY-MM-DD)
    :param guests: Количество гостей
    :param max_price_per_night: Максимальная цена за 1 ночь в рублях
    :param min_rating: Минимальный рейтинг отеля (например 8.5)
    :param pet_friendly: Обязательно ли разрешено проживание с собакой/кошкой
    :param baby_crib: Нужна ли бесплатная детская кроватка в номере
    :param no_deposit: Только варианты без обязательного депозита/залога
    :param free_cancellation: Только с бесплатной отменой бронирования
    :param meal_type: Тип питания ('RO', 'BB', 'HB', 'AI')
    :param max_distance_to_center_km: Максимальное расстояние до центра в км
    :param max_distance_to_beach_m: Максимальное расстояние до моря в метрах
    :param vibe_query: Поиск по атмосфере (например: 'камин', 'шале в горах', 'первая линия')
    :param limit: Количество отелей в выдаче
    :return: Словарь со списком отелей, расчетом суммарной стоимости и хайлайтами
    """
    return HotelService.search(
        destination=destination,
        checkin_date=checkin_date,
        checkout_date=checkout_date,
        guests=guests,
        max_price_per_night=max_price_per_night,
        min_rating=min_rating,
        pet_friendly=pet_friendly,
        baby_crib=baby_crib,
        no_deposit=no_deposit,
        free_cancellation=free_cancellation,
        meal_type=meal_type,
        max_distance_to_center_km=max_distance_to_center_km,
        max_distance_to_beach_m=max_distance_to_beach_m,
        vibe_query=vibe_query,
        limit=limit
    )

def search_transfers_and_flights(
    destination: str,
    date: str,
    origin: str = "Москва",
    return_date: Optional[str] = None,
    passengers: int = 1,
    need_transfer: bool = True,
    hotel_checkin_time: str = "14:00",
    hotel_name: Optional[str] = None,
    departure_after: Optional[str] = None,
    departure_before: Optional[str] = None,
    return_departure_after: Optional[str] = None,
    return_departure_before: Optional[str] = None,
    return_arrival_after: Optional[str] = None,
    return_arrival_before: Optional[str] = None,
    preview: bool = False,
    adults: Optional[int] = None,
    children_ages: Optional[list[int]] = None,
    arrival_after: Optional[str] = None,
    arrival_before: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Подбор авиабилетов и трансферов до отеля с интеллектуальным анализом состыковки времени.

    Проверяет:
    - Время прибытия рейса + время получения багажа + время трансфера -> время прибытия в отель.
    - Сопоставляет со временем заселения (check-in) в отель, исключая долгое ожидание в холле.

    :param destination: Город назначения (например 'Сочи', 'Дубай', 'Шерегеш', 'Пхукет')
    :param date: Дата вылета (YYYY-MM-DD)
    :param origin: Город вылета (по умолчанию 'Москва')
    :param return_date: Дата обратного рейса (опционально)
    :param passengers: Количество пассажиров
    :param need_transfer: Нужен ли подбор трансфера из аэропорта до отеля
    :param hotel_checkin_time: Время заезда в отель (например '14:00')
    :param hotel_name: Название выбранного отеля
    :return: Варианты рейсов, трансферов и анализ состыковки
    """
    return FlightService.search(
        origin=origin,
        destination=destination,
        date=date,
        return_date=return_date,
        passengers=passengers,
        need_transfer=need_transfer,
        hotel_checkin_time=hotel_checkin_time,
        hotel_name=hotel_name,
        departure_after=departure_after, departure_before=departure_before,
        return_departure_after=return_departure_after, return_departure_before=return_departure_before,
        return_arrival_after=return_arrival_after, return_arrival_before=return_arrival_before,
        preview=preview,
        adults=adults, children_ages=children_ages,
        arrival_after=arrival_after, arrival_before=arrival_before,
    )

def get_weather_forecast(
    city: str,
    date: Optional[str] = None,
    days: int = 7
) -> Dict[str, Any]:
    """
    Получение прогноза погоды через Open-Meteo API с надежным офлайн-фоллбэком.

    :param city: Город или курорт (например: 'Сочи', 'Дубай', 'Шерегеш', 'Пхукет', 'Алтай')
    :param date: Дата начала (опционально, YYYY-MM-DD)
    :param days: Количество дней (от 1 до 14, по умолчанию 7)
    :return: Прогноз по дням (макс/мин температура, осадки, состояние) и туристический вердикт
    """
    return WeatherService.get_forecast(city=city, start_date=date, days=days)
