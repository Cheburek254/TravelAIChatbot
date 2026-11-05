"""Explicit flight-time edits, including questions such as 'can we fly later?'."""
import re
from datetime import date, timedelta

TIME_FIELDS = ("departure_after", "departure_before", "arrival_after", "arrival_before", "return_departure_after",
               "return_departure_before", "return_arrival_after", "return_arrival_before")
TIME_PATTERN = r"^(?:[01]\d|2[0-3]):[0-5]\d$"
_CLOCK = r"([01]?\d|2[0-3])(?:[.:]([0-5]\d))?(?![\d.:])"
_WEEKDAYS = (r"понедельник|пн", r"вторник|вт", r"сред[ау]|ср", r"четверг|чт",
             r"пятниц[ау]|пт", r"суббот[ау]|сб", r"воскресень[еея]|вс")


def _window(text, prefix, current=None):
    patch = {}
    relative_text = re.sub(r"\bне\s+позже", "", text)
    periods = ((r"утром|утрен\w*", "06:00", "11:59"),
               (r"до обеда|к обеду", "00:00", "11:59"),
               (r"днем|дневн\w*|после обеда", "12:00", "17:59"),
               (r"вечером|вечерн\w*", "18:00", "23:59"),
               (r"ночью|ночн\w*", "00:00", "05:59"))
    for pattern, lower, upper in periods:
        if re.search(pattern, text):
            patch.update({prefix + "after": lower, prefix + "before": upper})
    if re.search(r"не\s+(?:так(?:ого|ой)?\s+|слишком\s+|очень\s+)?ран(?:н|о)|попозже|позже", relative_text):
        lower = "09:00"
        if current and re.search(r"попозже|позже", relative_text):
            minutes = int(current[:2]) * 60 + int(current[3:]) + 1
            lower = f"{min(minutes, 1439) // 60:02d}:{min(minutes, 1439) % 60:02d}"
            if minutes >= 1440:
                patch[prefix + 'before'] = '00:00'
        patch[prefix + "after"] = lower
    for pattern, field in ((r"(?:после|не раньше)\s*", "after"),
                           (r"(?:до|не позже|не позднее)\s*", "before")):
        match = re.search(pattern + _CLOCK, text)
        if match:
            patch[prefix + field] = f"{int(match[1]):02d}:{int(match[2] or 0):02d}"
    exact = re.search(r"\b(?:ровно\s+)?в\s+" + _CLOCK, text)
    if exact:
        stamp = f"{int(exact[1]):02d}:{int(exact[2] or 0):02d}"
        patch.update({prefix + "after": stamp, prefix + "before": stamp})
    return patch


def _direction_windows(text, default_prefix, current=None, arrival_current=None):
    markers = list(re.finditer(r"\b(?:вылет\w*|улет\w*|отправ\w*|прилет\w*|прибыт\w*|прибыть|лететь|рейс\w*)\b", text))
    if not markers:
        return _window(text, default_prefix, arrival_current if default_prefix.endswith('arrival_') else current)
    result = {}
    returning = default_prefix.startswith('return_')
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        arrival = bool(re.match(r'прилет|прибыт|прибыть', marker[0]))
        prefix = ('return_' if returning else '') + ('arrival_' if arrival else 'departure_')
        result.update(_window(text[marker.start():end], prefix, current if not arrival else arrival_current))
    return result


def extract_flight_preferences(message, state=None, options=None):
    text = message.lower().replace("ё", "е")
    if re.match(r"\s*(?:а\s+)?(?:почему|зачем|расскажи|объясни|во сколько|сколько|в какое время)\b", text):
        return {}
    if not re.search(r"вылет|рейс|полет|лететь|улет|билет|верн|возвращ|обратн|прилет|прибыт|прибыть", text):
        return {}
    state = state or {}
    transport = next(iter((options or {}).values()), {}).get('transport', {})
    current = transport.get('depTime')
    returning = re.search(r"верн|возвращ|обратн", text)
    outward = text[:returning.start()] if returning else text
    back = text[returning.start():] if returning else ""
    patch = _direction_windows(outward, "departure_", current, transport.get('arrTime'))
    if back:
        returning_flight = transport.get('returnFlight') or {}
        patch.update(_direction_windows(back, "return_arrival_", returning_flight.get('departure_time'), returning_flight.get('arrival_time')))
    if not patch:
        return {}
    start = date.fromisoformat(state.get("checkin_date") or date.today().isoformat())
    for index, pattern in enumerate(_WEEKDAYS):
        if re.search(r"\b(?:в|во)\s+(?:" + pattern + r")\b", outward):
            start += timedelta(days=(index - start.weekday()) % 7)
            patch["checkin_date"] = start.isoformat()
    for index, pattern in enumerate(_WEEKDAYS):
        if re.search(r"\b(?:в|во)\s+(?:" + pattern + r")\b", back):
            end = start + timedelta(days=(index - start.weekday()) % 7)
            patch["checkout_date"] = end.isoformat()
    if "checkin_date" in patch and "checkout_date" not in patch:
        patch["checkout_date"] = (start + timedelta(days=state.get("nights", 4))).isoformat()
    return patch


def is_flight_change_request(message):
    return bool(extract_flight_preferences(message))
