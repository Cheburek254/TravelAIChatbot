import math
import re
from typing import List, Dict, Any, Tuple

SYNONYMS_AND_ASSOCIATIONS = {
    "тепло": ["жарко", "солнце", "пляж", "море", "персидский", "таиланд", "дубай", "тропики", "лето"],
    "ноябрь": ["осень", "бархатный", "тепло в ноябре", "зима в тепле", "пляж в ноябре"],
    "шале": ["домик", "коттедж", "деревянный", "камин", "горы", "альпийский", "кедр", "сруб"],
    "камин": ["дрова", "уют", "огонь", "шале", "романтика"],
    "горы": ["лыжи", "сноуборд", "подъемник", "красная поляна", "шерегеш", "алтай", "высота"],
    "море": ["пляж", "песок", "лазурный", "первая линия", "купание", "волны", "пальмы", "океан"],
    "ребенок": ["дети", "детская кроватка", "семейный", "аквапарк", "детский клуб", "анимация"],
    "собака": ["питомец", "животные", "пет-френдли", "pet-friendly", "пес", "лапы"],
    "романтика": ["медовый месяц", "для двоих", "бутик-отель", "вид", "босфор", "закат", "ужин"],
    "недорого": ["бюджет", "дешево", "эконом", "доступно", "скидки"],
    "лыжи": ["сноуборд", "пухляк", "трассы", "катание", "шерегеш", "красная поляна"]
}

def tokenize(text: str) -> List[str]:
    """Токенизация с удалением русских окончаний."""
    if not text:
        return []
    words = re.findall(r'[a-zA-Zа-яА-ЯёЁ0-9]+', text.lower())
    cleaned = []
    for w in words:
        if len(w) <= 2 and w not in ["ук", "жк", "ai", "bb", "hb", "ro"]:
            continue
        for suffix in ["ными", "ного", "ному", "ыми", "ого", "ему", "ная", "ное", "ные", "ный", "ях", "ов", "ев", "ам", "ем", "ом", "ах", "ий", "ый", "ой", "ая", "яя", "ое", "ее", "ые", "ие", "ам", "ям", "а", "я", "о", "е", "ы", "и"]:
            if len(w) > len(suffix) + 3 and w.endswith(suffix):
                w = w[:-len(suffix)]
                break
        cleaned.append(w)
    return cleaned

def expand_tokens(tokens: List[str]) -> List[str]:
    """Обогащение токенов синонимами для семантического поиска."""
    expanded = list(tokens)
    for t in tokens:
        for key, syns in SYNONYMS_AND_ASSOCIATIONS.items():
            if key.startswith(t) or t.startswith(key):
                for syn in syns:
                    expanded.extend(tokenize(syn))
    return expanded

class SemanticMatcher:
    """Косинусное сходство частот токенов с расширением синонимов."""

    @staticmethod
    def compute_similarity(query: str, document_text: str, tags: List[str] = None) -> float:
        if not query or not document_text:
            return 0.0

        query_tokens = tokenize(query)
        expanded_query = expand_tokens(query_tokens)

        doc_tokens = tokenize(document_text)
        if tags:
            for tag in tags:
                doc_tokens.extend(tokenize(tag) * 2) # Удваиваем вес явных тегов

        if not query_tokens or not doc_tokens:
            return 0.0

        q_counts: Dict[str, float] = {}
        for t in expanded_query:
            q_counts[t] = q_counts.get(t, 0.0) + 1.0

        doc_counts: Dict[str, float] = {}
        for t in doc_tokens:
            doc_counts[t] = doc_counts.get(t, 0.0) + 1.0

        dot_product = 0.0
        for token, count in q_counts.items():
            if token in doc_counts:
                # Бонус за точное совпадение исходного токена (а не синонима)
                weight = 1.5 if token in query_tokens else 1.0
                dot_product += count * doc_counts[token] * weight

        norm_q = math.sqrt(sum(c ** 2 for c in q_counts.values()))
        norm_doc = math.sqrt(sum(c ** 2 for c in doc_counts.values()))

        if norm_q == 0 or norm_doc == 0:
            return 0.0

        similarity = dot_product / (norm_q * norm_doc)
        return min(round(similarity, 3), 1.0)
