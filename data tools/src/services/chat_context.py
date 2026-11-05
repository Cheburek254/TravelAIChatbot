"""Small public conversation state and tool results used by the UI and LLM."""
import re

from src.services.database import destination_summary
from src.services.flight_preferences import TIME_FIELDS


def sync_destination_suggestions(session, reply=None):
    """Expose catalog choices even when the model answered without a search tool."""
    state = session["state"]
    if session["options"] or state.get("destination") or state.get("choosing_alternative"):
        return False
    if reply is None:
        reply = next((m.get("content", "") for m in reversed(session["messages"])
                      if m.get("role") == "assistant"), "")
    if not isinstance(reply, str) or not reply:
        return False
    choices = []
    has_candidates = False
    for destination in destination_summary():
        name = destination["name"]
        for match in re.finditer(r"(?<!\w)" + re.escape(name) + r"(?!\w)", reply, re.I):
            start = reply.rfind("\n", 0, match.start()) + 1
            end = reply.find("\n", match.end())
            line = reply[start:end if end != -1 else len(reply)]
            prefix = reply[start:match.start()]
            listed = bool(re.fullmatch(r"\s*(?:(?:#{1,6}|[-+•]|\d+[.)])\s+)?\*{0,2}", prefix))
            suggested = bool(re.search(r"предлага|рекоменд|рассмотр|подойдут|можно\s+(?:выбрать|поехать)|\bили\b.*\?", line, re.I))
            rejected = bool(re.search(r"не\s+(?:подход|рекоменд|совет|предлаг|доступ|стоит|укладыва)|слишком\s+дорог|превыша|вне\s+бюджета|нет\s+(?:поезд|вариант)", line, re.I))
            has_candidates = has_candidates or listed or suggested
            if (listed or suggested) and not rejected:
                choices.append((match.start(), name))
                break
    names = [name for _, name in sorted(choices)][:3]
    if not has_candidates or state.get("suggested_destinations", []) == names:
        return False
    state["suggested_destinations"] = names
    return True


def is_corrupt_text(text):
    return isinstance(text, str) and bool(re.search(r"\bcdnjs\b|<\|(?:assistant|endoftext|im_start)", text, re.I) or
        (re.search(r"[\u3400-\u9fff]", text) and re.search(r"[А-Яа-яЁё]", text)))


def repair_corrupt_history(session):
    changed = False
    for message in session["messages"]:
        if message.get("role") == "assistant" and is_corrupt_text(message.get("content")):
            message["content"] = "Предыдущий ответ был некорректным. Повторите запрос — проверю варианты и цены по каталогу."
            changed = True
    return changed


def public_chat_state(session):
    state = session["state"]
    fields = ("origin", "destination", "checkin_date", "checkout_date", "nights", "passengers",
              "budget_rub", "room_count", "has_meal_addon", "include_early_checkin", "pet_friendly", "suggested_destinations", "baby_crib", "adults", "children_ages", "travel_scope",
              "free_cancellation", "no_deposit", "min_rating", "meal_type", "max_distance_to_center_km",
              "max_distance_to_beach_m", "vibe_query", "hotel_ids", "alternative_quotes",
              "choosing_alternative", "date_weather", "dates_conditional", "budget_min_rub", "sort_by_price", "travel_styles")
    return {key: state[key] for key in (*fields, *TIME_FIELDS) if key in state}


def compact_tool_result(name, result):
    if not isinstance(result, dict):
        return result
    if name == "search_destinations":
        fields = ("id", "name", "country", "flight_time_hours_from_mow", "avg_budget_tier",
                  "climate_for_target_month", "match_reasons", "vibes", "visa_requirements", "best_months")
        return {"found_count": result.get("found_count"), "target_month": result.get("target_month"),
                "destinations": [{k: d[k] for k in fields if k in d} for d in result.get("destinations", [])[:3]]}
    if name == "search_hotels":
        fields = ("id", "name", "destination_name", "stars", "rating", "price_per_night", "total_price",
                  "meal_type", "pet_friendly", "child_friendly", "deposit", "cancellation_policy",
                  "distance_to_beach_m", "distance_to_center_km", "match_highlights", "checkin_time",
                  "checkout_time", "early_checkin_available", "late_checkout_available", "meal_description")
        return {"destination": result.get("destination"), "dates": result.get("dates"),
                "found_count": result.get("found_count"),
                "hotels": [{k: h[k] for k in fields if k in h} for h in result.get("hotels", [])[:5]]}
    if name == "search_transfers_and_flights":
        return {k: v[:3] if isinstance(v, list) else v for k, v in result.items()}
    return result
