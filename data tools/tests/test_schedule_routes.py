import copy
import io
import json
import os
import unittest
import urllib.error
import urllib.parse
from unittest.mock import patch

from src.services.flight_service import FlightService
from src.services.schedule_routes import parse_route
from src.services.trip_planner import select_affordable_options


def leg(departure="2026-11-15T08:00:00+03:00", arrival="2026-11-15T10:00:00+03:00",
        start="sSVO", end="sAER", mode="plane", number="SU 1"):
    return {"departure": departure, "arrival": arrival,
            "from": {"code": start, "title": start, "transport_type": mode},
            "to": {"code": end, "title": end, "transport_type": mode},
            "thread": {"number": number, "transport_type": mode, "carrier": {"title": "Carrier"}}, "has_transfers": False}


def connecting(change_station=False):
    first = leg(end="sCONNECT")
    second = leg("2026-11-15T14:00:00+03:00", "2026-11-15T16:00:00+03:00",
                 start="sOTHER" if change_station else "sCONNECT", number="SU 2")
    details = [first]
    if change_station:
        details.append({"is_transfer": True, "from": first["to"], "to": second["from"], "duration": 7200})
    details.append(second)
    return {"departure": first["departure"], "arrival": second["arrival"], "has_transfers": True, "details": details}


class ScheduleRoutesTests(unittest.TestCase):
    def test_direct_plane_is_preferred_but_train_route_is_valid(self):
        plane = parse_route(leg(), "2026-11-15")
        train = parse_route(leg(mode="train"), "2026-11-15")
        self.assertEqual(plane["route_rank"], 0)
        self.assertGreater(train["route_rank"], plane["route_rank"])

    def test_connecting_route_keeps_all_legs_and_layover(self):
        route = parse_route(connecting(), "2026-11-15")
        self.assertFalse(route["is_direct"])
        self.assertEqual(len(route["legs"]), 2)
        self.assertEqual(route["layovers"][0]["minutes"], 240)

    def test_real_yandex_transfer_shape_uses_station_fields_and_full_wait_duration(self):
        first = leg("2026-10-31T23:25:00+03:00", "2026-11-01T03:30:00+05:00", start="c213", end="c50")
        second = leg("2026-11-01T06:15:00+05:00", "2026-11-01T08:45:00+03:00", start="c50", end="c239")
        for endpoint in (first["from"], first["to"], second["from"], second["to"]):
            endpoint["type"] = "settlement"
        airport = {"code": "sPERM", "title": "Большое Савино", "type": "station"}
        data = {"departure": first["departure"], "arrival": second["arrival"], "has_transfers": True,
                "departure_from": {"code": "sVKO", "title": "Внуково"},
                "arrival_to": {"code": "sAER", "title": "Сочи"},
                "details": [first, {"is_transfer": True, "duration": 9900,
                    "transfer_point": {"code": "c50", "type": "settlement"}, "transfer_from": airport, "transfer_to": airport}, second]}
        route = parse_route(data, "2026-10-31")
        self.assertIsNotNone(route)
        self.assertEqual(route["layovers"][0]["minutes"], 165)
        self.assertFalse(route["layovers"][0]["stationChange"])
        self.assertEqual(route["from_station"], "Внуково")
        changed = copy.deepcopy(data)
        changed["details"][1]["transfer_to"] = {"code": "sOTHER", "title": "Другой аэропорт"}
        self.assertIsNone(parse_route(changed, "2026-10-31"))

    def test_mixed_route_can_be_valid(self):
        data = connecting()
        data["details"][1]["thread"]["transport_type"] = "train"
        self.assertEqual(parse_route(data, "2026-11-15")["modes"], ["plane", "train"])

    def test_short_or_negative_connection_is_rejected(self):
        for departure in ("2026-11-15T10:20:00+03:00", "2026-11-15T09:30:00+03:00"):
            data = connecting()
            data["details"][1]["departure"] = departure
            self.assertIsNone(parse_route(data, "2026-11-15"))

    def test_station_change_needs_explicit_transfer_and_enough_time(self):
        valid = connecting(change_station=True)
        self.assertTrue(parse_route(valid, "2026-11-15")["layovers"][0]["stationChange"])
        missing = copy.deepcopy(valid)
        missing["details"].pop(1)
        self.assertIsNone(parse_route(missing, "2026-11-15"))
        too_short = copy.deepcopy(valid)
        too_short["details"][-1]["departure"] = "2026-11-15T11:00:00+03:00"
        self.assertIsNone(parse_route(too_short, "2026-11-15"))

    def test_timezones_and_overnight_arrival_are_checked_as_instants(self):
        valid = leg("2026-11-15T12:00:00+03:00", "2026-11-15T11:00:00+00:00")
        self.assertEqual(parse_route(valid, "2026-11-15")["duration_hours"], 2)
        invalid = leg("2026-11-15T12:00:00+03:00", "2026-11-15T14:00:00+06:00")
        self.assertIsNone(parse_route(invalid, "2026-11-15"))
        overnight = leg("2026-11-15T23:00:00+03:00", "2026-11-16T01:00:00+03:00")
        self.assertEqual(parse_route(overnight, "2026-11-15")["arrival_date"], "2026-11-16")

    def test_connection_without_details_is_not_invented(self):
        data = leg()
        data["has_transfers"] = True
        self.assertIsNone(parse_route(data, "2026-11-15"))

    def test_direct_is_preferred_only_among_budget_feasible_routes(self):
        hotel = {"id": "h", "price_per_night": 1000, "destination_name": "unknown"}
        transfer = {"price_rub": 100, "capacity_passengers": 4}
        flights = [{"total_price": 10000, "route_rank": 0, "is_direct": True},
                   {"total_price": 2000, "route_rank": 1, "is_direct": False}]
        state = {"nights": 1, "passengers": 1, "budget_rub": 15000}
        chosen, _ = select_affordable_options([hotel], flights, [transfer], state)
        self.assertTrue(chosen[0]["flight"]["is_direct"])
        state["budget_rub"] = 5000
        chosen, _ = select_affordable_options([hotel], flights, [transfer], state)
        self.assertFalse(chosen[0]["flight"]["is_direct"])

    def test_direct_preference_applies_across_hotels_without_exceeding_budget(self):
        hotels = [{"id": "preferred", "price_per_night": 8000}, {"id": "other", "price_per_night": 1000}]
        flights = [{"total_price": 10000, "route_rank": 0, "is_direct": True}, {"total_price": 2000, "route_rank": 1, "is_direct": False}]
        state = {"nights": 1, "passengers": 1, "budget_rub": 15000, "hotel_ids": ["preferred", "other"]}
        choices, _ = select_affordable_options(hotels, flights, [{"price_rub": 100}], state)
        self.assertTrue(choices[0]["flight"]["is_direct"])
        self.assertEqual(choices[0]["hotel"]["id"], "other")
        self.assertTrue(all(choice["required"] <= 15000 for choice in choices))


class ScheduleProviderTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"OFFLINE_MODE": "0", "YANDEX_RASP_API_KEYS": "dummy-a,dummy-b"})
        self.env.start()
        self.saved_cache, self.saved_index = FlightService._segment_cache, FlightService._key_index
        FlightService._segment_cache, FlightService._key_index = {}, 0
        self.route = {"city": "Сочи", "airport_code": "AER", "base_price_rub": 8500,
                      "flight_duration_hours": 3.8, "airlines": [{"name": "Carrier", "code": "SU"}], "transfers": []}

    def tearDown(self):
        FlightService._segment_cache, FlightService._key_index = self.saved_cache, self.saved_index
        self.env.stop()

    def test_yandex_path_is_enabled_inside_tests_when_explicitly_configured(self):
        self.assertTrue(FlightService._yandex_enabled())
        with patch.dict(os.environ, {"OFFLINE_MODE": "1"}):
            self.assertFalse(FlightService._yandex_enabled())
        with patch.dict(os.environ, {"YANDEX_RASP_ENABLED": "false"}):
            self.assertFalse(FlightService._yandex_enabled())
            with patch.object(FlightService, "_find_route", return_value=self.route), patch("urllib.request.urlopen") as network:
                result = FlightService.search(destination="Сочи", date="2026-11-15", return_date="2026-11-19")
                network.assert_not_called()
                self.assertTrue(result["flights"])
                self.assertTrue(all(f["source"] == "Демонстрационное расписание" for f in result["flights"]))

    def test_hotel_amenity_tags_are_formatted_in_russian(self):
        from src.services.logistics_engine import format_amenity_tag, AMENITY_LABELS
        self.assertEqual(format_amenity_tag("water_villa"), "Водная вилла")
        self.assertEqual(format_amenity_tag("private_lagoon"), "Собственная лагуна")
        self.assertEqual(format_amenity_tag("diving_center"), "Дайвинг-центр")
        self.assertTrue(all("_" not in label for label in AMENITY_LABELS.values()))

    def test_rotation_tries_next_key_and_never_puts_keys_in_url(self):
        seen = []
        def response(req, **kwargs):
            seen.append(req.get_header("Authorization"))
            self.assertNotIn("apikey", req.full_url)
            if len(seen) == 1:
                raise urllib.error.HTTPError(req.full_url, 429, "quota", {}, None)
            return io.BytesIO(json.dumps({"segments": [leg()]}).encode())
        with patch("urllib.request.urlopen", side_effect=response):
            result = FlightService._fetch_yandex_segments("MOW", "AER", "2026-11-15")
        self.assertEqual(seen, ["dummy-a", "dummy-b"])
        self.assertEqual(len(result), 1)

    def test_pagination_and_cache_use_complete_results(self):
        offsets = []
        def response(req, **kwargs):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(req.full_url).query)
            offsets.append(params["offset"][0])
            self.assertEqual(params["transfers"], ["true"])
            return io.BytesIO(json.dumps({"segments": [leg()], "pagination": {"total": 2}}).encode())
        with patch("urllib.request.urlopen", side_effect=response) as network:
            self.assertEqual(len(FlightService._fetch_yandex_segments("MOW", "AER", "2026-11-15")), 2)
            FlightService._fetch_yandex_segments("MOW", "AER", "2026-11-15")
            self.assertEqual(network.call_count, 2)
        self.assertEqual(offsets, ["0", "1"])

    def test_expired_cache_is_refreshed(self):
        FlightService._segment_cache[("MOW", "AER", "2026-11-15")] = (0, [leg()])
        with patch("time.monotonic", return_value=601), patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"segments": []}')) as network:
            self.assertEqual(FlightService._fetch_yandex_segments("MOW", "AER", "2026-11-15"), [])
            network.assert_called_once()

    def search(self, fetch, **kwargs):
        with patch.object(FlightService, "_find_route", return_value=self.route), patch.object(FlightService, "_fetch_yandex_segments", side_effect=fetch):
            return FlightService.search(destination="Сочи", date="2026-11-15", **kwargs)

    def test_empty_real_schedule_is_not_replaced_with_synthetic_tickets(self):
        self.assertEqual(self.search([[]])["flights"], [])
        self.assertEqual(self.search([[leg()], []], return_date="2026-11-19")["flights"], [])

    def test_provider_failure_uses_explicit_demo_source_for_entire_route(self):
        result = self.search([None], return_date="2026-11-19")
        self.assertTrue(result["flights"])
        self.assertTrue(all(f["source"] == "Демонстрационное расписание" for f in result["flights"]))
        for flight in result["flights"]:
            self.assertTrue(flight["return_flight"])

    def test_time_filter_can_select_connection_when_direct_is_unsuitable(self):
        data = connecting()
        data["details"][0]["departure"] = "2026-11-15T11:00:00+03:00"
        data["details"][0]["arrival"] = "2026-11-15T12:30:00+03:00"
        data["departure"] = data["details"][0]["departure"]
        result = self.search([[leg(), data]], departure_after="11:00")
        self.assertEqual(len(result["flights"]), 1)
        self.assertFalse(result["flights"][0]["is_direct"])
        self.assertEqual(result["flights"][0]["departure_time"], "11:00")
