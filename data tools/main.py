import argparse
import uvicorn
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Запуск TravelAIChatbot")
    parser.add_argument(
        "--yandex-rasp",
        choices=("true", "false"),
        help="Включить (true) или отключить (false, мок-данные) API Яндекс Расписаний",
    )
    parser.add_argument(
        "--no-yandex-rasp",
        action="store_true",
        help="Отключить API Яндекс Расписаний и использовать мок-данные",
    )
    args, _ = parser.parse_known_args()
    if args.no_yandex_rasp:
        os.environ["YANDEX_RASP_ENABLED"] = "false"
    elif args.yandex_rasp is not None:
        os.environ["YANDEX_RASP_ENABLED"] = args.yandex_rasp

    port = int(os.environ.get("APP_PORT", 8080))
    host = os.environ.get("APP_HOST", "0.0.0.0")
    print(f"🚀 Запуск TravelAIChatbot на http://{host}:{port}")
    uvicorn.run("src.api.app:app", host=host, port=port, reload=False)
