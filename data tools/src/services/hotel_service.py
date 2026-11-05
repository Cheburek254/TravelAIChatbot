from typing import List, Dict, Any, Optional
from datetime import datetime

from src.services.semantic_search import SemanticMatcher
from src.services.database import load_catalog, query_hotels

class HotelService:
    @classmethod
    def _load_data(cls) -> List[Dict[str, Any]]:
        return load_catalog("hotels")

    @classmethod
    def search(
        cls,
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
        hotels = query_hotels(destination, max_price_per_night=max_price_per_night,
            min_rating=min_rating, pet_friendly=pet_friendly, baby_crib=baby_crib,
            no_deposit=no_deposit, free_cancellation=free_cancellation, meal_type=meal_type,
            max_distance_to_center_km=max_distance_to_center_km,
            max_distance_to_beach_m=max_distance_to_beach_m, limit=max(40, limit * 4))

        nights = 1
        if checkin_date and checkout_date:
            try:
                d1 = datetime.strptime(checkin_date, "%Y-%m-%d")
                d2 = datetime.strptime(checkout_date, "%Y-%m-%d")
                delta = (d2 - d1).days
                if delta > 0:
                    nights = delta
            except Exception:
                pass

        matched_hotels = []

        for hotel in hotels:
            score = 1.0
            highlights = []

            price = hotel.get("price_per_night", 0)
            if max_price_per_night is not None and price > max_price_per_night:
                continue

            rating = hotel.get("rating", 0.0)
            if min_rating is not None and rating < min_rating:
                continue
            highlights.append(f"Рейтинг {rating}/10 ({hotel.get('reviews_count', 0)} отзывов)")

            pet_info = hotel.get("pet_friendly", {})
            if pet_friendly is True:
                if not pet_info.get("allowed", False):
                    continue
                highlights.append(f"🐾 Pet-friendly: {pet_info.get('description')}")
            elif pet_info.get("allowed", False):
                highlights.append(f"🐾 Дог-френдли (до {pet_info.get('max_weight_kg')} кг)")

            child_info = hotel.get("child_friendly", {})
            if baby_crib is True:
                if not child_info.get("baby_crib_available", False):
                    continue
                fee_text = "бесплатно" if child_info.get("baby_crib_free") else "по запросу"
                highlights.append(f"👶 Детская кроватка ({fee_text})")
            elif child_info.get("baby_crib_available"):
                highlights.append("👶 Детская кроватка доступна")

            deposit_info = hotel.get("deposit", {})
            if no_deposit is True:
                if deposit_info.get("required", False):
                    continue
                highlights.append("💳 Без залога и депозита при заселении")
            elif not deposit_info.get("required"):
                highlights.append("💳 Без депозита")
            else:
                highlights.append(f"⚠️ Депозит: {deposit_info.get('amount')} {deposit_info.get('currency')}")

            canc_info = hotel.get("cancellation_policy", {})
            if free_cancellation is True:
                if canc_info.get("type") not in ["free_cancellation", "flexible"]:
                    continue
                highlights.append(f"✅ Бесплатная отмена: {canc_info.get('description')}")
            else:
                highlights.append(f"Условия отмены: {canc_info.get('description')}")

            hotel_meal = hotel.get("meal_type", "")
            if meal_type:
                if meal_type.upper() != hotel_meal.upper():
                    continue
            highlights.append(f"🍽️ {hotel.get('meal_description')}")

            dist_beach = hotel.get("distance_to_beach_m")
            if max_distance_to_beach_m is not None:
                if dist_beach is None or dist_beach > max_distance_to_beach_m:
                    continue
            if dist_beach is not None and dist_beach <= 100:
                highlights.append(f"🏖️ Первая линия: всего {dist_beach} м до пляжа")

            dist_center = hotel.get("distance_to_center_km")
            if max_distance_to_center_km is not None:
                if dist_center is not None and dist_center > max_distance_to_center_km:
                    continue

            if vibe_query:
                doc_text = f"{hotel.get('name')} {hotel.get('description')} {' '.join(hotel.get('amenities', []))}"
                sim = SemanticMatcher.compute_similarity(vibe_query, doc_text, hotel.get("vibe_tags", []))
                score += sim * 2.5
                if sim > 0.2:
                    highlights.append(f"✨ Соответствие вайбу: {hotel.get('description')[:80]}...")
            else:
                score += (rating / 10.0)

            hotel_res = dict(hotel)
            hotel_res["nights_count"] = nights
            hotel_res["total_price"] = price * nights
            hotel_res["match_score"] = round(score, 2)
            hotel_res["match_highlights"] = highlights

            matched_hotels.append(hotel_res)

        matched_hotels.sort(key=lambda x: x["match_score"], reverse=True)
        top_hotels = matched_hotels[:limit]

        return {
            "destination": destination,
            "dates": {
                "checkin_date": checkin_date,
                "checkout_date": checkout_date,
                "nights": nights
            },
            "found_count": len(top_hotels),
            "hotels": top_hotels
        }
