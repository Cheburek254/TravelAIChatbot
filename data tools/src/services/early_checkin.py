import re
from datetime import datetime, timedelta


def early_checkin_request(message):
    text = message.lower().replace('ё', 'е')
    if re.match(r'\s*(?:почему|расскажи|объясни|сколько|как)\b', text) or 'не меняй' in text:
        return None
    if not re.search(r'ранн\w*\s+(?:заезд|заселен)|засел\w*.{0,15}раньше', text):
        return None
    if re.search(r'убери|отмени|без\s+ранн', text):
        return False
    if re.search(r'оформ|добав|подключ|хочу|сделай|давай|нужен', text):
        return True
    return None


def early_arrival(hotel, flight, transfer, checkin_date):
    arrival = datetime.fromisoformat(flight.get('arrival_iso') or f"{flight.get('arrival_date', checkin_date)}T{flight['arrival_time']}")
    at_hotel = arrival + timedelta(minutes=35 + int(transfer.get('duration_minutes', 40)))
    standard = datetime.fromisoformat(f"{checkin_date}T{hotel.get('checkin_time','14:00')}").replace(tzinfo=arrival.tzinfo)
    return bool(hotel.get('early_checkin_available')) and at_hotel.date().isoformat() == checkin_date and at_hotel < standard
