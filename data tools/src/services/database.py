"""SQL catalog and chat storage. JSON files are only used for initial seeding."""
import json
import os
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from sqlalchemy import (JSON, Column, Float, ForeignKey, Integer, MetaData,
                        String, Table, create_engine, insert, select, text, update, or_, Index)
from src.services.catalog_migrations import is_legacy_demo_route

metadata = MetaData()
destinations = Table(
    "destinations", metadata,
    Column("id", String, primary_key=True), Column("name", String, nullable=False),
    Column("country", String, nullable=False), Column("data", JSON, nullable=False),
)
hotels = Table(
    "hotels", metadata,
    Column("id", String, primary_key=True),
    Column("destination_id", String, ForeignKey("destinations.id"), nullable=False, index=True),
    Column("name", String, nullable=False), Column("price_per_night", Integer, nullable=False),
    Column("rating", Float, nullable=False), Column("data", JSON, nullable=False),
)
routes = Table(
    "routes", metadata,
    Column("id", String, primary_key=True), Column("city", String, nullable=False),
    Column("data", JSON, nullable=False),
)
sessions = Table(
    "chat_sessions", metadata,
    Column("id", String(128), primary_key=True),
    Column("state", JSON, nullable=False), Column("messages", JSON, nullable=False),
    Column("options", JSON, nullable=False), Column("selected_option", String(1), nullable=False),
)
hotel_shortlist_index = Index("ix_hotels_shortlist", hotels.c.destination_id, hotels.c.price_per_night, hotels.c.rating)
_engine = None
_init_lock = RLock()
_turn_locks = [RLock() for _ in range(64)]


def get_engine():
    global _engine
    with _init_lock:
        if _engine is None:
            url = os.getenv("DATABASE_URL", "sqlite:///./travel.db")
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+psycopg://", 1)
            kwargs = {"pool_pre_ping": True}
            if url.startswith("sqlite"):
                kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
            engine = create_engine(url, **kwargs)
            metadata.create_all(engine)
            with engine.begin() as conn:
                # Multiple app processes may start together. Seed only once, without
                # replacing edits already made in SQL.
                if engine.dialect.name == "postgresql":
                    conn.execute(text("SELECT pg_advisory_xact_lock(8736521)"))
                hotel_shortlist_index.create(conn, checkfirst=True)
                _seed(conn)
            _engine = engine
        return _engine


def _seed(conn):
    base = Path(__file__).resolve().parents[2] / "data"
    source = [
        (destinations, "destinations.json"), (hotels, "hotels.json"),
        (routes, "transfers.json"),
    ]
    for table, filename in source:
        existing = set(conn.execute(select(table.c.id)).scalars())
        raw = json.loads((base / filename).read_text(encoding="utf-8"))
        records = [{"id": k, **v} for k, v in raw["routes"].items()] if table is routes else raw
        for record in records:
            if record["id"] in existing:
                if table is routes and record['id'] in ('dubai', 'bali'):
                    saved = conn.execute(select(table.c.data).where(table.c.id == record['id'])).scalar_one()
                    if is_legacy_demo_route(saved):
                        conn.execute(update(table).where(table.c.id == record['id']).values(data=record))
                continue
            row = {"id": record["id"], "data": record}
            if table is destinations:
                row.update(name=record["name"], country=record["country"])
            elif table is hotels:
                row.update(name=record["name"], destination_id=record["destination_id"],
                           price_per_night=record["price_per_night"], rating=record["rating"])
            else:
                row["city"] = record["city"]
            conn.execute(insert(table).values(**row))


def load_catalog(kind):
    table = {"destinations": destinations, "hotels": hotels, "routes": routes}[kind]
    with get_engine().connect() as conn:
        rows = conn.execute(select(table)).mappings().all()
    result = []
    for row in rows:
        # Scalar SQL columns override JSON metadata, so an SQL price edit is
        # immediately reflected in the API without a process restart.
        record = dict(row["data"])
        record.update({k: v for k, v in row.items() if k != "data"})
        result.append(record)
    return {r["id"]: r for r in result} if kind == "routes" else result


def destination_summary():
    with get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(select(destinations.c.id, destinations.c.name, destinations.c.country)).mappings()]


def query_hotels(destination, *, max_price_per_night=None, min_rating=None,
                 pet_friendly=None, baby_crib=None, no_deposit=None, free_cancellation=None,
                 meal_type=None, max_distance_to_center_km=None, max_distance_to_beach_m=None, limit=40):
    from src.services.catalog_locations import destination_id
    key = destination_id(destination)
    query = select(hotels)
    if key:
        query = query.where(hotels.c.destination_id == key)
    else:
        value = (destination or "").strip().lower()
        # Unknown places must not fall through to another city.
        query = query.where(or_(hotels.c.destination_id == value,
            hotels.c.data["destination_name"].as_string() == destination,
            hotels.c.data["address"].as_string() == destination))
    if max_price_per_night is not None:
        query = query.where(hotels.c.price_per_night <= max_price_per_night)
    if min_rating is not None:
        query = query.where(hotels.c.rating >= min_rating)
    for required, path in ((pet_friendly, ("pet_friendly", "allowed")), (baby_crib, ("child_friendly", "baby_crib_available"))):
        if required:
            query = query.where(hotels.c.data[path[0]][path[1]].as_boolean().is_(True))
    if no_deposit:
        query = query.where(hotels.c.data["deposit"]["required"].as_boolean().is_not(True))
    if free_cancellation:
        query = query.where(hotels.c.data["cancellation_policy"]["type"].as_string().in_(["free_cancellation", "flexible"]))
    if meal_type:
        query = query.where(hotels.c.data["meal_type"].as_string() == meal_type.upper())
    if max_distance_to_beach_m is not None:
        query = query.where(hotels.c.data["distance_to_beach_m"].as_float() <= max_distance_to_beach_m)
    if max_distance_to_center_km is not None:
        distance = hotels.c.data["distance_to_center_km"].as_float()
        query = query.where(or_(distance.is_(None), distance <= max_distance_to_center_km))
    query = query.order_by(hotels.c.price_per_night, hotels.c.rating.desc(), hotels.c.id).limit(min(max(limit, 1), 200))
    with get_engine().connect() as conn:
        return [{**r["data"], **{k: v for k, v in r.items() if k != "data"}}
                for r in conn.execute(query).mappings()]


def load_session(session_id):
    with get_engine().connect() as conn:
        row = conn.execute(select(sessions).where(sessions.c.id == session_id)).mappings().first()
    return dict(row) if row else {"id": session_id, "state": {}, "messages": [],
                                 "options": {}, "selected_option": "A"}


def save_session(session):
    values = {k: session[k] for k in ("state", "messages", "options", "selected_option")}
    with get_engine().begin() as conn:
        exists = conn.execute(select(sessions.c.id).where(sessions.c.id == session["id"])).first()
        if exists:
            conn.execute(update(sessions).where(sessions.c.id == session["id"]).values(**values))
        else:
            conn.execute(insert(sessions).values(id=session["id"], **values))


@contextmanager
def session_lock(session_id):
    # The container runs a single Uvicorn worker. A fixed lock pool also bounds
    # memory when clients create many different session ids.
    with _turn_locks[hash(session_id) % len(_turn_locks)]:
        yield
