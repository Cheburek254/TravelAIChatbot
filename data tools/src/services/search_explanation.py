import re


def failure_details(code, state, message):
    suggestions = {
        'hotels': ['изменить требования к отелю или выбрать другое направление'],
        'flights': ['изменить даты или ограничения времени перелёта', 'выбрать другой город вылета'],
        'transfer_capacity': ['уменьшить состав группы или выбрать направление с более вместительным трансфером'],
        'child_seat': ['выбрать другой трансфер или направление с детским креслом'],
        'pet_transfer': ['выбрать направление с трансфером, допускающим питомца'],
        'early_checkin': ['сохранить стандартный заезд или выбрать более ранний рейс и отель с ранним заездом'],
        'budget': ['сократить поездку или ослабить требования к отелю', 'изменить бюджет только по вашему решению'],
    }.get(code, ['уточнить даты, состав группы или требования к отелю'])
    return {'code': code, 'reason': message, 'suggestions': suggestions,
            'budget_rub': state.get('budget_rub'), 'passengers': state.get('passengers')}


def no_combination_reason(transfers, state):
    count = state['passengers']
    capacity = [t for t in transfers if int(t.get('capacity_passengers', count)) >= count]
    if not capacity:
        largest = max((int(t.get('capacity_passengers', 0)) for t in transfers), default=0)
        return 'transfer_capacity', f'Не хватает мест в трансфере: в поездке {count} гостей, максимальная вместимость доступного трансфера — {largest}. Повышение бюджета само по себе не добавляет мест.'
    if any(a < 7 for a in state.get('children_ages', [])):
        capacity = [t for t in capacity if t.get('child_seat_available')]
        if not capacity:
            return 'child_seat', 'Нет подходящего трансфера с детским креслом для ребёнка младше 7 лет.'
    if state.get('pet_friendly') and not any(t.get('pet_friendly') is not False for t in capacity):
        return 'pet_transfer', 'Нет трансфера, который одновременно вмещает всю группу и допускает питомца.'
    if state.get('include_early_checkin'):
        return 'early_checkin', 'Не найдено сочетание раннего прибытия, трансфера и отеля с доступным ранним заездом.'
    return 'criteria', 'Нет сочетания отеля, рейса и трансфера, одновременно подходящего под сохранённые условия.'


def latest_failure(session):
    for item in reversed(session['messages']):
        if item.get('role') == 'assistant' and 'search_failure' in item:
            return item.get('search_failure')
    return None


def failure_followup(session, message):
    failure = latest_failure(session)
    if failure and re.search(r'почему|что.{0,25}(?:измен|помен|меша)|како\w*.{0,25}(?:услов|вводн|измен)|в\s+каком.{0,25}(?:направлен|измен)', message, re.I):
        return 'Причина: ' + failure['reason'] + '\n\nМожно ' + '; '.join(failure['suggestions']) + '. Без вашего выбора условия не меняю.'
    return None
