import assert from 'node:assert/strict';
import { test } from 'node:test';
import { fetchInitialTrips, getChatSessionId, sendChatMessage } from '../src/tripApi.js';

function newTab() {
  const values = new Map();
  globalThis.sessionStorage = {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
  };
}

test('chat sessions differ between tabs and stay stable within one tab', () => {
  newTab();
  const first = getChatSessionId();
  assert.equal(getChatSessionId(), first);
  newTab();
  assert.notEqual(getChatSessionId(), first);
});

test('initial request and chat send the same session and selected option', async () => {
  newTab();
  const calls = [];
  globalThis.fetch = async (...args) => {
    calls.push(args);
    return { ok: true, json: async () => ({ reply: 'Готово' }) };
  };
  await fetchInitialTrips();
  await sendChatMessage('Выбери Б', 'B');
  assert.equal(new URL(calls[0][0], 'http://localhost').searchParams.get('session_id'), getChatSessionId());
  assert.deepEqual(JSON.parse(calls[1][1].body), {
    message: 'Выбери Б', selected_option: 'B', session_id: getChatSessionId(),
  });
});

test('provider errors reach the UI instead of returning a fake chat answer', async () => {
  newTab();
  globalThis.fetch = async () => ({ ok: false, json: async () => ({ detail: 'OpenRouter недоступен' }) });
  await assert.rejects(sendChatMessage('Сочи', 'A'), /OpenRouter недоступен/);
});
