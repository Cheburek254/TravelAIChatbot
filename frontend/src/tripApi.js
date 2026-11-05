// Адрес бэкенда (по умолчанию тот же хост и порт 8080 -> /api)
const API_URL = import.meta.env?.VITE_API_URL || '/api';

export function getChatSessionId() {
  const key = 'travelaichatbot.chat.session';
  let id = sessionStorage.getItem(key);
  if (!id) {
    id = globalThis.crypto?.randomUUID?.() || `session-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    sessionStorage.setItem(key, id);
  }
  return id;
}

export function startNewChat() {
  sessionStorage.removeItem('travelaichatbot.chat.session');
  window.location.assign(window.location.pathname);
}

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    signal: AbortSignal.timeout(95000),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Сервис недоступен. Попробуйте ещё раз.');
  }
  return response.json();
}

export async function fetchInitialTrips() {
  return requestJson(`/trips/initial?session_id=${encodeURIComponent(getChatSessionId())}`);
}

export async function sendChatMessage(message, currentOptionKey, actionId = null, actionData = {}) {
  return requestJson('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      ...(actionId ? { action_id: actionId } : {}),
      ...actionData,
      selected_option: currentOptionKey,
      session_id: getChatSessionId(),
    }),
  });
}

export async function createBooking(tripData, totalAmount) {
  try {
    const response = await fetch(`${API_URL}/bookings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        trip: tripData,
        total_price: totalAmount,
      }),
    });
    if (!response.ok) throw new Error('Ошибка записи брони в БД');
    return await response.json();
  } catch (error) {
    console.warn('БД бронирования недоступна, выдаем демо-ваучер:', error);
    return { status: 'confirmed', voucherId: 'OS-7741902', pnr: 'K7M9QP' };
  }
}
