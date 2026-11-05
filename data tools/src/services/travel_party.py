"""Validated party composition and explicit demo tariff rules."""
import math
import re
from typing import Annotated
from pydantic import Field

ChildAge = Annotated[int, Field(strict=True, ge=0, le=17)]
CHILD_WORDS = r"\b(?:дет(?:и|ей|ям|ьми|ях)|ребен\w*|сын\w*|доч\w*|малыш\w*)\b"
AGE_UNIT = r"(?:лет|года?|год)"


def extract_total_guests(message):
    text = message.lower()
    for pattern, count in ((r'\bвчетвером|\bучетвером', 4), (r'\bвтро[её]м', 3), (r'\bвдво[её]м', 2)):
        if re.search(pattern, text):
            return count
    match = re.search(r'\b(10|[1-9])\s*(?:чел(?:овек\w*)?|гост\w*|пассажир\w*)\b', text)
    return int(match[1]) if match else None


def is_child_addition(message):
    text = message.lower().replace("ё", "е")
    return bool(re.search(r"\bдобав\w*.{0,25}" + CHILD_WORDS, text))


def _mentioned_children(text):
    """Collect every age group; one known sibling must not hide an unknown one."""
    mentions = list(re.finditer(CHILD_WORDS, text))
    ages, unknown = [], False
    for index, child in enumerate(mentions):
        end = mentions[index + 1].start() if index + 1 < len(mentions) else len(text)
        following = text[child.end():end]
        age_text = re.match(r"\s*(?:(?:в\s+возрасте|возрастом)\s*)?[:—-]?\s*"
                            r"(\d{1,2}(?:\s*" + AGE_UNIT + r")?"
                            r"(?:\s*(?:,|и|/|;)\s*\d{1,2}(?:\s*" + AGE_UNIT + r")?)*)", following)
        explicit_age = bool(re.match(r"\s*(?:в\s+возрасте|возрастом)\b", following))
        parenthesized = re.match(r"\s*\(\s*(\d{1,2})\s*(?:" + AGE_UNIT + r")?\s*\)", following)
        values = []
        if age_text and (explicit_age or re.search(AGE_UNIT, age_text[1])):
            value_text = age_text[1]
            if not explicit_age:
                last_unit = list(re.finditer(AGE_UNIT, value_text))[-1]
                value_text = value_text[:last_unit.end()]
            values = [int(n) for n in re.findall(r"\d+", value_text)]
        elif parenthesized:
            values = [int(parenthesized[1])]
        # A plural count ('двое детей 8 лет') cannot silently become one child.
        count = re.search(r"\b(\d+|двое|два|трое|три|четверо|четыре)\s*$", text[:child.start()])
        expected = 1
        if count:
            expected = int(count[1]) if count[1].isdigit() else {"двое": 2, "два": 2, "трое": 3, "три": 3, "четверо": 4, "четыре": 4}[count[1]]
        unknown = unknown or not values or len(values) < expected
        ages.extend(values)
    return mentions, ages, unknown


def normalize_party(state, patch=None):
    patch = patch or {}
    ages = list(patch.get("children_ages", state.get("children_ages") or []))
    adults = patch.get("adults", state.get("adults", state.get("passengers", 2)))
    if "passengers" in patch and "adults" not in patch:
        adults = patch["passengers"] - len(ages)
    if isinstance(adults, bool) or not isinstance(adults, int) or adults < 1:
        raise ValueError("Нужен хотя бы один взрослый. Дети путешествуют со взрослым.")
    if any(isinstance(age, bool) or not isinstance(age, int) or not 0 <= age <= 17 for age in ages):
        raise ValueError("Укажите возраст каждого ребёнка от 0 до 17 лет.")
    if adults + len(ages) > 10:
        raise ValueError("В одной поездке допускается до 10 гостей, включая детей.")
    infants = sum(age < 2 for age in ages)
    if infants > adults:
        raise ValueError("На каждого младенца до 2 лет нужен отдельный сопровождающий взрослый.")
    return {"adults": adults, "children_ages": ages, "passengers": adults + len(ages)}


def party_factors(adults, ages):
    # Synthetic fares, not airline or hotel policies. Ages are at departure.
    return {"fare_units": adults + sum(0.1 if age < 2 else 0.75 if age < 12 else 1 for age in ages),
            "seats": adults + sum(age >= 2 for age in ages),
            "rooms": max(1, math.ceil((adults + sum(age >= 2 for age in ages)) / 2)),
            "meal_units": adults + sum(0.5 for age in ages if age >= 2)}


def extract_party(message, state=None):
    text = message.lower().replace("ё", "е")
    patch = {}
    if (state or {}).get("awaiting_children_ages") and re.fullmatch(r"[\d\s,;/и]+(?:лет|года?|год)?[.!\s]*", text):
        patch["children_ages"] = [int(n) for n in re.findall(r"\d+", text)]
    match = re.search(r"\b(10|[1-9])\s*взросл\w*", text)
    if match:
        patch["adults"] = int(match[1])
    else:
        for words, count in (("один|одна", 1), ("два|двое", 2), ("три|трое", 3), ("четыре|четверо", 4)):
            if re.search(r"\b(?:" + words + r")\s+взросл\w*", text):
                patch["adults"] = count
                break
        if "adults" not in patch:
            if re.search(r"(?:\b(?:я|еду|лечу|поеду)\s+(?:один|одна)|^(?:один|одна)\s+с\s+(?:ребен|сын|доч))", text):
                patch["adults"] = 1
            elif re.search(r"\b(?:с\s+(?:женой|мужем|супругой|супругом|девушкой|парнем)|вдвоем|парой)\b", text):
                patch["adults"] = 2
    # Require explicit ages; never guess them from 'с ребёнком'.
    _, ages, unknown = _mentioned_children(text)
    if ages and not unknown:
        patch["children_ages"] = ages
    if re.search(r"без\s+детей", text):
        patch["children_ages"] = []
    elif "children_ages" in patch and (is_child_addition(message) or (state or {}).get("pending_child_append")):
        patch["children_ages"] = list((state or {}).get("children_ages_before_edit", (state or {}).get("children_ages", []))) + patch["children_ages"]
    total = extract_total_guests(message)
    if total is None and (state or {}).get('awaiting_children_ages'):
        total = ((state or {}).get('pending_trip_edit') or {}).get('party_total_guests')
    if total is not None and not re.search(r'\b(?:\d+|один|двое|два|трое|три|четверо|четыре)\s*взросл', text):
        patch.pop('adults', None)
        patch['passengers'] = total
    if patch:
        base = {**(state or {}), **((state or {}).get("pending_trip_edit") or {})}
        normalized = normalize_party(base, patch)
        return normalized if "children_ages" in patch or 'passengers' in patch else {"adults": normalized["adults"]}
    return {}


def needs_children_ages(message, state):
    text = message.lower().replace("ё", "е")
    if re.search(r"без\s+детей", text):
        return False
    mentions, ages, unknown = _mentioned_children(text)
    return bool(mentions and unknown and (ages or not state.get("children_ages") or is_child_addition(message)))
