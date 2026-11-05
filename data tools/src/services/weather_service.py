import json
import os
import threading
import urllib.request
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from src.models.schemas import WeatherForecastResponse, DailyForecast
from src.services.database import load_catalog

WEATHER_CODE_DESCRIPTIONS = {
    0: "Ясно, солнечно ☀️",
    1: "В основном ясно 🌤️",
    2: "Переменная облачность ⛅",
    3: "Пасмурно ☁️",
    45: "Туман 🌫️",
    48: "Иней / туман 🌫️",
    51: "Небольшая морось 🌦️",
    53: "Умеренная морось 🌧️",
    55: "Плотная морось 🌧️",
    61: "Небольшой дождь 🌦️",
    63: "Умеренный дождь 🌧️",
    65: "Сильный дождь 🌧️",
    71: "Небольшой снег 🌨️",
    73: "Снегопад 🌨️",
    75: "Сильный снегопад ❄️",
    77: "Снежные зерна ❄️",
    80: "Кратковременный ливень 🌦️",
    81: "Ливень 🌧️",
    82: "Шквальный ливень ⛈️",
    95: "Гроза ⚡"
}

CITY_COORDINATES = {
    "дубай": {"lat": 25.2048, "lon": 55.2708, "country": "ОАЭ", "name": "Дубай"},
    "пхукет": {"lat": 7.8804, "lon": 98.3923, "country": "Таиланд", "name": "Пхукет"},
    "сочи": {"lat": 43.5855, "lon": 39.7231, "country": "Россия", "name": "Сочи"},
    "шерегеш": {"lat": 52.9208, "lon": 87.9868, "country": "Россия", "name": "Шерегеш"},
    "алтай": {"lat": 51.9582, "lon": 85.9603, "country": "Россия", "name": "Горно-Алтайск (Алтай)"},
    "стамбул": {"lat": 41.0082, "lon": 28.9784, "country": "Турция", "name": "Стамбул"},
    "мальдивы": {"lat": 3.2028, "lon": 73.2207, "country": "Мальдивы", "name": "Мале (Мальдивы)"},
    "калининград": {"lat": 54.7104, "lon": 20.4522, "country": "Россия", "name": "Калининград"},
    "москва": {"lat": 55.7558, "lon": 37.6173, "country": "Россия", "name": "Москва"},
    "санкт-петербург": {"lat": 59.9343, "lon": 30.3351, "country": "Россия", "name": "Санкт-Петербург"}
}

class WeatherService:
    @staticmethod
    def _find_city_info(city_query: str) -> Dict[str, Any]:
        normalized = city_query.strip().lower()
        for dest in load_catalog("destinations"):
            if normalized in (dest["name"].lower(), dest["id"].lower()):
                return {"lat": dest["latitude"], "lon": dest["longitude"],
                        "country": dest["country"], "name": dest["name"]}
        for key, val in CITY_COORDINATES.items():
            if key in normalized or normalized in key:
                return val
        return {"lat": 43.5855, "lon": 39.7231, "country": "Россия", "name": city_query.capitalize()}

    @classmethod
    def get_forecast(cls, city: str, start_date: Optional[str] = None, days: int = 7) -> Dict[str, Any]:
        city_info = cls._find_city_info(city)
        lat = city_info["lat"]
        lon = city_info["lon"]
        city_name = city_info["name"]
        country = city_info["country"]
        start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else datetime.now()
        end = start + timedelta(days=days - 1)

        # Климатическая оценка для офлайна и дат вне горизонта прогноза.
        if (os.environ.get("OFFLINE_MODE") == "1" or start.date() < datetime.now().date()
                or end.date() > (datetime.now() + timedelta(days=13)).date()):
            return cls._get_offline_fallback(city_name, country, days, start)

        result_container = {}

        def fetch_api():
            try:
                url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=auto&start_date={start:%Y-%m-%d}&end_date={end:%Y-%m-%d}"
                req = urllib.request.Request(url, headers={"User-Agent": "TravelAIChatbot/1.0"})
                with urllib.request.urlopen(req, timeout=0.8) as resp:
                    if resp.status == 200:
                        result_container["data"] = json.loads(resp.read().decode("utf-8"))
            except Exception:
                pass

        # Изолированный поток с жестким таймаутом - исключает зависание главного потока на Windows DNS
        worker = threading.Thread(target=fetch_api, daemon=True)
        worker.start()
        worker.join(timeout=0.6)

        data = result_container.get("data")
        if data and "daily" in data:
            daily = data["daily"]
            dates = daily.get("time", [])
            max_temps = daily.get("temperature_2m_max", [])
            min_temps = daily.get("temperature_2m_min", [])
            precips = daily.get("precipitation_sum", [])
            codes = daily.get("weather_code", [])

            forecast_items = []
            avg_max = 0.0
            for i in range(len(dates)):
                t_max = max_temps[i]
                t_min = min_temps[i]
                p_sum = precips[i]
                code = codes[i]
                cond = WEATHER_CODE_DESCRIPTIONS.get(code, "Переменная облачность")
                is_fav = (t_max >= 20.0 and p_sum < 2.0) or (t_max < 0 and "снег" in cond.lower())

                forecast_items.append({
                    "date": dates[i],
                    "temp_max": t_max,
                    "temp_min": t_min,
                    "precipitation_mm": p_sum,
                    "condition": cond,
                    "is_favorable_for_vacation": is_fav
                })
                avg_max += t_max

            avg_max = round(avg_max / max(len(dates), 1), 1)
            verdict = cls._build_verdict(city_name, avg_max, sum(precips))

            return {
                "city": city_name,
                "country": country,
                "source": "Open-Meteo Live API",
                "verdict": verdict,
                "forecast": forecast_items
            }

        # Климатическая оценка при недоступности API.
        return cls._get_offline_fallback(city_name, country, days, start)

    @classmethod
    def _build_verdict(cls, city: str, avg_temp: float, total_rain: float) -> str:
        if avg_temp >= 26:
            return f"В {city} великолепная теплая погода (в среднем +{avg_temp}°C). Отлично для пляжного отдыха и загара!"
        elif avg_temp >= 18:
            return f"В {city} комфортное мягкое тепло (+{avg_temp}°C). Идеально для прогулок, экскурсий и осмотра достопримечательностей."
        elif avg_temp < 0:
            return f"В {city} зимняя морозная погода ({avg_temp}°C). Прекрасные условия для горнолыжного отдыха и снежных шале."
        else:
            return f"В {city} умеренная погода (+{avg_temp}°C), рекомендуется легкая куртка для вечерних прогулок."

    @classmethod
    def _get_offline_fallback(cls, city_name: str, country: str, days: int, start=None) -> Dict[str, Any]:
        today = start or datetime.now()
        forecast_items = []

        norm = city_name.lower()
        if "дубай" in norm:
            base_max, base_min, cond = 30.5, 21.0, "Ясно, солнечно ☀️"
        elif "пхукет" in norm:
            base_max, base_min, cond = 31.0, 24.5, "В основном ясно 🌤️"
        elif "шерегеш" in norm:
            base_max, base_min, cond = -8.0, -15.0, "Снегопад 🌨️"
        elif "сочи" in norm:
            base_max, base_min, cond = 17.0, 10.0, "Переменная облачность ⛅"
        elif "алтай" in norm:
            base_max, base_min, cond = 2.0, -6.0, "Преимущественно ясно 🌤️"
        elif "мальдивы" in norm:
            base_max, base_min, cond = 30.0, 26.0, "Тропическое солнце ☀️"
        else:
            base_max, base_min, cond = 15.0, 8.0, "Переменная облачность ⛅"

        for dest in load_catalog("destinations"):
            if dest["name"].lower() == norm:
                climate = dest.get("climate_by_month", {}).get(str(today.month), {})
                base_max = climate.get("avg_day_temp", base_max)
                base_min = climate.get("avg_night_temp", base_min)
                cond = climate.get("description", "Климатическая оценка")
                break

        for i in range(days):
            day_date = today + timedelta(days=i)
            forecast_items.append({
                "date": day_date.strftime("%Y-%m-%d"),
                "temp_max": base_max,
                "temp_min": base_min,
                "precipitation_mm": 0.0,
                "condition": cond,
                "is_favorable_for_vacation": True
            })

        return {
            "city": city_name,
            "country": country,
            "source": "Offline Climate Fallback",
            "verdict": "Климатическая оценка, не точный прогноз: " + cls._build_verdict(city_name, base_max, 0.0),
            "forecast": forecast_items
        }
