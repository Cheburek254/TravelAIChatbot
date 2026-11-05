from datetime import datetime, date, timedelta, timezone
from typing import Any, Dict, List, Optional
import random
from src.services.travel_party import party_factors
from src.services.accommodation import validate_room_count
from src.services.schedule_routes import MODES


def format_duration(hours):
    minutes = max(0, round(float(hours) * 60))
    hours, minutes = divmod(minutes, 60)
    return f'{hours} ч {minutes} мин'

AMENITY_LABELS: Dict[str, str] = {
    "6_pools": "6 бассейнов",
    "6_restaurants": "6 ресторанов",
    "ac": "Кондиционер",
    "all_inclusive": "Всё включено",
    "animation": "Анимация",
    "banya_on_lake": "Баня на озере",
    "bar": "Бар",
    "bbq": "Зона барбекю",
    "beach_transfer": "Трансфер на пляж",
    "beachfront": "У самого пляжа",
    "bike_rental": "Прокат велосипедов",
    "bosphorus_view": "Вид на Босфор",
    "concierge": "Консьерж-сервис",
    "diving_center": "Дайвинг-центр",
    "fine_dining": "Высокая кухня",
    "fireplace": "Камин",
    "first_line_beach": "Первая линия пляжа",
    "fitness": "Фитнес-зал",
    "gym": "Тренажёрный зал",
    "heated_pool": "Подогреваемый бассейн",
    "helipad": "Вертолётная площадка",
    "historic_building": "Историческое здание",
    "indoor_pool": "Крытый бассейн",
    "infinity_pool": "Инфинити-бассейн",
    "jungle_pool": "Бассейн в джунглях",
    "kids_club": "Детский клуб",
    "kids_waterpark": "Детский аквапарк",
    "lake_view": "Вид на озеро",
    "mountain_view": "Вид на горы",
    "nightclub": "Ночной клуб",
    "ocean_view": "Вид на океан",
    "outdoor_heated_pool": "Тёплый открытый бассейн",
    "outdoor_infinity_pool": "Открытый инфинити-бассейн",
    "parking": "Парковка",
    "pool": "Бассейн",
    "private_beach": "Собственный пляж",
    "private_lagoon": "Собственная лагуна",
    "restaurant": "Ресторан",
    "restaurants": "Рестораны",
    "river_view": "Вид на реку",
    "sauna": "Сауна",
    "sea_view_balcony": "Балкон с видом на море",
    "ski_in_ski_out": "Ski-in / Ski-out",
    "ski_storage": "Лыжехранилище",
    "ski_transfer": "Трансфер к подъёмнику",
    "spa": "СПА-комплекс",
    "speedboat_transfer": "Трансфер на катере",
    "swimming_pool": "Бассейн",
    "tennis": "Теннисный корт",
    "terrace": "Терраса",
    "terrace_restaurant": "Панорамный ресторан",
    "transfer": "Трансфер",
    "tropical_garden": "Тропический сад",
    "valet_parking": "Валет-паркинг",
    "water_villa": "Водная вилла",
    "wellness": "Велнес-зона",
    "wifi": "Бесплатный Wi-Fi",
    "yoga": "Йога-терраса",
}


def format_amenity_tag(tag: str) -> str:
    raw = str(tag or "").strip()
    if raw in AMENITY_LABELS:
        return AMENITY_LABELS[raw]
    lower = raw.lower()
    if lower in AMENITY_LABELS:
        return AMENITY_LABELS[lower]
    return raw.replace("_", " ").capitalize()


class TimelineValidator:
    @staticmethod
    def _time_to_minutes(time_str: str) -> int:
        parts = (time_str or "14:00").strip().split(":")
        h = int(parts[0]) if parts and parts[0].isdigit() else 14
        m = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        return h * 60 + m

    @staticmethod
    def _minutes_to_time(total_minutes: int) -> str:
        norm = total_minutes % (24 * 60)
        h = norm // 60
        m = norm % 60
        return f"{h:02d}:{m:02d}"

    @classmethod
    def validate_timeline(
        cls,
        flight: Dict[str, Any],
        transfer: Dict[str, Any],
        hotel: Dict[str, Any],
        return_departure_time: str = "18:30",
        baggage_claim_minutes: int = 35,
        layover_minutes: Optional[int] = None,
        room_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        return_departure_time = (flight.get("return_flight") or {}).get("departure_time", return_departure_time)
        arr_str = flight.get("arrival_time", "12:00")
        dep_str = flight.get("departure_time", "08:30")
        transfer_min = int(transfer.get("duration_minutes", 40))
        checkin_str = hotel.get("checkin_time", "14:00")
        checkout_str = hotel.get("checkout_time", "12:00")
        early_available = bool(hotel.get("early_checkin_available", True))
        late_available = bool(hotel.get("late_checkout_available", True))
        price_per_night = int(hotel.get("price_per_night", 9000))
        party = flight.get('party')
        if party:
            price_per_night *= validate_room_count(party['adults'], party['children_ages'], room_count)

        arr_min = cls._time_to_minutes(arr_str)
        hotel_arrival_min = arr_min + baggage_claim_minutes + transfer_min
        hotel_arrival_str = cls._minutes_to_time(hotel_arrival_min)
        checkin_min = cls._time_to_minutes(checkin_str)

        wait_minutes = checkin_min - (hotel_arrival_min % (24 * 60))
        is_night_arrival = (hotel_arrival_min % (24 * 60)) < 7 * 60

        early_checkin_needed = wait_minutes > 90 or is_night_arrival
        early_checkin_fee_rub = 0
        alerts: List[str] = []
        recommendations: List[str] = []

        if is_night_arrival:
            status = "night_arrival_conflict"
            if early_available:
                early_checkin_fee_rub = int(round(price_per_night * 0.5, -2))
                msg = (
                    f"Ночной/ранний прилёт ({arr_str}): в отеле будете в ~{hotel_arrival_str}, "
                    f"а стандартное заселение в {checkin_str} (ожидание {max(wait_minutes, 60) // 60} ч). "
                    f"Доступен гарантированный ранний заезд (+{early_checkin_fee_rub:,} ₽) или бесплатная комната багажа.".replace(",", " ")
                )
                recommendations.append(f"Подключить гарантированный ранний заезд (+{early_checkin_fee_rub:,} ₽)".replace(",", " "))
            else:
                msg = (
                    f"Ранний прилёт в {arr_str} (в отеле ~{hotel_arrival_str}), заселение с {checkin_str}. "
                    f"Рекомендуем оставить вещи в бесплатной камере хранения отеля и посетить завтрак/СПА."
                )
                recommendations.append("Использовать камеру хранения багажа на ресепшене до 14:00")
            alerts.append(msg)
        elif wait_minutes > 90:
            status = "early_arrival_wait"
            if early_available:
                early_checkin_fee_rub = int(round(price_per_night * 0.5, -2))
                msg = (
                    f"Прибытие в отель в ~{hotel_arrival_str}, стандартный заезд в {checkin_str} "
                    f"(разрыв {wait_minutes // 60} ч {wait_minutes % 60} мин). Можно оставить багаж бесплатно или оформить ранний заезд (+{early_checkin_fee_rub:,} ₽).".replace(",", " ")
                )
            else:
                msg = (
                    f"Прибытие в отель в ~{hotel_arrival_str}, заезд в {checkin_str}. "
                    f"До заселения ({wait_minutes // 60} ч) доступна бесплатная камера хранения."
                )
            alerts.append(msg)
        elif wait_minutes < -180:
            status = "late_arrival_warn"
            msg = (
                f"Позднее прибытие в отель (~{hotel_arrival_str}). "
                f"Перед поездкой подтвердите в отеле поздний заезд."
            )
            alerts.append(msg)
        else:
            status = "perfect_match"
            msg = (
                f"Рейс {flight.get('flight_number', 'SU-1120')} прилетает в {arr_str}. "
                f"С учётом багажа ({baggage_claim_minutes} мин) и трансфера ({transfer_min} мин) вы будете в отеле в ~{hotel_arrival_str} — идеально ко времени заезда ({checkin_str})!"
            )

        checkout_min = cls._time_to_minutes(checkout_str)
        ret_dep_min = cls._time_to_minutes(return_departure_time)
        AirportBufferMin = 150
        pickup_min = ret_dep_min - AirportBufferMin - transfer_min
        pickup_str = cls._minutes_to_time(pickup_min)
        checkout_gap_min = pickup_min - checkout_min

        late_checkout_needed = checkout_gap_min > 180
        late_checkout_fee_rub = 0
        if late_checkout_needed:
            if late_available:
                late_checkout_fee_rub = int(round(price_per_night * 0.5, -2))
                checkout_note = (
                    f"Выезд из номера в {checkout_str}, а трансфер в аэропорт в {pickup_str} под рейс в {return_departure_time}. "
                    f"Доступен поздний выезд (+{late_checkout_fee_rub:,} ₽) или бесплатная камера хранения багажа.".replace(",", " ")
                )
            else:
                checkout_note = (
                    f"Выезд в {checkout_str}, трансфер в аэропорт в {pickup_str} (рейс {return_departure_time}). "
                    f"Камера хранения багажа в отеле бесплатна до вечера."
                )
            alerts.append(checkout_note)
        else:
            checkout_note = f"Выезд в {checkout_str}, подача обратного трансфера в {pickup_str} ко времени вылета ({return_departure_time})."

        if not flight.get("is_direct", True) and layover_minutes is not None and layover_minutes < 75:
            alerts.append(f"Риск короткой пересадки ({layover_minutes} мин): рекомендуем прямой рейс или запас от 90 минут.")

        return {
            "flight_departure": dep_str,
            "flight_arrival": arr_str,
            "baggage_claim_minutes": baggage_claim_minutes,
            "transfer_duration_minutes": transfer_min,
            "estimated_hotel_arrival": hotel_arrival_str,
            "hotel_checkin_time": checkin_str,
            "hotel_checkout_time": checkout_str,
            "return_transfer_pickup": pickup_str,
            "return_flight_departure": return_departure_time,
            "wait_before_checkin_minutes": max(0, wait_minutes),
            "early_checkin_needed": early_checkin_needed,
            "early_checkin_available": early_available,
            "early_checkin_fee_rub": early_checkin_fee_rub,
            "late_checkout_needed": late_checkout_needed,
            "late_checkout_available": late_available,
            "late_checkout_fee_rub": late_checkout_fee_rub,
            "status": status,
            "timeline_valid": True,
            "conflict_resolved": True,
            "message": msg,
            "checkout_message": checkout_note,
            "alerts": alerts,
            "recommendations": recommendations,
        }


class FairPriceCalculator:
    CURRENCY_RATES_TO_RUB = {
        "RUB": 1.0,
        "AED": 27.0,
        "USD": 96.0,
        "EUR": 104.0,
        "THB": 2.8,
    }

    RESORT_FEE_PER_NIGHT_PER_ADULT_RUB = {
        "сочи": 100,
        "красная поляна": 100,
        "санкт-петербург": 100,
        "кисловодск": 100,
        "дубай": 400,
    }

    @classmethod
    def calculate_fair_price(
        cls,
        hotel: Dict[str, Any],
        flight: Dict[str, Any],
        transfer: Dict[str, Any],
        nights: int = 4,
        passengers: int = 2,
        with_pet: bool = False,
        has_meal_addon: bool = False,
        include_early_checkin: bool = False,
        daily_commute_cost_rub: int = 0,
        room_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        price_per_night = int(hotel.get("price_per_night", 8500))
        party = flight.get("party") or {"adults": passengers, "children_ages": []}
        factors = party_factors(party["adults"], party["children_ages"])
        rooms = validate_room_count(party['adults'], party['children_ages'], room_count)
        hotel_base_rub = price_per_night * max(nights, 1) * rooms

        flight_base_rub = int(flight.get("total_price") or (int(flight.get("price_per_passenger", 9000)) * passengers))
        transfer_rub = int(transfer.get("price_rub", 2000))
        station_changes = sum(layover.get("stationChange", False) for layover in flight.get("layovers", [])) + sum(layover.get("stationChange", False) for layover in (flight.get("return_flight") or {}).get("layovers", []))
        connection_transfer_rub = 1500 * station_changes

        baggage_info = flight.get("baggage") or {}
        baggage_included = bool(baggage_info.get("included", True))
        baggage_fee_rub = 0 if baggage_included else 1800 * factors["seats"]

        pet_info = hotel.get("pet_friendly") or {}
        pet_allowed = bool(pet_info.get("allowed", False))
        raw_pet_fee = pet_info.get("fee_per_stay")
        if raw_pet_fee is None:
            raw_pet_fee = pet_info.get("extra_fee_rub", 0)
        pet_fee_rub = int(raw_pet_fee or 0) if (with_pet and pet_allowed) else 0

        dest_norm = (hotel.get("destination_name") or hotel.get("destination_id") or "").lower()
        resort_rate = 0
        for city_key, fee_val in cls.RESORT_FEE_PER_NIGHT_PER_ADULT_RUB.items():
            if city_key in dest_norm:
                resort_rate = fee_val
                break
        resort_fee_rub = resort_rate * max(nights, 1) * party["adults"]

        meal_addon_rub = round(2600 * factors["meal_units"]) if has_meal_addon else 0
        early_checkin_rub = int(round(price_per_night * rooms * 0.5, -2)) if include_early_checkin else 0
        commute_total_rub = daily_commute_cost_rub * max(nights, 1)

        deposit_info = hotel.get("deposit") or {}
        deposit_required = bool(deposit_info.get("required", False))
        deposit_raw_amt = float(deposit_info.get("amount") or deposit_info.get("amount_rub") or 0)
        deposit_curr = str(deposit_info.get("currency", "RUB")).upper()
        rate = cls.CURRENCY_RATES_TO_RUB.get(deposit_curr, 1.0)
        refundable_deposit_rub = int(round(deposit_raw_amt * rate)) if deposit_required else 0

        extras: List[Dict[str, Any]] = [
            {
                "name": f"Трансфер: {transfer.get('type', 'Комфорт')} ({transfer.get('vehicle', 'Седан')})",
                "price": transfer_rub,
            }
        ]

        if baggage_fee_rub > 0:
            extras.append({
                "name": f"Доплата за регистрируемый багаж ({factors['seats']} пасс. с местом)",
                "price": baggage_fee_rub,
            })
        if connection_transfer_rub:
            extras.append({"name": f"Перемещения между станциями / аэропортами ({station_changes}) — демотариф", "price": connection_transfer_rub})

        if pet_allowed and pet_fee_rub > 0:
            extras.append({
                "name": "Тариф «Питомец в номере» (pet-friendly пакет)",
                "price": pet_fee_rub,
            })

        if resort_fee_rub > 0:
            extras.append({
                "name": f"Курортный / туристический сбор ({nights} ноч.)",
                "price": resort_fee_rub,
            })

        if meal_addon_rub > 0:
            extras.append({
                "name": "Пакет питания: завтрак + ужин (Полупансион)",
                "price": meal_addon_rub,
            })

        if early_checkin_rub > 0:
            extras.append({
                "name": "Гарантированный ранний заезд",
                "price": early_checkin_rub,
            })

        if commute_total_rub > 0:
            extras.append({
                "name": f"Ежедневный трансфер до подъёмников ({nights} дн.)",
                "price": commute_total_rub,
            })

        extras_total_rub = sum(int(item["price"]) for item in extras)
        grand_total_rub = hotel_base_rub + flight_base_rub + extras_total_rub

        hidden_fees_summary: List[str] = []
        if not baggage_included:
            hidden_fees_summary.append(f"Тариф авиа без багажа: учтена доплата +{baggage_fee_rub:,} ₽".replace(",", " "))
        if refundable_deposit_rub > 0:
            hidden_fees_summary.append(
                f"Возвратный депозит при заселении: {refundable_deposit_rub:,} ₽ (замораживается и возвращается при выезде)".replace(",", " ")
            )
        else:
            hidden_fees_summary.append("Скрытых залогов и депозитов при заселении нет (0 ₽)")
        if resort_fee_rub > 0:
            hidden_fees_summary.append(f"Курортный сбор включён в расчёт: {resort_fee_rub:,} ₽".replace(",", " "))

        return {
            "hotel_base_rub": hotel_base_rub,
            "rooms": rooms,
            "demo_party_tariff": "До 2 лет: 10% авиатарифа без места; 2–11 лет: 75%; с 12 лет: 100%. Номер на 2 места, младенец без отдельного места. Питание: взрослый 2600 ₽, ребёнок от 2 лет 1300 ₽ за поездку; сбор только для взрослых.",
            "flight_base_rub": flight_base_rub,
            "transfer_rub": transfer_rub,
            "connection_transfer_rub": connection_transfer_rub,
            "baggage_fee_rub": baggage_fee_rub,
            "pet_fee_rub": pet_fee_rub,
            "resort_fee_rub": resort_fee_rub,
            "meal_addon_rub": meal_addon_rub,
            "early_checkin_rub": early_checkin_rub,
            "commute_total_rub": commute_total_rub,
            "extras_total_rub": extras_total_rub,
            "grand_total_rub": grand_total_rub,
            "refundable_deposit_rub": refundable_deposit_rub,
            "extras": extras,
            "hidden_fees_summary": hidden_fees_summary,
        }


class TradeoffAnalyzer:
    @classmethod
    def analyze_option(
        cls,
        option_key: str,
        hotel: Dict[str, Any],
        flight: Dict[str, Any],
        transfer: Dict[str, Any],
        timing: Dict[str, Any],
        pricing: Dict[str, Any],
        other_pricing: Optional[Dict[str, Any]] = None,
        other_hotel: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        this_total = int(pricing.get("grand_total_rub", 0))
        other_total = int(other_pricing.get("grand_total_rub", this_total)) if other_pricing else this_total
        price_diff = this_total - other_total

        rating = float(hotel.get("rating", 9.0))
        reviews = int(hotel.get("reviews_count", 300))
        dist_beach = hotel.get("distance_to_beach_m")
        dist_lift = hotel.get("distance_to_ski_lift_m")
        dist_center = float(hotel.get("distance_to_center_km") or 0.0)
        meal_desc = hotel.get("meal_description", "Завтрак по тарифу")
        pet_info = hotel.get("pet_friendly") or {}
        canc_info = hotel.get("cancellation_policy") or {}
        canc_desc = canc_info.get("description", "Бесплатная отмена за 48 часов") if isinstance(canc_info, dict) else str(canc_info)
        canc_type = canc_info.get("type", "free_cancellation") if isinstance(canc_info, dict) else "flexible"

        pros: List[str] = []
        if price_diff < -1000:
            walk_note = ""
            if dist_beach and dist_beach > 150:
                walk_min = max(5, int(round(dist_beach / 80)))
                walk_note = f", при этом до пляжа всего {walk_min} минут пешком ({dist_beach} м)"
            elif dist_lift and dist_lift > 200:
                walk_min = max(5, int(round(dist_lift / 80)))
                walk_note = f", до подъёмника {walk_min} минут ({dist_lift} м)"
            pros.append(f"Почему этот вариант: экономит {abs(price_diff):,} ₽ по сравнению с альтернативой{walk_note}".replace(",", " "))
        else:
            if dist_beach is not None and dist_beach <= 100:
                pros.append(f"Почему этот вариант: первая пляжная линия ({dist_beach} м до воды) и высокий рейтинг {rating}/10 ({reviews} отзывов)")
            elif dist_lift is not None and dist_lift <= 250:
                pros.append(f"Почему этот вариант: формат Ski-in/Ski-out ({dist_lift} м до подъёмника), рейтинг {rating}/10")
            else:
                pros.append(f"Почему этот вариант: проверенный рейтинг {rating}/10 ({reviews} отзывов) и {meal_desc.lower()}")

        if pet_info.get("allowed"):
            pros.append(f"Честный Pet-friendly (до {pet_info.get('max_weight_kg', 15)} кг): {pet_info.get('description', 'размещение с питомцем подтверждено')}")
        else:
            pros.append(f"Питание и сервис: {meal_desc}")

        pros.append(timing.get("message", "Стыковка рейса, трансфера и времени заселения проверена"))

        cons: List[str] = []
        risks: List[str] = []

        if price_diff > 1000:
            cons.append(f"Компромисс по бюджету: дороже второго варианта на {price_diff:,} ₽ за счёт локации и категории {hotel.get('stars', 4)}*".replace(",", " "))
        elif dist_beach and dist_beach > 150:
            walk_min = max(5, int(round(dist_beach / 80)))
            if price_diff < 0:
                cons.append(f"Компромисс: экономит {abs(price_diff):,} ₽, но придётся пройти {walk_min} минут ({dist_beach} м) до пляжа".replace(",", " "))
            else:
                cons.append(f"Компромисс по локации: до пляжа около {walk_min} минут пешком ({dist_beach} м)")
        elif dist_center > 5.0:
            cons.append(f"Компромисс по локации: до исторического центра {dist_center} км (около 20 минут на трансфере/такси)")

        if hotel.get("meal_type") == "RO":
            cons.append("Компромисс: питание не включено в базовый тариф номера (RO)")

        dep_rub = int(pricing.get("refundable_deposit_rub", 0))
        if dep_rub > 0:
            risk_dep = f"Риск/условие при заселении: требуется возвратный депозит {dep_rub:,} ₽".replace(",", " ")
            risks.append(risk_dep)
            cons.append(risk_dep)
        else:
            cons.append("Без возвратного залога на ресепшене (0 ₽ депозит)")

        baggage_info = flight.get("baggage") or {}
        if not baggage_info.get("included", True):
            risk_bag = "Риск тарифа перелёта: базовый билет только с ручной кладью 10 кг (багаж учтён отдельной строкой в смете)"
            risks.append(risk_bag)
            if len(cons) < 3:
                cons.append(risk_bag)

        if canc_type not in ("free_cancellation", "flexible"):
            risk_canc = f"Риск: невозвратный тариф ({canc_desc})"
            risks.append(risk_canc)
            if len(cons) < 3:
                cons.append(risk_canc)
        else:
            risk_canc = f"Условия отмены: {canc_desc}"
            risks.append(risk_canc)
            if len(cons) < 3:
                cons.append(risk_canc)

        why_this = pros[0]
        what_sacrificed = cons[0] if cons else "Без существенных компромиссов по локации и комфорту"
        risk_summary = risks[0] if risks else f"Условия отмены: {canc_desc}"

        return {
            "option_key": option_key,
            "why_this": why_this,
            "what_sacrificed": what_sacrificed,
            "risk_summary": risk_summary,
            "pros": pros[:3],
            "cons": cons[:3],
            "risks": risks,
        }


class BookingCartAssembler:
    @classmethod
    def assemble_timeline_steps(
        cls,
        origin: str,
        dest_name: str,
        nights: int,
        hotel: Dict[str, Any],
        flight: Dict[str, Any],
        transfer: Dict[str, Any],
        timing: Dict[str, Any],
        checkin_date: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        start = date.fromisoformat(checkin_date) if checkin_date else date.today() + timedelta(days=21)
        end = start + timedelta(days=nights)
        baggage_info = flight.get("baggage") or {}
        baggage_str = (
            f"Багаж {baggage_info.get('weight_kg', 20)} кг включён"
            if baggage_info.get("included", True)
            else "Ручная кладь 10 кг + докупленный багаж"
        )
        canc_raw = hotel.get("cancellation_policy")
        canc_text = (
            canc_raw.get("description", "Бесплатная отмена за 48 часов.")
            if isinstance(canc_raw, dict)
            else (str(canc_raw) if canc_raw else "Бесплатная отмена за 48 часов.")
        )

        steps = [
            {
                "time": f"{start:%d.%m.%Y}, {flight.get('departure_time', '09:30')}",
                "title": f"Вылет из г. {origin} ({flight.get('airline', 'Аэрофлот')} {flight.get('flight_number', 'SU-1120')})",
                "desc": f"{baggage_str} • Прямой рейс • Онлайн-регистрация открыта",
                "tag": "Авиабилет",
            },
            {
                "time": f"{start:%d.%m.%Y}, {flight.get('arrival_time', '13:15')}",
                "title": f"Встреча в аэропорту и трансфер ({transfer.get('duration_minutes', 40)} мин до отеля)",
                "desc": f"{transfer.get('description', 'Встреча с табличкой в зоне прилёта')} • Расчётное прибытие в отель ~{timing.get('estimated_hotel_arrival', '14:20')}",
                "tag": "Трансфер",
            },
            {
                "time": f"{start:%d.%m.%Y}, {hotel.get('checkin_time', '14:00')}",
                "title": f"Заселение в {hotel.get('name', 'Отель')} {hotel.get('stars', 4)}*",
                "desc": timing.get("message", "Стыковка времени прилёта и заселения проверена"),
                "tag": "Отель",
            },
            {
                "time": f"{end:%d.%m.%Y}, {hotel.get('checkout_time', '12:00')}",
                "title": "Выезд из отеля и обратный трансфер ко времени вылета",
                "desc": f"{timing.get('checkout_message', 'Камера хранения багажа доступна')} • {canc_text}",
                "tag": "Обратно",
            },
        ]
        returning = flight.get("return_flight")
        if returning:
            steps.append({"time": f"{end:%d.%m.%Y}, {returning['departure_time']}",
                          "title": f"Обратный вылет: {dest_name} → {origin} ({returning['flight_number']})",
                          "desc": f"Прибытие {returning['arrival_date']} в {returning['arrival_time']}. Демобилет включён в стоимость перелёта.",
                          "tag": "Авиабилет"})
        def leg_steps(legs, back=False):
            result = []
            for index, leg in enumerate(legs):
                departure = datetime.fromisoformat(leg["departure"])
                arrival = datetime.fromisoformat(leg["arrival"])
                result.append({"time": f"{departure:%d.%m.%Y, %H:%M}",
                    "title": f"{'Обратно: ' if back else ''}{MODES.get(leg['mode'], 'Транспорт')} {leg['number']}: {leg['from']['title']} → {leg['to']['title']}",
                    "desc": f"Прибытие {arrival:%d.%m.%Y, %H:%M} (UTC{arrival:%z}). {leg['carrier']}." + (" Далее пересадка по проверенному расписанию." if index < len(legs)-1 else ""),
                    "tag": "Транспорт"})
            return result
        arrival = datetime.fromisoformat(flight.get("arrival_iso") or f"{flight.get('arrival_date', start.isoformat())}T{flight.get('arrival_time', '13:15')}")
        hotel_arrival = arrival + timedelta(minutes=35 + int(transfer.get("duration_minutes", 40)))
        scheduled_checkin = datetime.fromisoformat(f"{start.isoformat()}T{hotel.get('checkin_time', '14:00')}").replace(tzinfo=arrival.tzinfo)
        if not timing.get('early_checkin_selected'):
            hotel_arrival = max(hotel_arrival, scheduled_checkin)
        steps[1]["time"] = arrival.strftime("%d.%m.%Y, %H:%M")
        steps[1]["title"] = "Прибытие и трансфер до отеля"
        steps[1]["desc"] = f"Демотрансфер от точки прибытия до отеля: {transfer.get('duration_minutes',40)} мин. Расчётное прибытие {hotel_arrival:%d.%m.%Y, %H:%M}."
        steps[2]["time"] = hotel_arrival.strftime("%d.%m.%Y, %H:%M")
        if flight.get("legs"):
            steps = leg_steps(flight["legs"]) + steps[1:]
        if returning and returning.get("legs"):
            steps = steps[:-1] + leg_steps(returning["legs"], back=True)
        for step in steps:
            if step.get("tag") == "Обратно":
                return_departure = datetime.fromisoformat((returning or {}).get("departure_iso") or f"{end.isoformat()}T{(returning or {}).get('departure_time','18:30')}")
                pickup = return_departure - timedelta(minutes=150 + int(transfer.get("duration_minutes",40)))
                checkout = datetime.fromisoformat(f"{end.isoformat()}T{hotel.get('checkout_time','12:00')}").replace(tzinfo=return_departure.tzinfo)
                step["time"] = min(checkout, pickup).strftime("%d.%m.%Y, %H:%M")
        return steps

    @classmethod
    def create_voucher_and_receipt(
        cls,
        trip: Optional[Dict[str, Any]] = None,
        total_price: Optional[int] = None,
    ) -> Dict[str, Any]:
        trip_data = trip or {}
        hotel_data = trip_data.get("hotel") or {}
        transport_data = trip_data.get("transport") or trip_data.get("flight") or {}
        extras_list = trip_data.get("extras") or []

        nights = int(hotel_data.get("nights", 4))
        price_per_night = int(hotel_data.get("pricePerNight", 8500))
        hotel_subtotal = price_per_night * nights
        transport_subtotal = int(transport_data.get("price", 18000))
        extras_subtotal = sum(int(item.get("price", 0)) for item in extras_list)
        computed_total = hotel_subtotal + transport_subtotal + extras_subtotal
        final_total = int(total_price) if (total_price and total_price > 0) else computed_total

        voucher_num = random.randint(1000000, 9999999)
        pnr_num = random.randint(100000, 999999)
        voucher_id = f"OST-{voucher_num}"
        pnr_code = f"AERO-{pnr_num}"

        line_items = [
            {
                "category": "transport",
                "title": f"{transport_data.get('type', 'Авиаперелёт')} ({transport_data.get('carrier', 'Аэрофлот')})",
                "amount_rub": transport_subtotal,
            },
            {
                "category": "hotel",
                "title": f"Проживание: {hotel_data.get('name', 'Отель')} ({nights} ноч.)",
                "amount_rub": hotel_subtotal,
            },
        ]
        for ex in extras_list:
            line_items.append({
                "category": "extra",
                "title": str(ex.get("name", "Дополнительная услуга")),
                "amount_rub": int(ex.get("price", 0)),
            })
        issued = datetime.now(timezone(timedelta(hours=3)))
        return {
            "status": "confirmed",
            "voucherId": voucher_id,
            "pnr": pnr_code,
            "total_price": final_total,
            "issued_at": issued.strftime("%d.%m.%Y %H:%M (МСК)"),
            "issued_at_iso": issued.isoformat(),
            "loyalty_points_earned": max(150, (final_total * 15 + 500) // 1000),
            "receipt": {
                "receipt_id": f"CHK-{voucher_num}",
                "currency": "RUB",
                "transport_subtotal_rub": transport_subtotal,
                "hotel_subtotal_rub": hotel_subtotal,
                "extras_subtotal_rub": extras_subtotal,
                "grand_total_rub": final_total,
                "line_items": line_items,
            },
            "voucher": {
                "voucher_id": voucher_id,
                "pnr": pnr_code,
                "title": trip_data.get("title", "План поездки"),
                "destination": trip_data.get("destination", "Россия"),
                "dates": trip_data.get("dates", "15 ноября — 19 ноября"),
                "hotel_name": hotel_data.get("name", "Отель"),
                "hotel_address": hotel_data.get("address", ""),
                "pet_friendly": bool(hotel_data.get("petFriendly", False)),
                "travellers": trip_data.get("travellers", {"passengers": 2, "withPet": False}),
                "timeline": trip_data.get("timeline", []),
            },
        }


class LogisticsAndTradeoffEngine:
    @classmethod
    def build_validated_frontend_options(
        cls,
        origin: str,
        dest_name: str,
        nights: int,
        passengers: int,
        hotel_a: Dict[str, Any],
        hotel_b: Dict[str, Any],
        flight_a: Dict[str, Any],
        flight_b: Dict[str, Any],
        transfer_a: Dict[str, Any],
        transfer_b: Dict[str, Any],
        weather: Dict[str, Any],
        photo_map: Dict[str, List[str]],
        default_images: List[str],
        with_pet: bool = False,
        has_meal_addon: bool = False,
        checkin_date: Optional[str] = None,
        include_early_checkin: bool = False,
        room_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        timing_a = TimelineValidator.validate_timeline(flight=flight_a, transfer=transfer_a, hotel=hotel_a, room_count=room_count)
        timing_b = TimelineValidator.validate_timeline(flight=flight_b, transfer=transfer_b, hotel=hotel_b, room_count=room_count)

        pricing_a = FairPriceCalculator.calculate_fair_price(
            hotel=hotel_a,
            flight=flight_a,
            transfer=transfer_a,
            nights=nights,
            passengers=passengers,
            with_pet=with_pet,
            has_meal_addon=has_meal_addon,
            include_early_checkin=include_early_checkin,
            room_count=room_count,
        )
        pricing_b = FairPriceCalculator.calculate_fair_price(
            hotel=hotel_b,
            flight=flight_b,
            transfer=transfer_b,
            nights=nights,
            passengers=passengers,
            with_pet=with_pet,
            has_meal_addon=has_meal_addon,
            include_early_checkin=include_early_checkin,
            room_count=room_count,
        )

        if include_early_checkin:
            for timing, pricing in ((timing_a, pricing_a), (timing_b, pricing_b)):
                timing['early_checkin_selected'] = True
                timing['message'] = f"Ранний заезд включён в демосмету: {pricing['early_checkin_rub']:,} ₽. Заселение по расчётному времени прибытия в отель.".replace(',', ' ')
        same_hotel = hotel_a.get("id") == hotel_b.get("id")
        tradeoff_a = TradeoffAnalyzer.analyze_option(
            option_key="A",
            hotel=hotel_a,
            flight=flight_a,
            transfer=transfer_a,
            timing=timing_a,
            pricing=pricing_a,
            other_pricing=None if same_hotel else pricing_b,
            other_hotel=None if same_hotel else hotel_b,
        )
        tradeoff_b = TradeoffAnalyzer.analyze_option(
            option_key="B",
            hotel=hotel_b,
            flight=flight_b,
            transfer=transfer_b,
            timing=timing_b,
            pricing=pricing_b,
            other_pricing=None if same_hotel else pricing_a,
            other_hotel=None if same_hotel else hotel_a,
        )

        opt_a = cls._pack_single_option(
            option_key="A",
            badge_prefix="Оптимальный выбор ИИ",
            origin=origin,
            dest_name=dest_name,
            nights=nights,
            hotel=hotel_a,
            flight=flight_a,
            transfer=transfer_a,
            timing=timing_a,
            pricing=pricing_a,
            tradeoff=tradeoff_a,
            weather=weather,
            photo_map=photo_map,
            default_images=default_images,
            has_meal_addon=has_meal_addon,
            checkin_date=checkin_date,
            passengers=passengers,
            with_pet=with_pet,
        )
        opt_b = cls._pack_single_option(
            option_key="B",
            badge_prefix="Альтернатива для сравнения",
            origin=origin,
            dest_name=dest_name,
            nights=nights,
            hotel=hotel_b,
            flight=flight_b,
            transfer=transfer_b,
            timing=timing_b,
            pricing=pricing_b,
            tradeoff=tradeoff_b,
            weather=weather,
            photo_map=photo_map,
            default_images=default_images,
            has_meal_addon=has_meal_addon,
            checkin_date=checkin_date,
            passengers=passengers,
            with_pet=with_pet,
        )

        return {
            "options": {"A": opt_a, "B": opt_b},
            "timing_a": timing_a,
            "timing_b": timing_b,
            "pricing_a": pricing_a,
            "pricing_b": pricing_b,
            "tradeoff_a": tradeoff_a,
            "tradeoff_b": tradeoff_b,
        }

    @classmethod
    def _pack_single_option(
        cls,
        option_key: str,
        badge_prefix: str,
        origin: str,
        dest_name: str,
        nights: int,
        hotel: Dict[str, Any],
        flight: Dict[str, Any],
        transfer: Dict[str, Any],
        timing: Dict[str, Any],
        pricing: Dict[str, Any],
        tradeoff: Dict[str, Any],
        weather: Dict[str, Any],
        photo_map: Dict[str, List[str]],
        default_images: List[str],
        has_meal_addon: bool = False,
        checkin_date: Optional[str] = None,
        passengers: int = 2,
        with_pet: bool = False,
    ) -> Dict[str, Any]:
        first_day = weather["forecast"][0] if weather.get("forecast") else {"temp_max": 20, "condition": "Ясно ☀️"}
        temp_val = int(round(first_day.get("temp_max", 20)))
        temp_str = f"+{temp_val}°C" if temp_val > 0 else f"{temp_val}°C"

        pet_info = hotel.get("pet_friendly") or {}
        pet_allowed = bool(pet_info.get("allowed", False))
        pet_policy_text = pet_info.get(
            "description",
            "Разрешено с питомцами 🐾" if pet_allowed else "Без животных",
        )

        baggage_info = flight.get("baggage") or {}
        baggage_str = (
            f"Багаж {baggage_info.get('weight_kg', 20)} кг включён"
            if baggage_info.get("included", True)
            else "Ручная кладь 10 кг (багаж в смете)"
        )

        dest_id = hotel.get("destination_id", "sochi")
        dest_photos = photo_map.get(dest_id, default_images)
        raw_photos = hotel.get("photos") or []
        if raw_photos and raw_photos[0].startswith("http") and ("unsplash.com" in raw_photos[0]):
            img_url = raw_photos[0]
        else:
            img_url = dest_photos[0 if option_key == "A" else min(1, len(dest_photos) - 1)]

        tags = [format_amenity_tag(a) for a in hotel.get("amenities", [])[:3]]
        if has_meal_addon:
            tags = ["Завтрак + Ужин (HB)"] + tags[:2]
        elif not tags:
            tags = [hotel.get("meal_description", "Завтрак включён")]
        if pet_allowed:
            tags.append("Можно с питомцем")
        if pricing.get("rooms", 1) > 1:
            tags.append(f"Номеров: {pricing['rooms']}")
        if pricing.get('early_checkin_rub'):
            tags.append('Ранний заезд включён')

        timeline_steps = BookingCartAssembler.assemble_timeline_steps(
            origin=origin,
            dest_name=dest_name,
            nights=nights,
            hotel=hotel,
            flight=flight,
            transfer=transfer,
            timing=timing,
            checkin_date=checkin_date,
        )

        start = date.fromisoformat(checkin_date) if checkin_date else date.today() + timedelta(days=21)
        end = start + timedelta(days=nights)

        return {
            "id": option_key,
            "badge": f"Вариант {option_key} • {badge_prefix}",
            "title": f"{dest_name}: {hotel['name']}",
            "destination": f"{origin} → {dest_name}",
            "travellers": {"passengers": passengers, "withPet": with_pet},
            "dates": f"{start:%d.%m.%Y} — {end:%d.%m.%Y} • {nights} ноч.",
            "weather": {
                "temp": temp_str,
                "cond": first_day.get("condition", "Солнечно"),
                "humidity": "62%",
                "source": weather.get("source", ""),
            },
            "transport": {
                "type": " + ".join(dict.fromkeys(MODES.get(mode, mode) for mode in flight.get("modes", ["plane"]))) + " + Трансфер",
                "isDirectAir": flight.get("is_direct_air", flight.get("is_direct", True)),
                "connectionLabel": "Прямой" if flight.get("is_direct", True) else f"Пересадки: {max(1, len(flight.get('legs', []))-1)}",
                "legs": flight.get("legs", []), "layovers": flight.get("layovers", []),
                "source": flight.get("source", "Демонстрационное расписание"),
                "departureTimezone": (flight.get("departure_iso") or "")[-6:] if flight.get("departure_iso") else "",
                "arrivalTimezone": (flight.get("arrival_iso") or "")[-6:] if flight.get("arrival_iso") else "",
                "familyTariff": pricing.get("demo_party_tariff"),
                "carrier": f"{flight.get('airline', 'Аэрофлот')} • {flight.get('flight_number', 'SU-1120')}",
                "trainNumber": f"Трансфер: {transfer.get('vehicle', 'Toyota Camry')} ({transfer.get('duration_minutes', 40)} мин до отеля)",
                "depTime": flight.get("departure_time", "09:30"),
                "depCity": origin,
                "depStation": flight.get("origin", f"{origin} (Аэропорт)"),
                "arrTime": flight.get("arrival_time", "13:15"),
                "arrCity": dest_name,
                "arrStation": flight.get("destination", f"{dest_name} (Аэропорт)"),
                "duration": format_duration(flight.get('duration_hours', 3.5)),
                "wagonOrClass": f"Эконом Комфорт • {baggage_str}",
                "petRule": pet_policy_text,
                "price": int(pricing["flight_base_rub"]),
                "returnFlight": flight.get("return_flight"),
                "departureDate": start.isoformat(),
                "arrivalDate": flight.get("arrival_date", start.isoformat()),
                "priceIncludesReturn": bool(flight.get("price_includes_return")),
            },
            "hotel": {
                "id": hotel.get("id"),
                "name": hotel["name"],
                "stars": int(hotel.get("stars", 4)),
                "rating": float(hotel.get("rating", 9.2)),
                "reviews": int(hotel.get("reviews_count", 410)),
                "address": hotel.get("address", dest_name),
                "image": img_url,
                "pricePerNight": int(hotel.get("price_per_night", 8500)) * pricing.get("rooms", 1),
                "roomPricePerNight": int(hotel.get("price_per_night", 8500)),
                "rooms": pricing.get("rooms", 1),
                "nights": nights,
                "petFriendly": pet_allowed,
                "tags": tags,
                "pros": tradeoff["pros"],
                "cons": tradeoff["cons"],
                "risks": tradeoff["risks"],
                "whyThis": tradeoff["why_this"],
                "whatSacrificed": tradeoff["what_sacrificed"],
            },
            "timeline": timeline_steps,
            "extras": pricing["extras"],
            "fairPriceBreakdown": pricing,
            "timingValidation": timing,
        }
