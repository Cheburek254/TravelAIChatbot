export function getQuickActions({ options = {}, selected = 'A', viewMode = 'canvas', state = {}, planStatus = 'empty' }) {
  const actions = stageActions({ options, selected, viewMode, state, planStatus });
  if (viewMode === 'itinerary' || viewMode === 'checkout') return actions;
  const controls = [
    ...(!actions.some(a => a.local === 'guests') ? [{ id: 'guests', label: '👥 Взрослые и дети', local: 'guests' }] : []),
    { id: 'origin', label: '🛫 Город вылета', local: 'origin' },
    { id: 'mountains', label: '🏔️ Хочу в горы', actionText: 'Помоги выбрать направление для отдыха в горах. Сначала предложи направления и уточни условия.', actionId: 'inspire_mountains' },
    { id: 'sea', label: '🏖️ Хочу к морю', actionText: 'Помоги выбрать направление для отдыха у моря. Сначала предложи направления и уточни условия.', actionId: 'inspire_sea' },
    { id: 'cheapest', label: '🏷️ Самая дешёвая поездка', actionText: 'Найди самую дешёвую поездку', actionId: 'cheapest' },
  ];
  return [...actions.filter(a => !['budget', 'sea', 'mountains'].includes(a.id)), ...controls];
}

function stageActions({ options, selected, viewMode, state, planStatus }) {
  const keys = Object.keys(options).filter(k => {
    const opt = options[k];
    if (!opt || opt.available === false) return false;
    if (k === 'B' && options.A && opt.hotel?.id && opt.hotel.id === options.A.hotel?.id) return false;
    return true;
  });
  if (state.choosing_alternative && state.alternative_quotes?.length) return [
    ...state.alternative_quotes.map(q => ({ id: `alternative-${q.id}`, label: `📍 ${q.name} • от ${q.minimum_total_rub.toLocaleString('ru-RU')} ₽`,
      actionText: `Выбираю ${q.name}. Собери поездку в пределах моего бюджета.`, actionId: 'choose_destination', actionData: { destination: q.id } })),
    { id: 'dates', label: '📅 Изменить даты', local: 'dates' },
    ...(keys.length ? [{ id: 'plan', label: '← К текущему плану', actionText: 'Покажи план поездки', actionId: 'plan' }] : []),
  ];
  if (keys.length && viewMode === 'itinerary') return [
    { id: 'print', label: '🖨️ Распечатать маршрут', local: 'print' },
    { id: 'plan', label: '🧳 Открыть план', actionText: 'Покажи план поездки', actionId: 'plan' },
    { id: 'new', label: '✨ Новая поездка', local: 'new' },
  ];
  if (keys.length) {
    const other = keys.find(k => k !== selected);
    if (viewMode === 'compare') return [
      ...keys.map(key => ({ id: `select-${key}`, label: `🧳 Выбрать вариант ${key === 'A' ? 'А' : 'Б'}`, actionText: `Выбери вариант ${key}`, actionId: key === 'A' ? 'select_a' : 'select_b' })),
      { id: 'plan', label: '← К плану', actionText: 'Покажи план поездки', actionId: 'plan' },
      { id: 'checkout', label: '✓ К оформлению', actionText: 'Открой оформление выбранного варианта', actionId: 'checkout' },
    ];
    if (viewMode === 'checkout') return [
      { id: 'plan', label: '← К плану', actionText: 'Покажи план поездки', actionId: 'plan' },
      ...(keys.length > 1 ? [{ id: 'compare', label: '⚖️ Сравнить варианты', actionText: 'Сравни варианты', actionId: 'compare' }] : []),
      { id: 'questions', label: '💬 Уточнить условия', fill: 'Хочу уточнить условия выбранного отеля: ' },
    ];
    return [
      ...(keys.length > 1 ? [{ id: 'compare', label: '⚖️ Сравнить варианты', actionText: 'Сравни варианты', actionId: 'compare' }] : []),
      ...(other ? [{ id: 'select', label: `🧳 Выбрать вариант ${other === 'A' ? 'А' : 'Б'}`, actionText: `Выбери вариант ${other}`, actionId: other === 'A' ? 'select_a' : 'select_b' }] : []),
      { id: 'meal', label: state.has_meal_addon ? '🍽️ Убрать доп. питание' : '🍽️ Добавить завтраки и ужины', actionText: state.has_meal_addon ? 'Убери дополнительное питание' : 'Добавь завтраки и ужины, сохрани отели', actionId: state.has_meal_addon ? 'meal_off' : 'meal_on' },
      { id: 'dates', label: '📅 Изменить даты', local: 'dates' },
      { id: 'alternatives', label: '🌍 Другие направления', actionText: 'Предложи другие направления с сохранением моего бюджета', actionId: 'alternatives' },
      { id: 'checkout', label: '✓ К оформлению', actionText: 'Открой оформление выбранного варианта', actionId: 'checkout' },
    ];
  }
  if (planStatus === 'unavailable') return [
    { id: 'budget', label: '💰 Изменить бюджет', fill: 'Новый максимальный бюджет за всю поездку: ' },
    { id: 'dates', label: '📅 Изменить даты', local: 'dates' },
    { id: 'alternatives', label: '🌍 Другие направления', actionText: 'Предложи другие направления с сохранением моего бюджета', actionId: 'alternatives' },
    ...(state.destination ? [{ id: 'rebuild', label: '🔄 Повторить подбор', actionText: 'Пересобери поездку с сохранёнными условиями', actionId: 'rebuild' }] : []),
  ];
  if (state.suggested_destinations?.length && !state.destination) return state.suggested_destinations.slice(0, 3).map(name => ({
    id: `destination-${name}`, label: `📍 ${name}`, actionText: `Выбираю ${name}. Собери поездку в пределах моего бюджета.`, actionId: 'choose_destination', actionData: { destination: name },
  }));
  if (state.destination) return [
    { id: 'dates', label: '📅 Указать даты', local: 'dates' },
    { id: 'guests', label: '👥 Кто едет', local: 'guests' },
    { id: 'budget', label: '💰 Указать бюджет', fill: 'Максимальный бюджет за всю поездку: ' },
    { id: 'build', label: '✨ Собрать поездку', actionText: 'Собери поездку с сохранёнными условиями' },
  ];
  return [
    { id: 'sea', label: '🏖️ Хочу к морю', actionText: 'Помоги выбрать направление для отдыха у моря. Сначала предложи направления и уточни условия.' },
    { id: 'mountains', label: '🏔️ Хочу в горы', actionText: 'Помоги выбрать направление для отдыха в горах. Сначала предложи направления и уточни условия.' },
    { id: 'destination', label: '📍 Уже знаю куда', fill: 'Хочу поехать в ' },
    { id: 'budget', label: '💰 Начать с бюджета', fill: 'Максимальный бюджет за всю поездку: ' },
  ];
}
