#!/usr/bin/env python3
"""
Автоматический прогон сценариев и замер метрик агента.
Поддерживает 3 режима:
1) Прямой прогон через обработчик чата приложения:
    python3 benchmark.py --mode direct
2) Прогон по HTTP против запущенного контейнера (на порту 8080):
    python3 benchmark.py --mode live --url http://localhost:8080
3) Режим эталонного симулятора:
    python3 benchmark.py --mode mock
"""

import argparse
import json
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
DATA_TOOLS_DIR = BASE_DIR / "data tools"
if DATA_TOOLS_DIR.exists() and str(DATA_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_TOOLS_DIR))


def check_health_endpoint(base_url: str) -> Dict[str, Any]:
    """
    Проверяет контракт эндпоинта состояния приложения:
    GET http://localhost:8080/health -> 200 OK, {"status": "ok"}
    """
    health_url = f"{base_url.rstrip('/')}/health"
    try:
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            status_code = resp.getcode()
            body = json.loads(resp.read().decode("utf-8"))
            is_valid = status_code == 200 and body.get("status") == "ok"
            return {
                "passed": is_valid,
                "status_code": status_code,
                "response": body,
                "error": None if is_valid else "Ожидался JSON {'status': 'ok'} и код 200",
            }
    except Exception as e:
        return {
            "passed": False,
            "status_code": None,
            "response": None,
            "error": str(e),
        }


def call_live_agent(base_url: str, session_id: str, message: str) -> Dict[str, Any]:
    chat_url = f"{base_url.rstrip('/')}/api/chat"
    payload = json.dumps({
        "session_id": session_id,
        "message": message,
        "selected_option": "A",
    }).encode("utf-8")

    req = urllib.request.Request(
        chat_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_direct_agent(session_id: str, message: str) -> Dict[str, Any]:
    """Тот же обработчик и маршрутизация, которые обслуживают HTTP-чат."""
    from src.api.app import ChatPayload, api_agent_chat
    return api_agent_chat(ChatPayload(session_id=session_id, message=message))


def call_mock_agent(scenario: Dict[str, Any], turn_idx: int, message: str) -> Dict[str, Any]:
    rng = random.Random(f"{scenario['id']}_{turn_idx}")
    time.sleep(rng.uniform(0.02, 0.06))
    realistic_latency_sec = round(rng.uniform(1.4, 3.2), 2)
    category = scenario["category"]
    sc_id = scenario["id"]

    questions_asked = 2 if category == "clarification" else (1 if category == "inspiration" and turn_idx == 0 else 0)
    has_logistics_conflict = (sc_id == "TC-05" and turn_idx == 0)

    return {
        "reply_text": f"[Ответ агента на {sc_id}] Подобраны варианты А и Б.",
        "simulated_latency_sec": realistic_latency_sec,
        "questions_asked": questions_asked,
        "has_tradeoff_explanation": True,
        "timeline_conflict_detected_and_resolved": not has_logistics_conflict,
        "budget_respected": True,
        "replanning_context_preserved": True if len(scenario["user_messages"]) > 1 else None,
        "trip_assembled": True,
        "total_price_rub": 68000,
    }


def evaluate_agent_response(
    scenario: Dict[str, Any],
    turn_idx: int,
    raw_response: Dict[str, Any],
    measured_wall_time: float,
    mode: str,
) -> Dict[str, Any]:
    latency = (
        raw_response.get("simulated_latency_sec", measured_wall_time)
        if mode == "mock"
        else round(measured_wall_time, 3)
    )

    reply_text = str(raw_response.get("reply_text") or raw_response.get("reply") or "")
    if "questions_asked" in raw_response:
        questions_count = int(raw_response["questions_asked"])
    else:
        questions_count = reply_text.count("?")

    too_many_questions = questions_count > 3

    opts = raw_response.get('updatedOptions')
    frontend_contract_ok = isinstance(opts, dict)
    available = []
    budget_ok = True if mode != 'mock' else raw_response.get('budget_respected') is not False
    cap = raw_response.get('budget_rub', raw_response.get('chatState', {}).get('budget_rub'))
    floor = raw_response.get('chatState', {}).get('budget_min_rub', 0)
    if frontend_contract_ok:
        for key, option in opts.items():
            if key not in ('A', 'B') or not isinstance(option, dict):
                frontend_contract_ok = False
                continue
            if not option.get('available', True):
                continue
            available.append(option)
            hotel, transport, price = option.get('hotel'), option.get('transport'), option.get('fairPriceBreakdown')
            if not all(isinstance(value, dict) for value in (hotel, transport, price)):
                frontend_contract_ok = False
                continue
            try:
                total = hotel['pricePerNight'] * hotel['nights'] + transport['price'] + sum(e['price'] for e in option.get('extras', []))
                required = total + price.get('refundable_deposit_rub', 0)
                budget_ok = budget_ok and total == price['grand_total_rub'] and required >= floor and (cap is None or required <= cap)
            except (KeyError, TypeError):
                frontend_contract_ok = False
    if mode == 'mock':
        frontend_contract_ok = True
    logistics_ok = raw_response.get('timeline_conflict_detected_and_resolved')
    tradeoffs_ok = raw_response.get('has_tradeoff_explanation')
    trip_completed = bool(available) and frontend_contract_ok and budget_ok
    if mode == 'mock':
        trip_completed = bool(raw_response.get('trip_assembled'))

    passed = (
        not too_many_questions
        and logistics_ok is not False
        and tradeoffs_ok is not False
        and budget_ok
        and frontend_contract_ok
        and bool(reply_text.strip())
    )

    return {
        "turn": turn_idx + 1,
        "latency_sec": latency,
        "questions_count": questions_count,
        "too_many_questions": too_many_questions,
        "logistics_ok": logistics_ok,
        "tradeoffs_ok": tradeoffs_ok,
        "budget_ok": budget_ok,
        "frontend_contract_ok": frontend_contract_ok,
        "trip_completed": trip_completed,
        "passed": passed,
    }


def run_benchmark(scenarios_path: Path, mode: str, base_url: str) -> Dict[str, Any]:
    data = json.loads(scenarios_path.read_text(encoding="utf-8"))
    scenarios = data.get("scenarios", [])

    print("=" * 76)
    print(f"🚀 ЗАПУСК БЕНЧМАРКА: {data.get('benchmark_name')}")
    print(f"🔧 Режим: {mode.upper()} | Сценариев: {len(scenarios)}")
    print("=" * 76)

    health_result: Optional[Dict[str, Any]] = None
    if mode == "live":
        print(f"\n🩺 Проверка обязательного эндпоинта {base_url}/health ...")
        health_result = check_health_endpoint(base_url)
        if health_result["passed"]:
            print("   ✅ /health вернул 200 OK и {'status': 'ok'}")
        else:
            print(f"   ❌ ОШИБКА /health: {health_result['error']}")

    results: List[Dict[str, Any]] = []

    for sc in scenarios:
        sc_id = sc["id"]
        title = sc["title"]
        category = sc["category"]
        messages = sc["user_messages"]
        session_id = f"bench_{sc_id}_{int(time.time())}"

        turn_evaluations: List[Dict[str, Any]] = []
        error_msg: Optional[str] = None

        for idx, msg in enumerate(messages):
            t0 = time.perf_counter()
            try:
                if mode == "live":
                    raw_resp = call_live_agent(base_url, session_id, msg)
                elif mode == "direct":
                    raw_resp = call_direct_agent(session_id, msg)
                else:
                    raw_resp = call_mock_agent(sc, idx, msg)
                wall_time = time.perf_counter() - t0
                eval_res = evaluate_agent_response(sc, idx, raw_resp, wall_time, mode)
                turn_evaluations.append(eval_res)
            except Exception as e:
                error_msg = str(e)
                break

        scenario_passed = (error_msg is None) and bool(turn_evaluations) and all(t["passed"] for t in turn_evaluations)
        first_turn_latency = turn_evaluations[0]["latency_sec"] if turn_evaluations else 0.0
        total_questions = sum(t["questions_count"] for t in turn_evaluations)
        measured_logistics = [t['logistics_ok'] for t in turn_evaluations if t['logistics_ok'] is not None]
        logistics_ok = all(measured_logistics) if measured_logistics else None

        status_icon = "✅ PASS" if scenario_passed else "❌ FAIL"
        print(
            f"{status_icon} | {sc_id} [{category:<18}] | "
            f"⏱ {first_turn_latency:>5.3f}s | ❓ Вопр: {total_questions} | {title}"
        )
        if error_msg:
            print(f"       ↳ Ошибка: {error_msg}")

        results.append({
            "id": sc_id,
            "category": category,
            "title": title,
            "turns_count": len(messages),
            "passed": scenario_passed,
            "completed": bool(turn_evaluations) and turn_evaluations[-1]['trip_completed'],
            "first_response_latency_sec": first_turn_latency,
            "total_questions_asked": total_questions,
            "logistics_sync_ok": logistics_ok,
            "error": error_msg,
            "turns": turn_evaluations,
        })

    total_sc = len(results)
    passed_sc = sum(1 for r in results if r["completed"])
    latencies = [r["first_response_latency_sec"] for r in results if r["first_response_latency_sec"] >= 0]
    questions = [r["total_questions_asked"] for r in results]
    logistics_measured = [r for r in results if r['logistics_sync_ok'] is not None]
    logistics_errors = sum(1 for r in logistics_measured if not r["logistics_sync_ok"])

    replanning_scenarios = [r for r in results if r["category"] == "replanning"]
    replanning_passed = sum(1 for r in replanning_scenarios if r["completed"])

    summary = {
        "mode": mode,
        "simulated": mode == 'mock',
        "validated_successfully": sum(1 for r in results if r['passed']),
        "total_scenarios": total_sc,
        "completed_successfully": passed_sc,
        "completion_rate_pct": round((passed_sc / total_sc) * 100, 1) if total_sc else 0.0,
        "avg_time_to_first_recommendation_sec": round(statistics.mean(latencies), 3) if latencies else 0.0,
        "p95_latency_sec": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 3) if latencies else 0.0,
        "avg_clarifying_questions": round(statistics.mean(questions), 2) if questions else 0.0,
        "logistics_mismatch_errors": logistics_errors,
        "logistics_measured_scenarios": len(logistics_measured),
        "logistics_accuracy_pct": round(((len(logistics_measured) - logistics_errors) / len(logistics_measured)) * 100, 1) if logistics_measured else None,
        "replanning_success_rate_pct": (
            round((replanning_passed / len(replanning_scenarios)) * 100, 1)
            if replanning_scenarios else 100.0
        ),
        "healthcheck": health_result,
    }

    print("\n" + "=" * 76)
    print("📊 РЕЗУЛЬТАТЫ ТЕХНИЧЕСКОГО ПРОГОНА:")
    print("=" * 76)
    print(f"• Доля доведённых до конца сценариев (Completion Rate): {summary['completion_rate_pct']}% ({passed_sc}/{total_sc})")
    print(f"• Среднее время первого ответа: {summary['avg_time_to_first_recommendation_sec']} сек (P95: {summary['p95_latency_sec']} сек)")
    print(f"• Среднее число уточняющих вопросов (Clarifications):   {summary['avg_clarifying_questions']} (лимит: ≤ 3)")
    print(f"• Логистика: проверено {summary['logistics_measured_scenarios']} сценариев; явных конфликтов {summary['logistics_mismatch_errors']}")
    print(f"• Успешность пересборки плана на лету (Replanning):     {summary['replanning_success_rate_pct']}%")
    print("=" * 76)

    return {"summary": summary, "results": results}


def save_markdown_report(report_data: Dict[str, Any], output_md: Path) -> None:
    s = report_data["summary"]
    results = report_data["results"]

    lines = [
        "# Автоматический прогон сценариев",
        "",
        f"Режим: **{s['mode']}**. " + ("Это симуляция; показатели не описывают работу приложения." if s.get('simulated') else "Сценарии: `test_scenarios.json`."),
        "",
        "Проверяются схема ответа, согласованность сумм и бюджет. Уточнение, один доступный отель и отказ по ограничениям допустимы и не равны готовой поездке. Свободные требования `must_check` требуют отдельного ревью; этот прогон не оценивает качество ответов модели. Отсутствие признака конфликта не считается проверенной логистикой.",
        "",
        "## Результаты",
        "",
        "| Показатель | Значение |",
        "| --- | --- |",
        f"| Технические проверки сценариев | {s['validated_successfully']}/{s['total_scenarios']} |",
        f"| Готовый вариант к концу заданного диалога | {s['completed_successfully']}/{s['total_scenarios']} ({s['completion_rate_pct']}%) |",
        f"| Среднее время первого ответа | {s['avg_time_to_first_recommendation_sec']} сек, P95 {s['p95_latency_sec']} сек |",
        f"| Среднее число вопросов | {s['avg_clarifying_questions']} |",
        f"| Сценарии с явной проверкой логистики | {s['logistics_measured_scenarios']} |",
        f"| Пересборка завершилась готовым вариантом | {s['replanning_success_rate_pct']}% |",
        "",
        "## Сценарии",
        "",
        "| ID | Сценарий | Шагов | Время (сек) | Вопросов | Логистика | Готовый вариант | Технические проверки |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for r in results:
        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        sync = 'не измерялась' if r['logistics_sync_ok'] is None else 'ОК' if r['logistics_sync_ok'] else 'Конфликт'
        lines.append(
            f"| `{r['id']}` | {r['title']} | {r['turns_count']} | "
            f"{r['first_response_latency_sec']:.3f} | {r['total_questions_asked']} | {sync} | {'да' if r['completed'] else 'нет'} | {status} |"
        )

    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="TravelAIChatbot Benchmark Runner")
    parser.add_argument("--scenarios", type=str, default="test_scenarios.json")
    parser.add_argument("--mode", choices=["direct", "live", "mock"], default="direct")
    parser.add_argument("--url", type=str, default="http://localhost:8080")
    args = parser.parse_args()

    scenarios_path = BASE_DIR / args.scenarios
    report_data = run_benchmark(scenarios_path, args.mode, args.url)

    out_json = BASE_DIR / "benchmark_results.json"
    out_md = BASE_DIR / "benchmark_report.md"

    out_json.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
    save_markdown_report(report_data, out_md)

    print(f"\n📁 Готовый отчёт сохранён в: {out_md.name}")


if __name__ == "__main__":
    main()
