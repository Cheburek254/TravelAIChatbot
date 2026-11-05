import os
from pathlib import Path
from typing import Optional, Dict, Any
from typing import Literal
from uuid import uuid4
from datetime import date
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.tools.travel_tools import (
    search_destinations,
    search_hotels,
    search_transfers_and_flights,
    get_weather_forecast
)
from src.tools.tool_definitions import OPENAI_TOOL_DEFINITIONS, execute_tool_call
from src.models.schemas import (
    DestinationSearchParams,
    HotelSearchParams,
    TransferFlightSearchParams,
    WeatherForecastParams
)
from src.services.agent_orchestrator import (
    run_agent_turn,
)
from src.services.logistics_engine import BookingCartAssembler
from src.services.agent_orchestrator import build_trip_response, restore_user_budget
from src.services.database import get_engine, load_session, save_session, session_lock
from src.services.openrouter_agent import run_openrouter_turn, is_configured, AgentUnavailable
from src.services.trip_planner import enforce_saved_budget
from src.services.chat_context import public_chat_state, repair_corrupt_history, sync_destination_suggestions
from src.services.trip_actions import is_alternative_request, is_cheapest_request
from src.services.budget_constraints import is_budget_only_request
from src.services.travel_preferences import inspiration_styles, restore_travel_styles, enforce_saved_styles
from src.services.flight_preferences import is_flight_change_request
from src.services.departure_cities import CITIES, extract_origin_request, is_origin_info_request
from src.services.hotel_preferences import is_hotel_change_request
from src.services.travel_party import ChildAge
from src.services.chat_language import normalize_chat_text
from src.services.early_checkin import early_checkin_request
from src.services.accommodation import requested_room_count


@asynccontextmanager
async def lifespan(app):
    get_engine()
    yield

app = FastAPI(
    lifespan=lifespan,
    title="TravelAIChatbot API",
    description="API чата и инструментов планирования поездок.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatPayload(BaseModel):
    message: str = Field(min_length=1, max_length=6000)
    selected_option: Literal["A", "B"] = "A"
    session_id: str = Field(default_factory=lambda: str(uuid4()), min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    action_id: Optional[Literal["compare", "select_a", "select_b", "checkout", "plan", "meal_on", "meal_off", "rebuild", "alternatives", "choose_destination", "change_dates", "edit_trip", "change_origin", "change_guests", "change_hotels", "set_budget", "cheapest", "inspire_mountains", "inspire_sea"]] = None
    origin: Optional[str] = Field(None, min_length=1, max_length=100)
    adults: Optional[int] = Field(None, ge=1, le=10)
    children_ages: Optional[list[ChildAge]] = Field(None, max_length=9)
    pet_friendly: Optional[bool] = None
    departure_time: Optional[str] = Field(None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    arrival_time: Optional[str] = Field(None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    destination: Optional[str] = Field(None, max_length=100)
    checkin_date: Optional[date] = None
    checkout_date: Optional[date] = None
    passengers: Optional[int] = Field(None, ge=1, le=10)
    budget_min_rub: Optional[int] = Field(None, ge=0, le=10000000)
    budget_rub: Optional[int] = Field(None, ge=0, le=10000000)


class BookingPayload(BaseModel):
    trip: Optional[Dict[str, Any]] = None
    total_price: Optional[int] = 0


@app.get("/health", tags=["Health"])
def health_check():
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "service": "travel-ai-chatbot"}


@app.get("/api/trips/initial", tags=["Frontend & Agent"])
def api_get_initial_trips(session_id: str = ""):
    session_id = session_id or str(uuid4())
    if not 8 <= len(session_id) <= 128 or not all(c.isascii() and (c.isalnum() or c in "_-") for c in session_id):
        raise HTTPException(status_code=422, detail="Некорректный идентификатор сессии")
    with session_lock(session_id):
        session = load_session(session_id)
        changed = restore_user_budget(session)
        changed = restore_travel_styles(session) or changed
        changed = repair_corrupt_history(session) or changed
        changed = enforce_saved_budget(session) or changed
        changed = enforce_saved_styles(session) or changed
        changed = sync_destination_suggestions(session) or changed
        cap = session["state"].get("budget_rub")
        if changed:
            save_session(session)
        if not session["state"] and not session["messages"] and session["options"]:
            # Remove legacy example cards from sessions with no user history.
            session["options"] = {}
            save_session(session)
        return {**session["options"], "sessionId": session_id,
                "departureCities": list(CITIES),
                "options": session["options"], "planStatus": session["state"].get("plan_status", "empty"),
                "chatState": public_chat_state(session),
                "planMessage": session["state"].get("plan_message", ""), "budget_rub": cap,
                "messages": session["messages"], "selectedOption": session["selected_option"],
                "agent": "openrouter" if os.getenv("OPENROUTER_API_KEY", "").strip() else "groq" if is_configured() else "demo"}


@app.post("/api/chat", tags=["Frontend & Agent"])
def api_agent_chat(payload: ChatPayload):
    if not payload.message.strip():
        raise HTTPException(status_code=422, detail="Сообщение не должно быть пустым")
    try:
        with session_lock(payload.session_id):
            saved = load_session(payload.session_id)
            normalized = normalize_chat_text(payload.message, saved['messages'])
            original = payload.message
            payload = payload.model_copy(update={'message': normalized})
            result = _dispatch_chat(payload)
            if original != normalized:
                session = load_session(payload.session_id)
                for item in reversed(session['messages']):
                    if item.get('role') == 'user':
                        item['content'] = original
                        break
                save_session(session)
            return {**result, 'sessionId': payload.session_id}
    except AgentUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _dispatch_chat(payload):
    if is_configured() or payload.action_id or is_alternative_request(payload.message) or is_cheapest_request(payload.message) or is_budget_only_request(payload.message) or inspiration_styles(payload.message) or is_flight_change_request(payload.message) or extract_origin_request(payload.message) or is_origin_info_request(payload.message) or is_hotel_change_request(payload.message) or early_checkin_request(payload.message) is not None or requested_room_count(payload.message) is not None:
        result = run_openrouter_turn(payload.session_id, payload.message, payload.selected_option, action_id=payload.action_id,
            action_data=payload.model_dump(mode="json", exclude={"message", "session_id", "selected_option", "action_id"}, exclude_none=True))
    else:
        result = run_agent_turn(payload.session_id, payload.message, payload.selected_option)
        result["agent"] = "demo"
    return result

@app.post("/api/bookings", tags=["Frontend & Agent"])
def api_create_booking(payload: BookingPayload):
    return BookingCartAssembler.create_voucher_and_receipt(
        trip=payload.trip,
        total_price=payload.total_price,
    )


@app.get("/api/tools/schemas", tags=["Agent Integration"])
def get_tool_schemas():
    return {"tools": OPENAI_TOOL_DEFINITIONS}


@app.post("/api/tools/execute", tags=["Agent Integration"])
def run_tool(payload: Dict[str, Any]):
    name = payload.get("name")
    args = payload.get("arguments", {})
    if not name:
        raise HTTPException(status_code=400, detail="Missing 'name' field")
    return execute_tool_call(name, args)


@app.get("/api/tools/destinations", tags=["Tools"])
@app.post("/api/tools/destinations", tags=["Tools"])
def api_search_destinations(params: Optional[DestinationSearchParams] = None):
    p = params or DestinationSearchParams()
    return search_destinations(
        query=p.query,
        month=p.month,
        min_temp=p.min_temp,
        vibe=p.vibe,
        max_flight_hours=p.max_flight_hours,
        budget_tier=p.budget_tier,
        limit=p.limit
    )


@app.get("/api/tools/hotels", tags=["Tools"])
@app.post("/api/tools/hotels", tags=["Tools"])
def api_search_hotels(params: HotelSearchParams):
    return search_hotels(
        destination=params.destination,
        checkin_date=params.checkin_date,
        checkout_date=params.checkout_date,
        guests=params.guests,
        max_price_per_night=params.max_price_per_night,
        min_rating=params.min_rating,
        pet_friendly=params.pet_friendly,
        baby_crib=params.baby_crib,
        no_deposit=params.no_deposit,
        free_cancellation=params.free_cancellation,
        meal_type=params.meal_type,
        max_distance_to_center_km=params.max_distance_to_center_km,
        max_distance_to_beach_m=params.max_distance_to_beach_m,
        vibe_query=params.vibe_query,
        limit=params.limit
    )


@app.get("/api/tools/transfers-flights", tags=["Tools"])
@app.post("/api/tools/transfers-flights", tags=["Tools"])
def api_search_transfers_and_flights(params: TransferFlightSearchParams):
    return search_transfers_and_flights(**params.model_dump(exclude_none=True))


@app.get("/api/tools/weather", tags=["Tools"])
@app.post("/api/tools/weather", tags=["Tools"])
def api_get_weather(params: WeatherForecastParams):
    return get_weather_forecast(
        city=params.city,
        date=params.date,
        days=params.days
    )


@app.get("/tools-dashboard", response_class=HTMLResponse, tags=["Dashboard"])
def interactive_dashboard():
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <title>TravelAIChatbot — инструменты</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }
            .container { max-width: 1000px; margin: 0 auto; }
            h1 { color: #38bdf8; display: flex; align-items: center; gap: 10px; }
            .card { background: #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid #334155; }
            .badge { display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: bold; background: #0284c7; color: white; margin-bottom: 8px; }
            button { background: #38bdf8; color: #0f172a; border: none; padding: 10px 18px; border-radius: 8px; font-weight: bold; cursor: pointer; transition: 0.2s; }
            button:hover { background: #0284c7; color: white; }
            pre { background: #090d16; padding: 14px; border-radius: 8px; overflow-x: auto; color: #a5f3fc; font-size: 13px; max-height: 250px; }
            a { color: #38bdf8; text-decoration: none; }
            .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🏖️ TravelAIChatbot — инструменты планирования</h1>
            <p>Модуль данных, мок-сервисов и инструментов поиска для AI-агента путешествий.</p>
            <p>Основной UI: <a href="/">/ (React App)</a> | Документация OpenAPI: <a href="/docs" target="_blank">/docs (Swagger UI)</a> | Health: <a href="/health">/health</a></p>
            <div class="grid">
                <div class="card">
                    <span class="badge">Tool 1</span>
                    <h3>search_destinations</h3>
                    <button onclick="testTool('dest')">Тестировать 'тепло в ноябре'</button>
                    <pre id="res-dest">// Нажмите кнопку для теста</pre>
                </div>
                <div class="card">
                    <span class="badge">Tool 2</span>
                    <h3>search_hotels</h3>
                    <button onclick="testTool('hotel')">Тестировать отели Шерегеша</button>
                    <pre id="res-hotel">// Нажмите кнопку для теста</pre>
                </div>
                <div class="card">
                    <span class="badge">Tool 3</span>
                    <h3>search_transfers_and_flights</h3>
                    <button onclick="testTool('flight')">Тестировать рейс в Сочи</button>
                    <pre id="res-flight">// Нажмите кнопку для теста</pre>
                </div>
                <div class="card">
                    <span class="badge">Tool 4</span>
                    <h3>get_weather_forecast</h3>
                    <button onclick="testTool('weather')">Тестировать погоду в Дубае</button>
                    <pre id="res-weather">// Нажмите кнопку для теста</pre>
                </div>
            </div>
        </div>
        <script>
            async function testTool(type) {
                let pre = document.getElementById('res-' + type);
                pre.innerText = "Загрузка...";
                let map = {
                    dest: ['/api/tools/destinations', { query: 'хочу где тепло в ноябре с ребенком к морю', limit: 2 }],
                    hotel: ['/api/tools/hotels', { destination: 'Шерегеш', vibe_query: 'шале камин', pet_friendly: true, limit: 2 }],
                    flight: ['/api/tools/transfers-flights', { destination: 'Сочи', date: '2026-11-15', hotel_checkin_time: '14:00' }],
                    weather: ['/api/tools/weather', { city: 'Дубай', days: 5 }]
                };
                let [url, body] = map[type];
                let r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
                pre.innerText = JSON.stringify(await r.json(), null, 2);
            }
        </script>
    </body>
    </html>
    """


FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST_DIR", "/app/frontend_dist"))
if not FRONTEND_DIST.exists():
    alt_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if alt_dist.exists():
        FRONTEND_DIST = alt_dist

if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


@app.get("/", response_class=HTMLResponse)
def root_page():
    index_file = FRONTEND_DIST / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return interactive_dashboard()
