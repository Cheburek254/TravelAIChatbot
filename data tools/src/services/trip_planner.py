"""Select real catalog combinations against the complete, server-calculated budget."""
from itertools import product

from src.services.logistics_engine import FairPriceCalculator
from src.services.early_checkin import early_arrival


def required_option_funds(option):
    price = option.get("fairPriceBreakdown") or {}
    if price:
        return price["grand_total_rub"] + price.get("refundable_deposit_rub", 0)
    transport = option.get("transport") or option.get("flight") or {}
    hotel = option.get("hotel") or {}
    return transport.get("price", 0) + hotel.get("pricePerNight", 0) * hotel.get("nights", 0) + sum(e["price"] for e in option.get("extras", []))


def enforce_saved_budget(session):
    """Remove legacy expensive cards while retaining any affordable alternative."""
    cap = session["state"].get("budget_rub")
    floor = session["state"].get("budget_min_rub", 0)
    within = lambda o: required_option_funds(o) >= floor and (cap is None or required_option_funds(o) <= cap)
    if not any(not within(o) for o in session["options"].values() if o.get("available", True)):
        return False
    session["options"] = {k: o for k, o in session["options"].items()
                          if o.get("available", True) and within(o)}
    if session["options"]:
        session["state"]["plan_status"] = "ready"
        session["state"].pop("plan_message", None)
        if session["selected_option"] not in session["options"]:
            session["selected_option"] = next(iter(session["options"]))
    else:
        session["state"].update(plan_status="unavailable", plan_message=
            "Предыдущие варианты не входят в ваш диапазон бюджета. Попросите пересобрать поездку — покажу только подходящие предложения.")
    return True


def select_affordable_options(hotels, flights, transfers, state):
    budget = state.get("budget_rub")
    floor = state.get("budget_min_rub", 0)
    wanted = state.get("hotel_ids") or []
    hotel_order = {h["id"]: i for i, h in enumerate(hotels)}
    candidates = []
    for hotel, flight, transfer in product(hotels, flights, transfers):
        if flight.get("arrival_date") and flight["arrival_date"] >= state["checkout_date"]:
            continue
        if int(transfer.get("capacity_passengers", state["passengers"])) < state["passengers"]:
            continue
        if state.get("pet_friendly") and transfer.get("pet_friendly") is False:
            continue
        if any(age < 7 for age in state.get("children_ages", [])) and not transfer.get("child_seat_available"):
            continue
        if state.get('include_early_checkin') and not early_arrival(hotel, flight, transfer, state['checkin_date']):
            continue
        price = FairPriceCalculator.calculate_fair_price(
            hotel, flight, transfer, nights=state["nights"], passengers=state["passengers"],
            with_pet=bool(state.get("pet_friendly")), has_meal_addon=bool(state.get("has_meal_addon")),
            include_early_checkin=bool(state.get('include_early_checkin')),
            room_count=state.get('room_count'),
        )
        required = price["grand_total_rub"] + price["refundable_deposit_rub"]
        candidates.append({"hotel": hotel, "flight": flight, "transfer": transfer,
                           "price": price, "required": required})
    minimum = min((c["required"] for c in candidates), default=None)
    feasible = [c for c in candidates if c["required"] >= floor and (budget is None or c["required"] <= budget)]
    if feasible:
        minimum = min(c["required"] for c in feasible)
    feasible.sort(key=lambda c: (
        c["required"] if state.get("sort_by_price") else 0,
        c["flight"].get("route_rank", 0 if c["flight"].get("is_direct", True) else 1),
        wanted.index(c["hotel"]["id"]) if c["hotel"]["id"] in wanted else len(wanted),
        hotel_order[c["hotel"]["id"]], c["required"],
    ))
    if not feasible:
        return [], minimum
    first = feasible[0]
    second = next((c for c in feasible[1:] if c["hotel"]["id"] != first["hotel"]["id"]), None)
    return [first, second] if second else [first], minimum
