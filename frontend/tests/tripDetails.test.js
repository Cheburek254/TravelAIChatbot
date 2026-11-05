import test from 'node:test';
import assert from 'node:assert/strict';
import { travellersLabel, loyaltyPoints, partyDetails, partyLabel, validPartyDraft } from '../src/tripDetails.js';

test('travellers use the actual guest count and pet presence', () => {
  assert.equal(travellersLabel(1, false), '1 гость');
  assert.equal(travellersLabel(3, false), '3 гостя');
  assert.equal(travellersLabel(5, true), '5 гостей + питомец');
  assert.equal(travellersLabel(2, true), '2 гостя + питомец');
});

test('loyalty uses 1.5 percent, a 150 minimum and consistent half-up rounding', () => {
  assert.equal(loyaltyPoints(0), 150);
  assert.equal(loyaltyPoints(1000), 150);
  assert.equal(loyaltyPoints(100000), 1500);
  assert.equal(loyaltyPoints(10100), 152);
});

test('family labels and restoration preserve adult count and exact child ages', () => {
  const party = partyDetails({}, { travellers: { adults: 2, children_ages: [1, 8], withPet: true } });
  assert.equal(party.passengers, 4);
  assert.equal(partyLabel(party), '2 взрослых + 2 ребёнка (1 год, 8 лет) + питомец');
  assert.equal(partyDetails({ passengers: 3 }).adults, 3);
});

test('guest editor requires ages, adult supervision and at most ten guests', () => {
  assert.ok(validPartyDraft(1, ['0', '6']));
  for (const [adults, ages] of [[0, ['6']], [1, ['', '6']], [1, ['0', '1']], [10, ['6']], [1, ['18']]]) {
    assert.equal(validPartyDraft(adults, ages), false);
  }
});
