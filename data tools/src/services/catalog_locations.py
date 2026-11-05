"""One exact destination resolver for hotel, route and agent searches."""
import re

ALIASES = {
    "so": "sochi", "sochi": "sochi", "сочи": "sochi", "адлер": "sochi",
    "dubai": "dubai", "дубай": "dubai", "оаэ": "dubai",
    "phuket": "phuket", "пхукет": "phuket", "таиланд": "phuket",
    "gesh": "sheregesh", "sheregesh": "sheregesh", "шерегеш": "sheregesh",
    "altai": "altay", "altay": "altay", "алтай": "altay", "горно-алтайск": "altay",
    "istanbul": "istanbul", "стамбул": "istanbul", "турция": "istanbul",
    "kaliningrad": "kaliningrad", "калининград": "kaliningrad",
    "maldives": "maldives", "мальдивы": "maldives",
    "dagestan": "dagestan", "дагестан": "dagestan", "махачкала": "dagestan",
    "дербент": "dagestan", "каспийск": "dagestan", "bali": "bali", "бали": "bali", "денпасар": "bali",
}


def destination_id(value):
    value = re.split(r"→|->", (value or "").strip().lower())[-1].strip()
    if value in ALIASES:
        return ALIASES[value]
    matches = {key for alias, key in ALIASES.items() if len(alias) > 2 and
               re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", value)}
    return next(iter(matches)) if len(matches) == 1 else None
