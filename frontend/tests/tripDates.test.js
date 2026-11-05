import test from 'node:test';
import assert from 'node:assert/strict';
import { shiftedCheckout } from '../src/tripDates.js';
import { getQuickActions } from '../src/quickActions.js';

test('moving dates keeps the duration across month, year and leap boundaries', () => {
  assert.equal(shiftedCheckout('2027-05-03', 4), '2027-05-07');
  assert.equal(shiftedCheckout('2027-12-31', 4), '2028-01-04');
  assert.equal(shiftedCheckout('2028-02-28', 4), '2028-03-03');
  assert.equal(shiftedCheckout('2027-03-27', 4), '2027-03-31');
});
test('invalid dates cannot produce a submit-ready range', () => {
  assert.equal(shiftedCheckout('', 4), '');
  assert.equal(shiftedCheckout('2027-02-31', 4), '');
});
test('alternatives shortcut uses a server action and affordable choices use ids', () => {
  const unavailable = getQuickActions({ planStatus: 'unavailable', state: { destination: 'Мальдивы' } });
  assert.equal(unavailable.find(a => a.id === 'alternatives').actionId, 'alternatives');
  assert.equal(unavailable.find(a => a.id === 'dates').local, 'dates');
  const choices = getQuickActions({ state: { choosing_alternative: true, alternative_quotes: [{ id: 'sochi', name: 'Сочи', minimum_total_rub: 55460 }] } });
  assert.equal(choices[0].actionId, 'choose_destination');
  assert.deepEqual(choices[0].actionData, { destination: 'sochi' });
});
