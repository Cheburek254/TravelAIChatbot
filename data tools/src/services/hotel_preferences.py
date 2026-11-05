"""Explicit requests to replace the displayed hotels, rather than repeat them."""
import re


def is_hotel_change_request(message):
    text = message.lower().replace('ё', 'е')
    if re.match(r'\s*(?:почему|зачем|расскажи|объясни)\b', text):
        return False
    return bool(re.search(r'(?:покаж\w*|вывед\w*|подбер\w*|найд\w*|хочу|давай\w*|смен\w*|помен\w*|замен\w*).{0,35}(?:друг\w*|нов\w*|альтернатив\w*).{0,15}(?:отел\w*|гостиниц\w*)|(?:смен\w*|помен\w*|замен\w*)\s+(?:отел\w*|гостиниц\w*)', text))
