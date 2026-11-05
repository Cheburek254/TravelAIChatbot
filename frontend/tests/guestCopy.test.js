import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('guest editor explains child tariffs', () => {
  const source = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8');
  assert.ok(source.includes('10% авиатарифа без места'));
  assert.ok(!source.includes('авиатарфа'));
});
