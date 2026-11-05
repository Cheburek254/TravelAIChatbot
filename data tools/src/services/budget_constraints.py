"""User-owned lower and upper limits for the complete trip price."""
import re
from decimal import Decimal

_NUMBER = r"\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?"
_UNIT = r"(?:млн|миллион\w*|тысяч\w*|тыс(?:\.|\b)|т\.?\s*р\.?|[кk](?:\b|(?=₽|р))|руб\w*|₽|р\b)"
_AMOUNT = rf"({_NUMBER})\s*({_UNIT})?"


def _value(number, unit=""):
    amount = Decimal(re.sub(r"[\s\u00a0\u202f]", "", number).replace(",", "."))
    u = (unit or "").strip()
    if u and u.startswith(("млн", "миллион")):
        amount *= 1000000
    elif u and (u.startswith(("тыс", "тысяч", "т")) or u in ("к", "k")):
        amount *= 1000
    return int(amount)


def extract_budget_bounds(message):
    text = message.lower()
    text = re.sub(rf"\b(тысяч\w*|тыс\.?)\s+(от\s+{_NUMBER}\s+(?:до|[-–—])\s+{_NUMBER})\b", r"\2 \1", text)
    text = re.sub(rf"\b(тысяч\w*|тыс\.?)\s+({_NUMBER}(?:\s*[-–—]\s*{_NUMBER})?)\b", r"\2 \1", text)
    text = re.sub(r"\b(бюджет\w*)\s+(?:около|примерно|где-то|в\s+районе|в\s+пределах|порядка|плюс-минус)\s+", r"\1 ", text)
    bounds = {}
    interval = re.search(rf"(?:\bот\s+|бюджет\w*\s*[:=]?\s*){_AMOUNT}\s*(?:до|[-–—])\s*{_AMOUNT}", text)
    if interval and (interval.group(2) or interval.group(4) or _value(interval.group(1)) >= 1000 or "бюджет" in interval.group(0)):
        low, low_unit, high, high_unit = interval.groups()
        # In 'от 80 до 150 тыс.' the last multiplier applies to both bounds.
        if not low_unit and high_unit and _value(low) < 1000:
            low_unit = high_unit
        bounds.update(budget_min_rub=_value(low, low_unit), budget_rub=_value(high, high_unit))
        text = text[:interval.start()] + " " + text[interval.end():]
    else:
        lower = re.search(rf"(?:\bот|минимум|не\s+(?:менее|меньше)|нижн\w*\s+границ\w*|минимальн\w*\s+(?:бюджет|стоимост\w*)(?:\s+поездки)?)\s*[:=—-]?\s*{_AMOUNT}", text)
        if lower and (lower.group(2) or _value(lower.group(1)) >= 1000 or re.search(r"бюджет|стоимост", lower.group(0))):
            bounds["budget_min_rub"] = _value(*lower.groups())
            text = text[:lower.start()] + " " + text[lower.end():]
    if re.search(r"(?:убери|сними|отмени|без)\s+(?:нижн\w*\s+(?:границ\w*|лимит\w*)|минимальн\w*\s+бюджет\w*)", text):
        bounds["budget_min_rub"] = 0
    upper = re.search(rf"(?:максимум|не\s+(?:более|больше)|\bдо|бюджет\w*)\s*[:=—-]?\s*{_AMOUNT}", text)
    if upper and (upper.group(2) or _value(upper.group(1)) >= 1000 or "бюджет" in upper.group(0)):
        bounds["budget_rub"] = _value(*upper.groups())
    elif "budget_rub" not in bounds:
        # Keep the existing single-price input ('150 тыс.', '150 000 ₽').
        amount = re.search(rf"({_NUMBER})\s*({_UNIT})", text)
        if amount:
            bounds["budget_rub"] = _value(*amount.groups())
    if re.search(r"(?:убери|сними|отмени|без)\s+верхн\w*\s+(?:границ\w*|лимит\w*|ограничени\w*)", text):
        bounds["budget_rub"] = None
    return bounds


def apply_budget_bounds(state, bounds):
    lower = bounds.get("budget_min_rub", state.get("budget_min_rub", 0)) or 0
    upper = bounds.get("budget_rub", state.get("budget_rub"))
    if not 0 <= lower <= 10000000 or (upper is not None and not 1 <= upper <= 10000000):
        raise ValueError("Границы бюджета должны быть от 0 до 10 000 000 ₽; максимум — больше нуля.")
    if upper is not None and lower > upper:
        raise ValueError("Минимальная стоимость не может быть больше максимального бюджета.")
    changed = any(state.get(k) != v for k, v in bounds.items())
    if changed:
        state.pop("hotel_ids", None)
    for field, value in bounds.items():
        state[field] = value
        state["user_" + field] = value
    return changed


def is_budget_only_request(message):
    if not extract_budget_bounds(message):
        return False
    rest = re.sub(rf"{_NUMBER}\s*(?:{_UNIT})?", " ", message.lower())
    rest = re.sub(r"\b(?:бюджет\w*|стоимост\w*|поездк\w*|диапазон\w*|границ\w*|лимит\w*|ограничени\w*|нижн\w*|верхн\w*|минимальн\w*|максимальн\w*|минимум|максимум|тысяч\w*|тыс|около|примерно|от|до|не|менее|более|меньше|больше|за|всю|мой|новый|установи|сделай|измени|убери|сними|отмени|без|пожалуйста)\b", " ", rest)
    return not re.search(r"\w", rest)
