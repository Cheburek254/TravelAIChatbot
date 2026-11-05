"""Normalize and validate direct and connecting Yandex A-to-B itineraries."""
from datetime import datetime

MODES = {"plane": "Самолёт", "train": "Поезд", "suburban": "Электричка", "bus": "Автобус"}


def stamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Не указан часовой пояс участка")
    return parsed


def station(point):
    return (point or {}).get("code") or (point or {}).get("title", "").strip().lower()


def _leg(item):
    thread = item.get("thread") or {}
    mode = thread.get("transport_type") or (item.get("from") or {}).get("transport_type")
    if mode not in MODES:
        raise ValueError("Неизвестный тип транспорта")
    dep, arr = stamp(item["departure"]), stamp(item["arrival"])
    if arr <= dep or not station(item.get("from")) or not station(item.get("to")):
        raise ValueError("Некорректные станции или время участка")
    return {"departure": dep.isoformat(), "arrival": arr.isoformat(),
            "from": dict(item["from"]), "to": dict(item["to"]), "mode": mode,
            "number": thread.get("number") or thread.get("uid") or MODES[mode],
            "carrier": (thread.get("carrier") or {}).get("title") or MODES[mode],
            "duration_minutes": int((arr - dep).total_seconds() / 60)}


def parse_route(segment, requested_date):
    try:
        details = segment.get("details")
        if segment.get("has_transfers") and not details:
            return None  # A connecting route needs its actual legs to be checked.
        details = details or [segment]
        legs, layovers, pending_transfer = [], [], None
        for detail in details:
            if detail.get("is_transfer"):
                if not legs or pending_transfer is not None:
                    return None
                pending_transfer = detail
                continue
            leg = _leg(detail)
            if legs:
                previous = legs[-1]
                gap = (stamp(leg["departure"]) - stamp(previous["arrival"])).total_seconds() / 60
                transfer_from = (pending_transfer or {}).get("transfer_from") or previous["to"]
                transfer_to = (pending_transfer or {}).get("transfer_to") or leg["from"]
                same_station = station(transfer_from) == station(transfer_to)
                if not pending_transfer and any(point.get("type") == "settlement" for point in (previous["to"], leg["from"])):
                    return None
                if not same_station and pending_transfer is None:
                    return None
                air_connection = "plane" in (previous["mode"], leg["mode"])
                minimum = (90 if same_station else 180) if air_connection else (15 if same_station else 60)
                if pending_transfer:
                    duration = float(pending_transfer.get("duration", 0)) / 60
                    if duration < 0 or duration > gap + 1:
                        return None
                    point = pending_transfer.get("transfer_point")
                    if point:
                        for endpoint in (previous["to"], leg["from"]):
                            if endpoint.get("type") == "settlement" and station(endpoint) != station(point):
                                return None
                    for field, expected in (("from", previous["to"]), ("to", leg["from"])):
                        if pending_transfer.get(field) and station(pending_transfer[field]) != station(expected):
                            return None
                if gap < minimum:
                    return None
                previous["to"], leg["from"] = dict(transfer_from), dict(transfer_to)
                layovers.append({"from": transfer_from.get("title", ""), "to": transfer_to.get("title", ""),
                                 "minutes": int(gap), "stationChange": not same_station})
            legs.append(leg)
            pending_transfer = None
        if not legs or pending_transfer:
            return None
        first, last = legs[0], legs[-1]
        if segment.get("departure_from"):
            first["from"] = dict(segment["departure_from"])
        if segment.get("arrival_to"):
            last["to"] = dict(segment["arrival_to"])
        dep, arr = stamp(first["departure"]), stamp(last["arrival"])
        if dep.date().isoformat() != requested_date:
            return None
        if segment.get("departure") and stamp(segment["departure"]) != dep:
            return None
        if segment.get("arrival") and stamp(segment["arrival"]) != arr:
            return None
        modes = [leg["mode"] for leg in legs]
        direct_air = len(legs) == 1 and modes == ["plane"]
        return {"flight_number": " / ".join(str(leg["number"]) for leg in legs),
                "airline": " / ".join(dict.fromkeys(leg["carrier"] for leg in legs)),
                "from_station": first["from"].get("title", ""), "to_station": last["to"].get("title", ""),
                "departure_time": dep.strftime("%H:%M"), "arrival_time": arr.strftime("%H:%M"),
                "date": dep.date().isoformat(), "arrival_date": arr.date().isoformat(),
                "departure_iso": dep.isoformat(), "arrival_iso": arr.isoformat(),
                "duration_hours": round((arr - dep).total_seconds() / 3600, 2),
                "is_direct": len(legs) == 1, "is_direct_air": direct_air,
                "route_rank": 0 if direct_air else 1 if all(m == "plane" for m in modes) else 2,
                "legs": legs, "layovers": layovers, "modes": modes}
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
