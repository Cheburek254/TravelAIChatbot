"""Supported departure cities, aliases and demo route adjustments."""
import re
CITIES = {
    "Москва": ("MOW", 1.0, 0), "Санкт-Петербург": ("LED", 1.1, 0.5),
    "Казань": ("KZN", 1.05, 0.2), "Екатеринбург": ("SVX", 1.15, 1),
    "Новосибирск": ("OVB", 1.2, 1.5), "Сочи": ("AER", 1.05, 0.3),
    "Калининград": ("KGD", 1.1, 0.5), "Самара": ("KUF", 1.05, 0.2),
    "Нижний Новгород": ("GOJ", 1.05, 0.2), "Уфа": ("UFA", 1.1, 0.5),
    "Красноярск": ("KJA", 1.25, 2), "Минеральные Воды": ("MRV", 1.05, 0.2),
    "Иркутск": ("IKT", 1.3, 2.5), "Владивосток": ("VVO", 1.5, 4),
    "Махачкала": ("MCX", 1.05, 0.3),
    "Краснодар": ("KRR", 1.05, 0.2), "Ростов-на-Дону": ("ROV", 1.1, 0.4),
}
ALIASES = {"питер": "Санкт-Петербург", "спб": "Санкт-Петербург", "петербург": "Санкт-Петербург",
           "из питера": "Санкт-Петербург"}
ALIASES.update({'мск': 'Москва', 'екб': 'Екатеринбург', 'нск': 'Новосибирск',
    'нн': 'Нижний Новгород', 'минводы': 'Минеральные Воды', 'крд': 'Краснодар',
    'владик': 'Владивосток', 'ростов': 'Ростов-на-Дону',
    'санкт петербург': 'Санкт-Петербург', 'санкт петербурга': 'Санкт-Петербург'})
ALIASES.update(dict(zip(
    ('москвы', 'санкт-петербурга', 'питера', 'петербурга', 'казани', 'екатеринбурга',
     'новосибирска', 'калининграда', 'самары', 'нижнего новгорода', 'уфы', 'красноярска',
     'минеральных вод', 'иркутска', 'владивостока', 'махачкалы', 'краснодара', 'ростова-на-дону'),
    ('Москва', 'Санкт-Петербург', 'Санкт-Петербург', 'Санкт-Петербург', 'Казань', 'Екатеринбург',
     'Новосибирск', 'Калининград', 'Самара', 'Нижний Новгород', 'Уфа', 'Красноярск',
     'Минеральные Воды', 'Иркутск', 'Владивосток', 'Махачкала', 'Краснодар', 'Ростов-на-Дону'))))
_ORIGIN_LOCATION = r'\b(?:из|город\s+вылета\s*[:—-]?)\s+([a-zа-я-]+(?:\s+[a-zа-я-]+){0,2})'
_ORIGIN_STOP = r'\s+(?:в|во|на|с|со|до|после|утром|вечером|бюджет)\b'


def extract_origin_request(message):
    text = message.lower().replace('ё', 'е').strip()
    if is_origin_info_request(message):
        return None
    if re.match(r'(?:почему|зачем|расскажи|объясни|во сколько|сколько)\b', text):
        return None
    travel_context = bool(re.search(r'лечу|летим|лететь|летать|вылет|улет|отправ|еду|едем|поедем|выезд', text) or text.startswith('из '))
    match = re.search(_ORIGIN_LOCATION, text)
    if not match:
        return None
    candidate = re.split(_ORIGIN_STOP, match[1])[0]
    if re.match(r'како\w*|каки\w*', candidate):
        return None
    names = {**{name.lower(): name for name in CITIES}, **ALIASES,
             **{code.lower(): name for name, (code, _, _) in CITIES.items()}}
    for alias in sorted(names, key=len, reverse=True):
        if re.match(re.escape(alias) + r'(?!\w)', candidate):
            return names[alias]
    return candidate if travel_context else None


def destination_text(message):
    """Do not interpret a departure resort as the destination as well."""
    if not extract_origin_request(message):
        return message
    match = re.search(_ORIGIN_LOCATION, message.lower())
    if not match:
        return message
    candidate = re.split(_ORIGIN_STOP, match[1])[0]
    return message[:match.start(1)] + ' ' * len(candidate) + message[match.start(1) + len(candidate):]


def is_origin_info_request(message):
    text = message.lower()
    return bool(re.search(r'(?:какие|каких|доступные|возможные).{0,25}город.{0,25}(?:вылет|отправ)|откуда.{0,20}(?:вылет|лететь|летать)', text))


def origin_choices_reply(unsupported=None):
    prefix = f'Город вылета «{unsupported}» пока не поддерживается каталогом. ' if unsupported else ''
    return prefix + 'Доступные города вылета: ' + ', '.join(CITIES) + '. Выберите город в шапке или напишите его в чате. Наличие подходящих рейсов проверяется отдельно; другой город без вашего выбора не подставляю.'


def normalize_origin(value):
    normalized = (value or "").strip().lower()
    if normalized in ALIASES:
        return ALIASES[normalized]
    for name, (code, _, _) in CITIES.items():
        if normalized in (name.lower(), code.lower()):
            return name
    raise ValueError("Неизвестный город вылета. Выберите город из списка в шапке поездки.")
