"""Persist explicit holiday styles and match them against catalog tags."""
import re
from src.services.chat_intent import is_conversation_request

STYLE_PATTERNS = {
    "mountains": r"\b(?:гор(?:ы|у|ах|ам|ами)|горнолыж\w*|лыж\w*|сноуборд\w*)\b",
    "sea": r"\b(?:мор(?:е|ю|я|ем)|пляж\w*|океан\w*)\b",
}


def extract_travel_styles(text):
    text = text.lower()
    # A negated preference is not an affirmative request for that landscape.
    text = re.sub(r"\b(?:не\s+(?:хочу\s+)?(?:в|к|на)?\s*|без\s+)(?:горы|гор|моря|море|пляжа|пляж)\b", " ", text)
    return [style for style, pattern in STYLE_PATTERNS.items() if re.search(pattern, text)]


def style_label(styles):
    return " и ".join({"mountains": "горы", "sea": "море"}[s] for s in styles if s in STYLE_PATTERNS)


def extract_travel_scope(text):
    t = text.lower()
    if re.search(r"\b(?:за\s*границ\w*|за\s*рубеж\w*|зарубеж\w*|в\s+друг\w+\s+стран\w*|другие\s+страны)\b", t):
        return "abroad"
    if re.search(r"\b(?:по\s+росси\w*|внутри\s+страны|отечественн\w*|в\s+рф)\b", t):
        return "russia"
    return None


def matches_destination(record, styles):
    tags = " ".join(record.get("vibes", []))
    supported = extract_travel_styles(tags)
    return all(style in supported for style in styles)


def matches_hotel(record, styles):
    if not styles:
        return True
    supported = extract_travel_styles(" ".join(record.get("vibe_tags", [])))
    # A trip combining sea and mountains can use either as its hotel base.
    return any(style in supported for style in styles)


def inspiration_styles(message):
    text = message.lower().strip().rstrip(".!?")
    simple = re.fullmatch(r"(?:хочу|давай|лучше)\s+(?:отдых\s+)?(?:в\s+горы|в\s+горах|к\s+морю|на\s+море|у\s+моря)", text)
    template = re.fullmatch(r"помоги выбрать направление для отдыха (?:в горах|у моря)(?:\. сначала предложи направления и уточни условия)?", text)
    return extract_travel_styles(text) if simple or template else None


def restore_travel_styles(session):
    state = session["state"]
    if "travel_styles" in state:
        return False
    for message in reversed(session["messages"]):
        if message.get("role") == "user" and not is_conversation_request(message.get("content", "")):
            styles = extract_travel_styles(message.get("content", ""))
            if styles:
                state["travel_styles"] = styles
                state.pop("alternative_quotes", None)
                state.pop("suggested_destinations", None)
                state["choosing_alternative"] = False
                return True
    return False


def enforce_saved_styles(session):
    styles = session["state"].get("travel_styles", [])
    if not styles or not session["options"]:
        return False
    from src.services.database import load_catalog
    destinations = {d["id"]: d for d in load_catalog("destinations")}
    hotels = {h["id"]: h for h in load_catalog("hotels")}
    def matches(option):
        hotel = hotels.get(option.get("hotel", {}).get("id"), {})
        destination = destinations.get(hotel.get("destination_id"), {})
        return matches_destination(destination, styles) and matches_hotel(hotel, styles)
    if all(matches(o) for o in session["options"].values() if o.get("available", True)):
        return False
    session["options"] = {k: o for k, o in session["options"].items() if o.get("available", True) and matches(o)}
    state = session["state"]
    if session["options"]:
        if session["selected_option"] not in session["options"]:
            session["selected_option"] = next(iter(session["options"]))
        state["plan_status"] = "ready"
        state.pop("plan_message", None)
    else:
        state.update(plan_status="unavailable", plan_message=f"Предыдущие варианты не соответствуют пожеланию «{style_label(styles)}». Выберите подходящее направление или повторите подбор.")
    return True
