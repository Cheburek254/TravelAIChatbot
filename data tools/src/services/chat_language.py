"""Lossless common shorthand expansion before intent parsing; history stays raw."""
import re


def normalize_chat_text(message, messages=()):
    text = message
    ordinals = {'первого': '1', 'первое': '1', 'второго': '2', 'второе': '2', 'третьего': '3', 'третье': '3', 'четвертого': '4', 'четвёртого': '4', 'четвертое': '4', 'четвёртое': '4', 'пятого': '5', 'пятое': '5'}
    text = re.sub(r'\b(с|со|по|до)\s+(' + '|'.join(ordinals) + r')\b', lambda m: m[1] + ' ' + ordinals[m[2].lower()], text, flags=re.I)
    for pattern, replacement in (
        (r'\b(?:пж|плиз)\b', 'пожалуйста'), (r'\bучетвером\b', 'вчетвером'),
        (r'\b(\d+)\s*взр\.?\b', r'\1 взрослых'),
        (r'\bреб\.?\s*(\d{1,2})\b', r'ребёнок \1 лет'),
        (r'\b(\d+)\s*н\b', r'\1 ночи'),
        (r'\bсотк[аиу]\b', '100000 рублей'),
        (r'\b(\d+)\s*штук\b', r'\1 тысяч рублей'),
        (r'\bчто[ -]?(?:нить|нибудь)\b', 'что-нибудь'),
    ):
        text = re.sub(pattern, replacement, text, flags=re.I)
    if re.fullmatch(r'\s*(?:а\s+)?(?:можно\s+)?(?:ещ[её]\s+)?(?:попозже|позже)[?!,.\s]*', text, re.I):
        recent = ''
        for item in reversed(list(messages)[-8:]):
            if item.get('role') != 'user':
                continue
            candidate = item.get('content', '')
            if re.search(r'вылет|прил[её]т|рейс|верну|обратн|отел|дат[ыау]|ноч|питан', candidate, re.I):
                recent = candidate
                break
        if re.search(r'вылет|прил[её]т|рейс|верну|обратн', recent, re.I):
            subject = 'обратный вылет' if re.search(r'обратн.*вылет', recent, re.I) else 'вернуться' if re.search(r'верну|обратн', recent, re.I) else 'вылет'
            text = f'Хочу {subject} позже'
    return text
