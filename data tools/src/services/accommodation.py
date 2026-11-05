"""Answer room-capacity questions from the saved calculation, without promises."""
import re
from src.services.travel_party import party_factors


def requested_room_count(message):
    text = message.lower().replace('ё', 'е')
    if re.search(r'не\s+(?:меняй|изменяй|хочу|надо|нужно)|\b(?:почему|сколько|расскажи|объясни)\b', text):
        return None
    number = r'(\d+|один|одном|одну|два|двух|две|три|трех|четыре|четырех|пять)'
    matches = list(re.finditer(r'\b' + number + r'\s+(?:номер\w*|комнат\w*)\b', text))
    matches = [m for m in matches if not re.search(r'\b(?:не|вместо|из|с)\s*$', text[:m.start()])]
    if not matches:
        return None
    if not re.search(r'можно|хочу|нуж\w*|давай|сделай|засел|размест|помен|измени|уменьш|увелич|возьм|заброни|остав|пересчит', text):
        return None
    value = matches[-1][1]
    return int(value) if value.isdigit() else {
        'один': 1, 'одном': 1, 'одну': 1, 'два': 2, 'двух': 2, 'две': 2,
        'три': 3, 'трех': 3, 'четыре': 4, 'четырех': 4, 'пять': 5,
    }[value]


def validate_room_count(adults, ages, room_count):
    minimum = party_factors(adults, ages)['rooms']
    if room_count is None:
        return minimum
    if isinstance(room_count, bool) or not isinstance(room_count, int) or not 1 <= room_count <= 10:
        raise ValueError('Количество номеров должно быть целым числом от 1 до 10.')
    if room_count < minimum:
        raise ValueError(f'Для {adults + len(ages)} гостей нужно минимум {minimum} номеров: '
                         'в демотарифе два места на номер, дети с 2 лет занимают место. '
                         'Семейные номера и дополнительные кровати каталогом не подтверждены. '
                         'Число гостей не уменьшаю; текущие карточки и смета сохранены.')
    return room_count


def accommodation_reply(session, selected_option, message):
    text = message.lower().replace("ё", "е")
    if not re.search(r"\b(?:один|одном|одну|1)\s+(?:номер\w*|комнат\w*)\b", text):
        return None
    options = session.get("options", {})
    selected = options.get(selected_option, {})
    if not selected.get("available", True) or not selected:
        selected = next((o for o in options.values() if o.get("available", True)), {})
    if not selected:
        return None
    hotel = selected.get("hotel", {})
    rooms = hotel.get("rooms", selected.get("fairPriceBreakdown", {}).get("rooms", 1))
    party = selected.get("travellers", {})
    ages = party.get("children_ages", [])
    answer = (f"В текущей карточке «{hotel.get('name', selected.get('title', 'Отель'))}» рассчитано "
              f"**{rooms} {'номер' if rooms == 1 else 'номера' if rooms < 5 else 'номеров'}**. "
              "Демотариф предусматривает два места в номере; ребёнок с 2 лет занимает отдельное место, "
              "младенец до 2 лет — без отдельного места.")
    if rooms > 1:
        answer += ("\n\nРазмещение всей семьи в одном номере текущим каталогом не подтверждено: "
                   "нет данных о семейном номере или дополнительной кровати. "
                   "Поэтому не меняю число номеров и смету и не обещаю такое размещение.")
    elif ages:
        answer += "\n\nВся указанная семья уже учтена в одном номере по этому демотарифу. Детская кроватка предоставляется только по запросу и правилам отеля."
    return answer
