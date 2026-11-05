from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from src.services.flight_preferences import TIME_PATTERN
from src.services.travel_party import ChildAge


class DestinationSearchParams(BaseModel):
    query: Optional[str] = Field(None, description="Текстовый запрос или вайб (например: 'где тепло в ноябре', 'уютные шале в горах')")
    month: Optional[int] = Field(None, ge=1, le=12, description="Месяц поездки (1-12). Например: 11 для ноября")
    min_temp: Optional[float] = Field(None, description="Минимальная средняя дневная температура (°C)")
    vibe: Optional[str] = Field(None, description="Ключевой вайб (пляж, горы, романтика, вечеринки, с детьми, лыжи)")
    max_flight_hours: Optional[float] = Field(None, description="Максимальное время перелета из Москвы (часы)")
    budget_tier: Optional[str] = Field(None, description="Уровень бюджета: 'budget', 'medium', 'luxury'")
    limit: int = Field(5, ge=1, le=20, description="Количество вариантов в ответе")

class DestinationClimate(BaseModel):
    month: int
    avg_day_temp: float
    avg_night_temp: float
    water_temp: float
    rainy_days: int
    description: str

class DestinationItem(BaseModel):
    id: str
    name: str
    country: str
    latitude: float
    longitude: float
    flight_time_hours_from_mow: float
    direct_flight_available: bool
    avg_budget_tier: str
    avg_daily_cost_rub: int
    vibes: List[str]
    description: str
    climate_for_target_month: Optional[DestinationClimate] = None
    best_months: List[int]
    visa_requirements: str
    top_activities: List[str]
    match_score: Optional[float] = None
    match_reasons: List[str] = Field(default_factory=list)

class DestinationSearchResponse(BaseModel):
    query: Optional[str]
    found_count: int
    destinations: List[DestinationItem]


class HotelSearchParams(BaseModel):
    destination: str = Field(..., description="Город или направление (например 'Сочи', 'Шерегеш', 'Дубай')")
    checkin_date: Optional[str] = Field(None, description="Дата заезда в формате YYYY-MM-DD")
    checkout_date: Optional[str] = Field(None, description="Дата выезда в формате YYYY-MM-DD")
    guests: int = Field(2, ge=1, le=10, description="Количество гостей")
    max_price_per_night: Optional[float] = Field(None, description="Максимальная цена за ночь в рублях")
    min_rating: Optional[float] = Field(None, description="Минимальная оценка отеля (например 8.5)")
    pet_friendly: Optional[bool] = Field(None, description="Обязательно ли разрешено проживание с питомцами")
    baby_crib: Optional[bool] = Field(None, description="Требуется ли наличие детской кроватки")
    no_deposit: Optional[bool] = Field(None, description="Искать только отели без обязательного залога/депозита")
    free_cancellation: Optional[bool] = Field(None, description="Искать только с бесплатной отменой")
    meal_type: Optional[str] = Field(None, description="Тип питания: 'RO' (без), 'BB' (завтрак), 'HB' (полупансион), 'AI' (все включено)")
    max_distance_to_center_km: Optional[float] = Field(None, description="Максимальное расстояние до центра (км)")
    max_distance_to_beach_m: Optional[float] = Field(None, description="Максимальное расстояние до пляжа (метры)")
    vibe_query: Optional[str] = Field(None, description="Вайб отеля (например 'камин', 'шале', 'первая линия', 'роскошный спа')")
    limit: int = Field(5, ge=1, le=20, description="Лимит возвращаемых отелей")

class PetPolicy(BaseModel):
    allowed: bool
    fee_per_stay: int
    max_weight_kg: int
    description: str

class ChildPolicy(BaseModel):
    baby_crib_available: bool
    baby_crib_free: bool
    kids_club: bool
    description: str

class DepositPolicy(BaseModel):
    required: bool
    amount: float
    currency: str
    description: str

class CancellationPolicy(BaseModel):
    type: str
    free_cancellation_days_before: Optional[int] = None
    description: str

class HotelItem(BaseModel):
    id: str
    name: str
    destination_id: str
    destination_name: str
    stars: int
    rating: float
    reviews_count: int
    price_per_night: int
    currency: str
    nights_count: Optional[int] = None
    total_price: Optional[int] = None
    address: str
    distance_to_center_km: Optional[float] = None
    distance_to_beach_m: Optional[float] = None
    distance_to_ski_lift_m: Optional[float] = None
    checkin_time: str
    checkout_time: str
    early_checkin_available: bool
    late_checkout_available: bool
    pet_friendly: PetPolicy
    child_friendly: ChildPolicy
    deposit: DepositPolicy
    cancellation_policy: CancellationPolicy
    meal_type: str
    meal_description: str
    amenities: List[str]
    vibe_tags: List[str]
    description: str
    photos: List[str]
    match_score: Optional[float] = None
    match_highlights: List[str] = Field(default_factory=list)

class HotelSearchResponse(BaseModel):
    destination: str
    dates: Optional[Dict[str, Optional[str]]] = None
    found_count: int
    hotels: List[HotelItem]


class TransferFlightSearchParams(BaseModel):
    adults: Optional[int] = Field(None, ge=1, le=10)
    children_ages: Optional[List[ChildAge]] = Field(None, max_length=9)
    arrival_after: Optional[str] = Field(None, pattern=TIME_PATTERN)
    arrival_before: Optional[str] = Field(None, pattern=TIME_PATTERN)
    departure_after: Optional[str] = Field(None, pattern=TIME_PATTERN, description="Вылет туда не раньше HH:MM")
    departure_before: Optional[str] = Field(None, pattern=TIME_PATTERN, description="Вылет туда не позже HH:MM")
    return_departure_after: Optional[str] = Field(None, pattern=TIME_PATTERN)
    return_departure_before: Optional[str] = Field(None, pattern=TIME_PATTERN)
    return_arrival_after: Optional[str] = Field(None, pattern=TIME_PATTERN, description="Прибытие домой не раньше HH:MM в день возвращения")
    return_arrival_before: Optional[str] = Field(None, pattern=TIME_PATTERN)
    origin: str = Field(default="Москва", description="Город вылета (например: 'Москва', 'MOW', 'Санкт-Петербург')")
    destination: str = Field(..., description="Город или направление прибытия (например 'Сочи', 'Дубай', 'Шерегеш')")
    date: str = Field(..., description="Дата вылета (YYYY-MM-DD)")
    return_date: Optional[str] = Field(None, description="Дата обратного вылета (YYYY-MM-DD)")
    passengers: int = Field(default=1, ge=1, le=10, description="Количество пассажиров")
    need_transfer: bool = Field(default=True, description="Включать ли подбор трансфера от аэропорта до отеля")
    hotel_checkin_time: Optional[str] = Field(default="14:00", description="Время заезда в отель для состыковки с рейсом (HH:MM)")
    hotel_name: Optional[str] = Field(None, description="Название отеля для расчета маршрута трансфера")

class BaggageInfo(BaseModel):
    included: bool
    weight_kg: int
    carry_on_kg: int

class FlightOption(BaseModel):
    legs: List[Dict[str, Any]] = Field(default_factory=list)
    layovers: List[Dict[str, Any]] = Field(default_factory=list)
    modes: List[str] = Field(default_factory=list)
    source: Optional[str] = None
    party: Optional[Dict[str, Any]] = None
    arrival_date: Optional[str] = None
    route_rank: int = 0
    return_flight: Optional[Dict[str, Any]] = None
    price_includes_return: bool = False
    flight_number: str
    airline: str
    origin: str
    destination: str
    departure_time: str
    arrival_time: str
    duration_hours: float
    is_direct: bool
    baggage: BaggageInfo
    price_per_passenger: int
    total_price: int

class TransferOption(BaseModel):
    type: str
    vehicle: str
    capacity_passengers: int
    capacity_luggage: int
    duration_minutes: int
    price_rub: int
    child_seat_available: bool
    pet_friendly: bool
    meet_with_sign: bool
    description: str

class TimingAnalysis(BaseModel):
    flight_arrival: str
    transfer_duration_minutes: int
    estimated_hotel_arrival: str
    hotel_checkin_time: str
    status: str
    message: str

class TransferFlightResponse(BaseModel):
    origin: str
    destination: str
    date: str
    passengers: int
    flights: List[FlightOption]
    transfers: List[TransferOption]
    timing_analysis: Optional[TimingAnalysis] = None


class WeatherForecastParams(BaseModel):
    city: str = Field(..., description="Город или курорт (например 'Сочи', 'Дубай', 'Шерегеш', 'Пхукет')")
    date: Optional[str] = Field(None, description="Начальная дата прогноза (YYYY-MM-DD)")
    days: int = Field(default=7, ge=1, le=14, description="Количество дней прогноза (от 1 до 14)")

class DailyForecast(BaseModel):
    date: str
    temp_max: float
    temp_min: float
    precipitation_mm: float
    condition: str
    is_favorable_for_vacation: bool

class WeatherForecastResponse(BaseModel):
    city: str
    country: str
    source: str
    verdict: str
    forecast: List[DailyForecast]
