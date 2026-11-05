from typing import List, Dict, Any, Optional

from src.services.semantic_search import SemanticMatcher
from src.services.database import load_catalog
from src.services.travel_preferences import extract_travel_styles, matches_destination

MONTH_NAMES_RU = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12
}

class DestinationService:
    @classmethod
    def _load_data(cls) -> List[Dict[str, Any]]:
        return load_catalog("destinations")

    @classmethod
    def _extract_intent_from_query(cls, query: str) -> Dict[str, Any]:
        """Извлечение критериев направления из текста запроса."""
        extracted = {}
        if not query:
            return extracted

        q_lower = query.lower()

        for prefix, month_num in MONTH_NAMES_RU.items():
            if prefix in q_lower:
                extracted["month"] = month_num
                break

        if "тепло" in q_lower or "жарко" in q_lower or "лето" in q_lower:
            extracted["min_temp"] = 22.0

        if "без долгого перелет" in q_lower or "недалеко" in q_lower or "быстрый перелет" in q_lower:
            extracted["max_flight_hours"] = 6.0

        if "недорого" in q_lower or "дешево" in q_lower or "эконом" in q_lower:
            extracted["budget_tier"] = "budget"
        elif "люкс" in q_lower or "роскош" in q_lower or "дорого" in q_lower or "премиум" in q_lower:
            extracted["budget_tier"] = "luxury"

        return extracted

    @classmethod
    def search(
        cls,
        query: Optional[str] = None,
        month: Optional[int] = None,
        min_temp: Optional[float] = None,
        vibe: Optional[str] = None,
        max_flight_hours: Optional[float] = None,
        budget_tier: Optional[str] = None,
        limit: int = 5
    ) -> Dict[str, Any]:
        destinations = cls._load_data()

        implicit = cls._extract_intent_from_query(query or "")
        target_month = month or implicit.get("month") or 11  # Месяц по умолчанию — ноябрь.
        target_min_temp = min_temp if min_temp is not None else implicit.get("min_temp")
        target_max_flight = max_flight_hours if max_flight_hours is not None else implicit.get("max_flight_hours")
        target_budget = budget_tier or implicit.get("budget_tier")

        scored_results = []

        search_query_combined = f"{query or ''} {vibe or ''}".strip()
        styles = extract_travel_styles(search_query_combined)

        for dest in destinations:
            if not matches_destination(dest, styles):
                continue
            score = 0.5
            reasons = []

            doc_text = f"{dest['name']} {dest['country']} {dest['description']} {' '.join(dest['top_activities'])}"
            if search_query_combined:
                sim = SemanticMatcher.compute_similarity(search_query_combined, doc_text, dest.get("vibes", []))
                score += sim * 2.0
                if sim > 0.2:
                    reasons.append(f"Высокое соответствие вайбу: {', '.join(dest.get('vibes', [])[:3])}")

            climate_month = dest.get("climate_by_month", {}).get(str(target_month))
            if climate_month:
                day_t = climate_month.get("avg_day_temp", 0)
                water_t = climate_month.get("water_temp", 0)

                if target_min_temp is not None:
                    if day_t >= target_min_temp:
                        score += 1.0
                        reasons.append(f"Теплая погода в месяце #{target_month}: днем +{day_t}°C (вода +{water_t}°C)")
                    else:
                        score -= 1.5 # Штраф за холод, если просили тепло

                if any(k in search_query_combined.lower() for k in ["лыж", "сноуборд", "пухляк", "зим"]) and day_t <= 0:
                    score += 1.2
                    reasons.append(f"Устойчивый снежный покров и температура {day_t}°C для лыж")

            flight_time = dest.get("flight_time_hours_from_mow", 0)
            if target_max_flight is not None:
                if flight_time <= target_max_flight:
                    score += 0.8
                    reasons.append(f"Удобный перелет: всего {flight_time} ч. из Москвы")
                else:
                    score -= 1.0 # Превышает желаемое время перелета
            else:
                reasons.append(f"Перелет из Москвы: ~{flight_time} ч.")

            if target_budget:
                if dest.get("avg_budget_tier") == target_budget:
                    score += 0.7
                    reasons.append(f"Соответствует ценовому сегменту: {target_budget}")

            dest_copy = dict(dest)
            dest_copy["match_score"] = round(score, 2)
            dest_copy["match_reasons"] = reasons
            if climate_month:
                dest_copy["climate_for_target_month"] = {
                    "month": target_month,
                    **climate_month
                }

            scored_results.append(dest_copy)

        scored_results.sort(key=lambda x: x["match_score"], reverse=True)
        top_destinations = scored_results[:limit]

        return {
            "query": query,
            "target_month": target_month,
            "found_count": len(top_destinations),
            "destinations": top_destinations
        }
