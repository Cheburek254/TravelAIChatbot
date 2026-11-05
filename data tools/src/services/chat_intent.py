"""Distinguish a request to change a trip from a question about it."""
import re
from datetime import date, timedelta


def is_flexible_edit_request(message):
    text = message.lower().strip()
    text = re.sub(r'^(?:(?:а|и|ну|тогда)\s+)+', '', text)
    if re.match(r'(?:почему|зачем|расскажи|объясни|что|как|сколько|во сколько)\b', text) or re.search(r'не\s+меняй|ничего\s+не\s+меня', text):
        return False
    return bool(re.search(r'подешевле|поближе|потише|попозже|неплохо\s+бы|можно.{0,30}(?:подобрать|найти|без|чтобы)|хочу|давай|сделай|подбери|поменяй|измени|смени|замени|выбери', text))


def is_read_only_request(message):
    text = re.sub(r'^(?:(?:а|и|ну|тогда)\s+)+', '', message.lower().strip())
    if re.fullmatch(r'(?:привет(?:ствую|ик)?|здравствуй(?:те)?|добрый\s+(?:день|вечер)|доброе\s+утро|хай|салют)[.!?,\s]*', text):
        return True
    if re.search(r'не\s+меняй|ничего\s+не\s+меня', text):
        return True
    if is_flexible_edit_request(message) or not is_conversation_request(message):
        return False
    return bool(re.search(r'\b(?:расскажи|объясни|почему|зачем|обсудим|поговорим)\b', text) or
                re.match(r'(?:что|как|сколько|во сколько|како\w*|каки\w*|можно\s+ли|есть\s+ли|подскажи|спасибо)\b', text))


def is_conversation_request(message):
    text = re.sub(r"^\s*(?:(?:а|и|ну|тогда)\s+)+", "", message.lower()).strip()
    stripped = re.sub(
        r"^(?:(?:привет(?:ствую|ик)?|здравствуй(?:те)?|добр(?:ый|ое|ого)\s+(?:день|вечер|утро|времени(?:\s+суток)?)|хай|хеллоу|салют)\b[.,!?\s—–-]*)+",
        "",
        text,
    ).strip()
    if not stripped:
        return True
    text = re.sub(r"^\s*(?:(?:а|и|ну|тогда)\s+)+", "", stripped).strip()
    if re.match(r"(?:можно(?:\s+ли)?|можем(?:\s+ли)?|давай(?:те)?)\s+(?:изменить|поменять|увеличить|уменьшить|установить|добавить|убрать|снять|перенести)\b", text):
        return False
    if re.match(r"(?:собер(?:и|ите)|пересобер(?:и|ите)|подбер(?:и|ите)|найд(?:и|ите)|добавь(?:те)?|убер(?:и|ите)|измен(?:и|ите)|перенес(?:и|ите)|выбер(?:и|ите)|установ(?:и|ите))\b", text):
        return False
    return bool(text.endswith("?") or re.search(r"\b(?:обсудим|поговорим)\b", text) or re.match(r"(?:расскаж(?:и|ите)|объясн(?:и|ите)|подробнее|почему|зачем|чем|что\b|как\b|сколько|какой\b|какая\b|какое\b|какие\b|каком\b|можно\s+ли|есть\s+ли|подскажи\b|спасибо\b|покаж(?:и|ите)\s+(?:условия|подробности))", text))


def is_plan_command(message):
    if is_conversation_request(message):
        return False
    return bool(re.search(r"\b(?:собер(?:и|ите)|собрать|пересобер(?:и|ите)|подбер(?:и|ите)|подобрать|найд(?:и|ите)|готов(?:ый|ые)?\s+план)\b", message.lower()))


def extract_passengers(message):
    t = message.lower()
    if re.search(r"\b(?:ни\s+один|один\s+из|один\s+день|один\s+час|один\s+раз|один\s+номер)\b", t):
        pass
    elif re.search(r"\b(?:я\s+)?(?:еду|лечу|поеду|буду|путешествую)?\s*(?:один|одна|одному|одной|соло)\b|\b1\s*(?:гость|человек|пассажир|взрослый)\b", t):
        return 1
    if re.search(r"\b(?:вдво[её]м|дво[её]|пара|парой|с\s+девушкой|с\s+парнем|с\s+женой|с\s+мужем|2\s*(?:гостя|человека|пассажира|взрослых))\b", t):
        return 2
    if re.search(r"\b(?:втро[её]м|тро[её]|троих|3\s*(?:гостя|человека|пассажира|взрослых))\b", t):
        return 3
    if re.search(r"\b(?:вчетвером|четверо|четверых|4\s*(?:гостя|человека|пассажира|взрослых))\b", t):
        return 4
    m = re.search(r"\b([1-9]|10)\s*(?:гост[яей]|человек[а]?|пассажир[аов]?|взросл[ых]+)\b", t)
    if m:
        return int(m.group(1))
    return None


def extract_nights_and_dates(message, current_state=None):
    t = message.lower()
    patch = {}
    if re.search(r"\bвыходн\w*|\bуикенд\w*|\bуик-энд\w*", t):
        patch["nights"] = 2
        today = date.today()
        days_ahead = (4 - today.weekday()) % 7
        if days_ahead == 0 and today.weekday() == 4:
            days_ahead = 0
        elif days_ahead == 0:
            days_ahead = 7
        friday = today + timedelta(days=days_ahead)
        sunday = friday + timedelta(days=2)
        patch["checkin_date"] = friday.isoformat()
        patch["checkout_date"] = sunday.isoformat()
    elif re.search(r"\bнедел\w*|\b7\s*(?:дней|ночей|дня|ночи)\b", t):
        patch["nights"] = 7
        cur_start = (current_state or {}).get("checkin_date")
        if cur_start:
            try:
                start = date.fromisoformat(cur_start)
                patch["checkout_date"] = (start + timedelta(days=7)).isoformat()
            except ValueError:
                pass
    else:
        m = re.search(r"\b(\d+)\s*(?:ноч\w*|дн\w*|суто?к\w*)\b", t)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 30:
                patch["nights"] = n
                cur_start = (current_state or {}).get("checkin_date")
                if cur_start:
                    try:
                        start = date.fromisoformat(cur_start)
                        patch["checkout_date"] = (start + timedelta(days=n)).isoformat()
                    except ValueError:
                        pass
    months = ('январ', 'феврал', 'март', 'апрел', 'ма[йя]', 'июн', 'июл', 'август', 'сентябр', 'октябр', 'ноябр', 'декабр')
    for month, stem in enumerate(months, 1):
        match = re.search(r'\b(?:(?:с|со)\s+)?(\d{1,2})(?:\s*(?:по|до|[-–—])\s*(\d{1,2}))?\s*' + stem + r'\w*(?:\s+(20\d{2}))?', t)
        if not match:
            continue
        year = int(match[3]) if match[3] else date.today().year
        start = date(year, month, int(match[1]))
        if not match[3] and start < date.today():
            year += 1
            start = date(year, month, int(match[1]))
        patch['checkin_date'] = start.isoformat()
        if match[2]:
            end = date(year, month, int(match[2]))
        else:
            end = start + timedelta(days=patch.get('nights', (current_state or {}).get('nights', 4)))
        patch.update(checkout_date=end.isoformat(), nights=(end-start).days)
        break
    return patch


def extract_pet_friendly(message):
    t = message.lower()
    if re.search(r"\b(?:без\s+(?:питом\w*|собак\w*|животн\w*|кош\w*)|(?:убери|отмени)\s+питом\w*)", t):
        return False
    if re.search(r"\b(?:с\s+)?(?:собак\w*|кошк\w*|котом|котиком|питомц\w*|животн\w*|корги|псом|песиком|пёсиком)\b", t):
        return True
    return None
