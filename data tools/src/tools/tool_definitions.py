from typing import Dict, Any, List
from src.models.schemas import TransferFlightSearchParams
from src.tools.travel_tools import (
    search_destinations,
    search_hotels,
    search_transfers_and_flights,
    get_weather_forecast
)

OPENAI_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_destinations",
            "description": "Поиск туристических направлений по 'вайбу', погоде, сезону, бюджету и времени перелета. Решает этап Inspiration и выбор направления для размытых запросов (например: 'где тепло в ноябре с ребенком', 'уютные шале в горах').",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Текстовый запрос или описание желаемого отдыха (например: 'где тепло в ноябре', 'хочу шале в горах')"
                    },
                    "month": {
                        "type": "integer",
                        "description": "Номер месяца поездки от 1 до 12 (например 11 для ноября)"
                    },
                    "min_temp": {
                        "type": "number",
                        "description": "Минимальная средняя дневная температура (°C)"
                    },
                    "vibe": {
                        "type": "string",
                        "description": "Вайб: пляж, горы, романтика, вечеринки, лыжи, с детьми, спа, гастрономия"
                    },
                    "max_flight_hours": {
                        "type": "number",
                        "description": "Максимальное время перелета из Москвы (часы)"
                    },
                    "budget_tier": {
                        "type": "string",
                        "enum": ["budget", "medium", "luxury"],
                        "description": "Ценовая категория"
                    },
                    "limit": {
                        "type": "integer",
                        "default": 5,
                        "description": "Количество возвращаемых направлений"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_hotels",
            "description": "Поиск отелей по каталогу с поддержкой реалистичных жизненных фильтров: питомцы (pet-friendly), детская кроватка (baby crib), отсутствие залога/депозита, бесплатная отмена, тип питания, время заезда/выезда и семантический поиск по атмосфере (камин, первая линия, шале).",
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {
                        "type": "string",
                        "description": "Город или курорт (например: Сочи, Шерегеш, Дубай, Пхукет, Алтай)"
                    },
                    "checkin_date": {
                        "type": "string",
                        "description": "Дата заезда в формате YYYY-MM-DD"
                    },
                    "checkout_date": {
                        "type": "string",
                        "description": "Дата выезда в формате YYYY-MM-DD"
                    },
                    "guests": {
                        "type": "integer",
                        "default": 2,
                        "description": "Количество гостей"
                    },
                    "max_price_per_night": {
                        "type": "number",
                        "description": "Максимальный бюджет за 1 ночь в рублях"
                    },
                    "min_rating": {
                        "type": "number",
                        "description": "Минимальный рейтинг (например 8.5)"
                    },
                    "pet_friendly": {
                        "type": "boolean",
                        "description": "Обязательно ли разрешено проживание с животными (собака/кошка)"
                    },
                    "baby_crib": {
                        "type": "boolean",
                        "description": "Требуется ли детская кроватка"
                    },
                    "no_deposit": {
                        "type": "boolean",
                        "description": "Только отели без обязательного денежного залога/депозита"
                    },
                    "free_cancellation": {
                        "type": "boolean",
                        "description": "Только тарифы с бесплатной отменой"
                    },
                    "meal_type": {
                        "type": "string",
                        "enum": ["RO", "BB", "HB", "AI"],
                        "description": "Питание: RO (без), BB (завтрак), HB (полупансион), AI (все включено)"
                    },
                    "max_distance_to_center_km": {
                        "type": "number",
                        "description": "Максимальное расстояние до центра города (км)"
                    },
                    "max_distance_to_beach_m": {
                        "type": "number",
                        "description": "Максимальное расстояние до моря/пляжа (метры)"
                    },
                    "vibe_query": {
                        "type": "string",
                        "description": "Поиск по атмосфере (например: 'камин', 'шале с панорамой', 'первая линия')"
                    },
                    "limit": {
                        "type": "integer",
                        "default": 5,
                        "description": "Количество отелей в ответе"
                    }
                },
                "required": ["destination"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_transfers_and_flights",
            "description": "Подбор авиабилетов и трансферов до отеля с автоматической проверкой состыковки времени прилета и заселения в отель (check-in time).",
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {
                        "type": "string",
                        "description": "Город назначения (например Сочи, Дубай, Шерегеш)"
                    },
                    "date": {
                        "type": "string",
                        "description": "Дата вылета в формате YYYY-MM-DD"
                    },
                    "origin": {
                        "type": "string",
                        "default": "Москва",
                        "description": "Город отправления (по умолчанию Москва)"
                    },
                    "return_date": {
                        "type": "string",
                        "description": "Дата обратного вылета (YYYY-MM-DD)"
                    },
                    "departure_after": {"type": "string", "description": "Вылет туда не раньше HH:MM"},
                    "departure_before": {"type": "string", "description": "Вылет туда не позже HH:MM"},
                    "return_departure_after": {"type": "string", "description": "Обратный вылет не раньше HH:MM"},
                    "return_departure_before": {"type": "string", "description": "Обратный вылет не позже HH:MM"},
                    "return_arrival_after": {"type": "string", "description": "Прибытие домой не раньше HH:MM в день возвращения"},
                    "return_arrival_before": {"type": "string", "description": "Прибытие домой не позже HH:MM в день возвращения"},
                    "passengers": {
                        "type": "integer",
                        "default": 1,
                        "description": "Количество пассажиров"
                    },
                    "need_transfer": {
                        "type": "boolean",
                        "default": True,
                        "description": "Нужен ли трансфер из аэропорта в отель"
                    },
                    "hotel_checkin_time": {
                        "type": "string",
                        "default": "14:00",
                        "description": "Время заселения в отель (HH:MM) для анализа состыковки"
                    },
                    "hotel_name": {
                        "type": "string",
                        "description": "Название забронированного отеля"
                    }
                },
                "required": ["destination", "date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather_forecast",
            "description": "Получение подробного прогноза погоды на даты поездки через бесплатный Open-Meteo API с туристическим вердиктом (температура, осадки, благоприятность для отдыха).",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "Город или курорт (например: Сочи, Дубай, Шерегеш, Пхукет)"
                    },
                    "date": {
                        "type": "string",
                        "description": "Дата начала прогноза (YYYY-MM-DD)"
                    },
                    "days": {
                        "type": "integer",
                        "default": 7,
                        "description": "Количество дней прогноза (от 1 до 14)"
                    }
                },
                "required": ["city"]
            }
        }
    }
]

for definition in OPENAI_TOOL_DEFINITIONS:
    if definition["function"]["name"] == "search_transfers_and_flights":
        definition["function"]["parameters"] = TransferFlightSearchParams.model_json_schema()

TOOL_REGISTRY = {
    "search_destinations": search_destinations,
    "search_hotels": search_hotels,
    "search_transfers_and_flights": search_transfers_and_flights,
    "get_weather_forecast": get_weather_forecast
}

def execute_tool_call(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Универсальный исполнитель вызовов инструментов для AI-оркестратора."""
    if tool_name not in TOOL_REGISTRY:
        return {"error": f"Tool '{tool_name}' not found. Available: {list(TOOL_REGISTRY.keys())}"}
    func = TOOL_REGISTRY[tool_name]
    return func(**arguments)
