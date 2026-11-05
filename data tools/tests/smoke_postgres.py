"""Run inside the Compose app to check PostgreSQL -> API -> frontend assets.

docker compose cp "data tools/tests/smoke_postgres.py" app:/tmp/smoke_postgres.py
docker compose exec -T app python3 /tmp/smoke_postgres.py
"""
import json
import re
import sys
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path.cwd()))
from sqlalchemy import update
from src.services.database import get_engine, hotels, load_catalog, load_session


def request(path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = Request("http://127.0.0.1:8080" + path, data=body,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=95) as response:
        raw = response.read()
        return json.loads(raw) if "application/json" in response.headers.get("Content-Type", "") else raw.decode()


engine = get_engine()
assert engine.dialect.name == "postgresql", "Smoke check must use PostgreSQL"
counts = {name: len(load_catalog(name)) for name in ("destinations", "hotels", "routes")}
assert counts["destinations"] >= 10 and counts["hotels"] >= 18 and counts["routes"] >= 10, counts
assert request("/health")["status"] == "ok"
html = request("/")
asset = re.search(r'src="([^"]+\.js)"', html).group(1)
assert request(asset), "Frontend JS must be served"

sid_a, sid_b = str(uuid.uuid4()), str(uuid.uuid4())
assert request("/api/trips/initial?session_id=" + sid_a)["options"] == {}
request("/api/trips/initial?session_id=" + sid_b)
response = request("/api/chat", {"session_id": sid_a, "message": "Хочу в Дубай на неделю вдвоём"})
assert "Дубай" in response["updatedOptions"]["A"]["title"]
assert load_session(sid_a)["state"]["destination"] == "Дубай"
assert load_session(sid_b)["state"] == {}
assert len(request("/api/trips/initial?session_id=" + sid_a)["messages"]) == 2

hotel = load_catalog("hotels")[0]
try:
    with engine.begin() as conn:
        conn.execute(update(hotels).where(hotels.c.id == hotel["id"]).values(price_per_night=hotel["price_per_night"] + 123))
    found = request("/api/tools/hotels", {"destination": hotel["destination_name"]})["hotels"]
    assert next(h for h in found if h["id"] == hotel["id"])["price_per_night"] == hotel["price_per_night"] + 123
finally:
    with engine.begin() as conn:
        conn.execute(update(hotels).where(hotels.c.id == hotel["id"]).values(price_per_night=hotel["price_per_night"]))

trip = response["updatedOptions"]["A"]
booking = request("/api/bookings", {"trip": trip, "total_price": response["total_price_rub"]})
assert booking["status"] == "confirmed"
print(json.dumps({"postgres": "ok", "catalog": counts, "isolated_sessions": "ok",
                  "sql_price_to_json": "ok", "frontend_assets": "ok", "demo_booking": "ok"}))
