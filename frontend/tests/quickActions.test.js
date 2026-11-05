import test from 'node:test';
import assert from 'node:assert/strict';
import { getQuickActions } from '../src/quickActions.js';

test('new chat suggests inspiration and inputs, never old plan actions', () => {
  const actions = getQuickActions({});
  assert.ok(actions.some(a => a.id === 'sea'));
  assert.ok(actions.some(a => a.fill));
  assert.ok(!actions.some(a => ['compare', 'checkout', 'select_a', 'select_b'].includes(a.actionId)));
  assert.ok(actions.some(a => a.actionId === 'cheapest'));
  assert.ok(!actions.some(a => a.id === 'budget' || a.local === 'budget'));
});
test('destination choices come from current search results', () => {
  const actions = getQuickActions({ state: { suggested_destinations: ['Бали', 'Дагестан'] } });
  assert.equal(actions.filter(a => a.id.startsWith('destination-')).length, 2);
  assert.ok(actions[0].actionText.includes('Бали'));
  assert.equal(actions[0].actionId, 'choose_destination');
  assert.deepEqual(actions[0].actionData, { destination: 'Бали' });
  assert.ok(!actions.some(a => a.id === 'destination'));
});

test('party and departure city editors are available before and after building a trip', () => {
  for (const config of [{}, { state: { destination: 'Сочи' } }, { options: { A: {} } }]) {
    const actions = getQuickActions(config);
    assert.equal(actions.filter(a => a.local === 'guests').length, 1);
    assert.equal(actions.filter(a => a.local === 'origin').length, 1);
  }
});

test('budget stays in chat while cheapest control remains available', () => {
  for (const config of [{}, { planStatus: 'unavailable' }, { options: { A: {} } },
    { state: { choosing_alternative: true, alternative_quotes: [{ id: 'sochi', name: 'Сочи', minimum_total_rub: 55460 }] } }]) {
    const actions = getQuickActions(config);
    assert.equal(actions.filter(a => a.id === 'budget' || a.local === 'budget').length, 0);
    assert.equal(actions.filter(a => a.actionId === 'cheapest').length, 1);
  }
});

test('holiday inspiration is a server action at every search stage, including an old destination', () => {
  for (const config of [{}, { state: { destination: 'Дубай' }, planStatus: 'unavailable' }, { options: { A: {} } }]) {
    const actions = getQuickActions(config);
    assert.equal(actions.filter(a => a.actionId === 'inspire_mountains').length, 1);
    assert.equal(actions.filter(a => a.actionId === 'inspire_sea').length, 1);
    assert.equal(actions.find(a => a.id === 'mountains').fill, undefined);
  }
});
test('ready plan selects the other available option and toggles meals', () => {
  const actions = getQuickActions({ options: { A: {}, B: {} }, selected: 'B', state: { has_meal_addon: true } });
  assert.ok(actions.some(a => a.actionId === 'select_a'));
  assert.ok(actions.some(a => a.actionId === 'meal_off'));
});
test('unavailable or duplicate-hotel option is never offered for selection or comparison', () => {
  const actions = getQuickActions({ options: { A: {}, B: { available: false } } });
  assert.ok(!actions.some(a => a.actionId === 'select_b' || a.actionId === 'compare'));
  const dupActions = getQuickActions({ options: { A: { hotel: { id: 'h1' } }, B: { hotel: { id: 'h1' } } } });
  assert.ok(!dupActions.some(a => a.actionId === 'select_b' || a.actionId === 'compare'));
});
test('unavailable search offers changed conditions instead of payment', () => {
  const actions = getQuickActions({ planStatus: 'unavailable', state: { destination: 'Бали' } });
  assert.ok(!actions.some(a => a.id === 'budget'));
  assert.ok(actions.some(a => a.actionId === 'rebuild'));
  assert.ok(!actions.some(a => a.actionId === 'checkout'));
});
test('checkout and booked stages expose relevant shortcuts', () => {
  const options = { A: {}, B: {} };
  assert.ok(getQuickActions({ options, viewMode: 'checkout' }).some(a => a.actionId === 'plan'));
  const booked = getQuickActions({ options, viewMode: 'itinerary' });
  assert.ok(booked.some(a => a.local === 'print'));
  assert.ok(booked.some(a => a.local === 'new'));
  const comparing = getQuickActions({ options, viewMode: 'compare' });
  assert.ok(comparing.some(a => a.actionId === 'select_a'));
  assert.ok(comparing.some(a => a.actionId === 'select_b'));
  assert.ok(!comparing.some(a => a.actionId === 'compare'));
});
