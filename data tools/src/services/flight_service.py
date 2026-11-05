import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.services.catalog_locations import destination_id
from src.services.database import load_catalog
from src.services.schedule_routes import parse_route, stamp
from src.services.departure_cities import CITIES, normalize_origin
from src.services.travel_party import normalize_party, party_factors

ORIGIN_IATA = {
    "москва": "MOW",
    "санкт-петербург": "LED",
    "петербург": "LED",
    "спб": "LED",
    "питер": "LED",
    "екатеринбург": "SVX",
    "новосибирск": "OVB",
    "казань": "KZN",
    "сочи": "AER",
    "калининград": "KGD",
    "самара": "KUF",
    "нижний новгород": "GOJ",
    "уфа": "UFA",
    "красноярск": "KJA",
    "минеральные воды": "MRV",
    "иркутск": "IKT",
    "владивосток": "VVO",
    "махачкала": "MCX",
}

AIRPORT_SHORT = {
    "шереметьево": "SVO",
    "домодедово": "DME",
    "внуково": "VKO",
    "жуковский": "ZIA",
    "пулково": "LED",
}


class FlightService:
    _segment_cache: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    _key_index: int = 0

    @classmethod
    def _load_data(cls) -> Dict[str, Any]:
        return load_catalog("routes")

    @classmethod
    def _find_route(cls, destination: str) -> Optional[Dict[str, Any]]:
        routes = cls._load_data()
        key = destination_id(destination)
        if key:
            return routes.get(key)
        value = (destination or "").strip().lower()
        return next((route for route in routes.values() if route["city"].lower() == value), None)

    @classmethod
    def _get_yandex_keys(cls) -> List[str]:
        raw = os.environ.get("YANDEX_RASP_API_KEYS") or os.environ.get("YANDEX_RASP_API_KEY") or ""
        return [k.strip() for k in raw.split(",") if k.strip()]

    @classmethod
    def _yandex_enabled(cls, preview=False, cache_key=None):
        if os.environ.get("OFFLINE_MODE") == "1":
            return False
        flag = os.environ.get("YANDEX_RASP_ENABLED", "true").strip().lower()
        if flag in ("false", "0", "no", "off"):
            return False
        return bool(cls._get_yandex_keys())

    @classmethod
    def _origin_iata(cls, origin):
        return CITIES[normalize_origin(origin)][0]

    @classmethod
    def _fetch_yandex_segments(cls, from_iata, to_iata, date_str):
        cache_key = (from_iata, to_iata, date_str)
        cached = cls._segment_cache.get(cache_key)
        if isinstance(cached, tuple) and time.monotonic() - cached[0] < 600:
            return cached[1]
        keys = cls._get_yandex_keys()
        if not keys:
            return None
        start_index = cls._key_index % len(keys)
        deadline = time.monotonic() + 10
        for attempt in range(len(keys)):
            idx = (start_index + attempt) % len(keys)
            segments, offset = [], 0
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    params = urllib.parse.urlencode({"format": "json", "from": from_iata,
                        "to": to_iata, "lang": "ru_RU", "date": date_str, "system": "iata",
                        "transfers": "true", "limit": 100, "offset": offset})
                    req = urllib.request.Request("https://api.rasp.yandex-net.ru/v3.0/search/?" + params,
                        headers={"Authorization": keys[idx]})
                    with urllib.request.urlopen(req, timeout=min(3, remaining)) as response:
                        data = json.loads(response.read().decode("utf-8"))
                    page = data.get("segments")
                    if not isinstance(page, list):
                        raise ValueError("Malformed schedule response")
                    segments.extend(page)
                    total = int((data.get("pagination") or {}).get("total", len(segments)))
                    if len(segments) >= total or not page:
                        break
                    offset += len(page)
                    if offset >= 1000:
                        return None  # Do not cache incomplete results as 'no flights'.
                cls._key_index = idx
                if len(cls._segment_cache) >= 500:
                    cls._segment_cache.clear()
                cls._segment_cache[cache_key] = (time.monotonic(), segments)
                return segments
            except urllib.error.HTTPError as exc:
                if exc.code == 400:
                    return None
            except (OSError, ValueError, TypeError):
                pass
        cls._key_index = (start_index + 1) % len(keys)
        return None

    @classmethod
    def _parse_segment(cls, seg, default_date, default_hours=0):
        return parse_route(seg, default_date)

    @classmethod
    def _format_origin_label(cls, origin: str, station_title: str, origin_iata: str) -> str:
        st_lower = (station_title or "").strip().lower()
        code = AIRPORT_SHORT.get(st_lower, origin_iata)
        if station_title and station_title.lower() != origin.lower():
            return f"{origin} ({station_title}, {code})"
        return f"{origin} ({code})"

    @classmethod
    def _build_yandex_flights(cls, origin, route, date, return_date, passengers,
            departure_after, departure_before, return_departure_after, return_departure_before,
            return_arrival_after, return_arrival_before, fits_fn):
        origin_code = cls._origin_iata(origin)
        raw_outbound = cls._fetch_yandex_segments(origin_code, route["airport_code"], date)
        if raw_outbound is None:
            return None
        parsed = [parse_route(seg, date) for seg in raw_outbound]
        parsed = [p for p in parsed if p and fits_fn(p["departure_time"], departure_after, departure_before)]
        if not parsed:
            return []
        returning = None
        if return_date:
            raw_return = cls._fetch_yandex_segments(route["airport_code"], origin_code, return_date)
            if raw_return is None:
                return None  # The whole itinerary uses the clearly marked demo fallback.
            returns = [parse_route(seg, return_date) for seg in raw_return]
            returns = [p for p in returns if p and fits_fn(p["departure_time"], return_departure_after, return_departure_before)
                       and fits_fn(p["arrival_time"], return_arrival_after, return_arrival_before)
                       and (not (return_arrival_after or return_arrival_before) or p["arrival_date"] == return_date)]
            if not returns:
                return []
            returning = min(returns, key=lambda p: (p["route_rank"], p["departure_time"] < "13:00", p["duration_hours"]))
        flights, seen = [], set()
        for info in sorted(parsed, key=lambda p: (p["route_rank"], p["departure_time"])):
            if returning and stamp(returning["departure_iso"]) <= stamp(info["arrival_iso"]):
                continue
            key = (info["departure_iso"], info["flight_number"])
            if key in seen:
                continue
            seen.add(key)
            # Schedule availability is real; fares and baggage remain demo data.
            multiplier = 0.78 if info["departure_time"] < "07:00" else 1.15 if info["departure_time"] >= "11:00" else 1
            multiplier *= 1 + 0.15 * (len(info["legs"]) - 1)
            price = round(route.get("base_price_rub", 8500) * multiplier)
            flight = {**info, "origin": cls._format_origin_label(origin, info["from_station"], origin_code),
                      "destination": f"{route['city']} ({info['to_station']})", "source": "Yandex Raspisaniya API",
                      "baggage": {"included": multiplier >= 1, "weight_kg": 23 if multiplier >= 1 else 0, "carry_on_kg": 10},
                      "price_per_passenger": price, "total_price": price * passengers,
                      "tag": "Расписание Яндекса · демонстрационная цена"}
            if returning:
                flight["price_includes_return"] = True
                flight["return_flight"] = {**returning,
                    "origin": cls._format_origin_label(route["city"], returning["from_station"], route["airport_code"]),
                    "destination": cls._format_origin_label(origin, returning["to_station"], origin_code)}
                flight["route_rank"] = max(info["route_rank"], returning["route_rank"])
            flights.append(flight)
        return flights

    @classmethod
    def search(
        cls,
        origin: str = "Москва",
        destination: str = "Сочи",
        date: str = "2026-11-15",
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
        children_ages: Optional[List[int]] = None,
        arrival_after: Optional[str] = None,
        arrival_before: Optional[str] = None,
    ) -> Dict[str, Any]:
        origin = normalize_origin(origin)
        party_patch = {"children_ages": children_ages or []}
        party_patch["adults" if adults is not None else "passengers"] = adults if adults is not None else passengers
        party = normalize_party({}, party_patch)
        passengers = party["passengers"]
        route = cls._find_route(destination)
        if not route:
            return {"origin": origin, "destination": destination, "date": date,
                    "passengers": passengers, "flights": [], "transfers": [],
                    "error": "В демокаталоге нет маршрута для этого направления"}

        if origin == route["city"]:
            return {"flights": [], "transfers": [], "error": "Город вылета совпадает с направлением."}
        route = dict(route)
        factor, duration_delta = CITIES[origin][1:]
        route["base_price_rub"] = round(route.get("base_price_rub", 8500) * factor)
        flight_hours = route.get("flight_duration_hours", 3.5) + duration_delta
        base_price = route.get("base_price_rub", 8500)
        airlines = route.get("airlines", [])
        if not return_date and any((return_departure_after, return_departure_before, return_arrival_after, return_arrival_before)):
            return {"origin": origin, "destination": route["city"], "date": date,
                    "passengers": passengers, "flights": [], "transfers": [],
                    "error": "Укажите дату возвращения для подбора обратного рейса по времени."}

        def fits(stamp, lower, upper):
            return (lower is None or stamp >= lower) and (upper is None or stamp <= upper)

        origin_code = cls._origin_iata(origin)
        cache_key = (origin_code, route["airport_code"], date)
        flights = None
        if cls._yandex_enabled(preview=preview, cache_key=cache_key):
            flights = cls._build_yandex_flights(
                origin=origin,
                route=route,
                date=date,
                return_date=return_date,
                passengers=passengers,
                departure_after=departure_after,
                departure_before=departure_before,
                return_departure_after=return_departure_after,
                return_departure_before=return_departure_before,
                return_arrival_after=return_arrival_after,
                return_arrival_before=return_arrival_before,
                fits_fn=fits,
            )

        if flights is None:
            # Синтетический фоллбэк (offline / тестовый режим / дата вне диапазона API)
            flights = []

            airline_1 = airlines[0] if airlines else {"name": "Аэрофлот", "code": "SU"}
            dep_dt1 = datetime.strptime(f"{date} 07:30", "%Y-%m-%d %H:%M")
            arr_dt1 = dep_dt1 + timedelta(hours=flight_hours)
            flights.append({
                "flight_number": f"{airline_1.get('code', 'SU')}-{1120}",
                "airline": airline_1.get("name"),
                "origin": f"{origin} ({origin_code})",
                "destination": f"{route['city']} ({route['airport_code']})",
                "departure_time": dep_dt1.strftime("%H:%M"),
                "arrival_time": arr_dt1.strftime("%H:%M"),
                "duration_hours": flight_hours,
                "is_direct": True,
                "baggage": {
                    "included": True,
                    "weight_kg": 23,
                    "carry_on_kg": 10
                },
                "price_per_passenger": base_price,
                "total_price": base_price * passengers,
                "tag": "Идеально к заселению (14:00)"
            })

            airline_2 = airlines[1] if len(airlines) > 1 else airline_1
            dep_dt2 = datetime.strptime(f"{date} 12:45", "%Y-%m-%d %H:%M")
            arr_dt2 = dep_dt2 + timedelta(hours=flight_hours)
            flights.append({
                "flight_number": f"{airline_2.get('code', 'S7')}-{2045}",
                "airline": airline_2.get("name"),
                "origin": f"{origin} ({origin_code})",
                "destination": f"{route['city']} ({route['airport_code']})",
                "departure_time": dep_dt2.strftime("%H:%M"),
                "arrival_time": arr_dt2.strftime("%H:%M"),
                "duration_hours": flight_hours,
                "is_direct": True,
                "baggage": {
                    "included": True,
                    "weight_kg": 20,
                    "carry_on_kg": 10
                },
                "price_per_passenger": int(base_price * 1.15),
                "total_price": int(base_price * 1.15) * passengers,
                "tag": "Комфортный дневной вылет"
            })

            airline_3 = airlines[-1] if airlines else airline_1
            dep_dt3 = datetime.strptime(f"{date} 06:10", "%Y-%m-%d %H:%M")
            arr_dt3 = dep_dt3 + timedelta(hours=flight_hours)
            flights.append({
                "flight_number": f"{airline_3.get('code', 'DP')}-{301}",
                "airline": airline_3.get("name"),
                "origin": f"{origin} ({origin_code})",
                "destination": f"{route['city']} ({route['airport_code']})",
                "departure_time": dep_dt3.strftime("%H:%M"),
                "arrival_time": arr_dt3.strftime("%H:%M"),
                "duration_hours": flight_hours,
                "is_direct": True,
                "baggage": {
                    "included": False,
                    "weight_kg": 0,
                    "carry_on_kg": 10,
                    "note": "Багаж 10 кг оплачивается отдельно (+1800 руб)"
                },
                "price_per_passenger": int(base_price * 0.78),
                "total_price": int(base_price * 0.78) * passengers,
                "tag": "Самый выгодный тариф"
            })

            flights = [f for f in flights if fits(f["departure_time"], departure_after, departure_before)]
            if return_date:
                returning = []
                for stamp in route.get("return_departures", ["18:30", "14:00", "09:00"]):
                    departure = datetime.strptime(f"{return_date} {stamp}", "%Y-%m-%d %H:%M")
                    arrival = departure + timedelta(hours=flight_hours)
                    if not fits(stamp, return_departure_after, return_departure_before):
                        continue
                    if not fits(arrival.strftime("%H:%M"), return_arrival_after, return_arrival_before):
                        continue
                    if (return_arrival_after or return_arrival_before) and arrival.date().isoformat() != return_date:
                        continue
                    returning.append((departure, arrival))
                if not returning:
                    flights = []
                else:
                    departure, arrival = returning[0]
                    for flight in flights:
                        flight["date"] = date
                        flight["arrival_date"] = (datetime.strptime(f"{date} {flight['departure_time']}", "%Y-%m-%d %H:%M") + timedelta(hours=flight_hours)).date().isoformat()
                        flight["price_includes_return"] = True
                        flight["return_flight"] = {
                            "flight_number": flight["flight_number"] + "-R", "airline": flight["airline"],
                            "origin": flight["destination"], "destination": flight["origin"],
                            "date": return_date, "arrival_date": arrival.date().isoformat(),
                            "departure_time": departure.strftime("%H:%M"), "arrival_time": arrival.strftime("%H:%M"),
                            "duration_hours": flight_hours,
                        }

        flights = [f for f in flights if fits(f["arrival_time"], arrival_after, arrival_before)
                   and (not (arrival_after or arrival_before) or f.get('arrival_date', date) == date)]
        for flight in flights:
            flight["party"] = party
            flight["total_price"] = round(flight["price_per_passenger"] * party_factors(party["adults"], party["children_ages"])["fare_units"])
            flight.setdefault("source", "Демонстрационное расписание")
            flight.setdefault("route_rank", 0)
        if not flights:
            return {"origin": origin, "destination": route["city"], "date": date,
                    "passengers": passengers, "flights": [], "transfers": [],
                    "error": "Нет подходящих билетов с подтверждённым маршрутом на указанные даты и время. Попробуйте другое время вылета или возвращения."}

        transfers = []
        if need_transfer:
            raw_transfers = route.get("transfers", [])
            for t in raw_transfers:
                transfers.append({
                    "type": t.get("type"),
                    "vehicle": t.get("vehicle"),
                    "capacity_passengers": t.get("capacity_passengers"),
                    "capacity_luggage": t.get("capacity_luggage"),
                    "duration_minutes": t.get("duration_minutes"),
                    "price_rub": t.get("price_rub"),
                    "child_seat_available": t.get("child_seat_available"),
                    "pet_friendly": t.get("pet_friendly"),
                    "meet_with_sign": t.get("meet_with_sign"),
                    "description": f"Встреча с именной табличкой в зоне прилета {route['airport_code']}. Помощь с багажом, кондиционер."
                })

        best_flight = flights[0]
        transfer_dur = transfers[0]["duration_minutes"] if transfers else 45
        arr_h, arr_m = map(int, best_flight["arrival_time"].split(":"))

        # Прибытие в отель: рейс + 35 мин на багаж + трансфер.
        baggage_time = 35
        total_after_landing = baggage_time + transfer_dur
        hotel_arr_m = (arr_m + total_after_landing) % 60
        hotel_arr_h = (arr_h + (arr_m + total_after_landing) // 60) % 24
        est_arrival_str = f"{hotel_arr_h:02d}:{hotel_arr_m:02d}"

        timing_analysis = {
            "flight_arrival": best_flight["arrival_time"],
            "transfer_duration_minutes": transfer_dur,
            "estimated_hotel_arrival": est_arrival_str,
            "hotel_checkin_time": hotel_checkin_time,
            "status": "perfect_match",
            "message": f"Рейс {best_flight['flight_number']} прилетает в {best_flight['arrival_time']}. С учетом получения багажа и трансфера ({transfer_dur} мин) вы прибудете в отель в ~{est_arrival_str}. Заезд начинается в {hotel_checkin_time} — вы заселяетесь практически без ожидания!"
        }

        return {
            "origin": origin,
            "destination": route["city"],
            "airport_code": route["airport_code"],
            "date": date,
            "passengers": passengers,
            "flights": flights,
            "transfers": transfers,
            "timing_analysis": timing_analysis
        }
