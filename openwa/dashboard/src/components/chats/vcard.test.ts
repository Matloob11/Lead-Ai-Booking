// Parsing is where this quietly goes wrong: a card that half-reads shows a name with no number, or
// a number cut in half, and neither looks like a bug from the outside.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseVCards } from './vcard.ts';

const ONE = [
  'BEGIN:VCARD',
  'VERSION:3.0',
  'N:Khaled;Abu;;;',
  'FN:Abu Khaled',
  'TEL;type=CELL;type=VOICE;waid=971501234567:+971 50 123 4567',
  'END:VCARD',
].join('\n');

test('reads the display name and the number', () => {
  assert.deepEqual(parseVCards(ONE), [{ name: 'Abu Khaled', phones: ['+971 50 123 4567'] }]);
});

test('a body that is not a vCard yields nothing, so the caller can fall back to text', () => {
  assert.deepEqual(parseVCards('just a message'), []);
  assert.deepEqual(parseVCards(''), []);
  assert.deepEqual(parseVCards(undefined), []);
});

test('multi_vcard: every contact in the body, not just the first', () => {
  const both = `${ONE}\n${ONE.replace('FN:Abu Khaled', 'FN:Sara N').replace('+971 50 123 4567', '+971 55 999 0000')}`;
  const parsed = parseVCards(both);
  assert.equal(parsed.length, 2);
  assert.equal(parsed[1].name, 'Sara N');
  assert.deepEqual(parsed[1].phones, ['+971 55 999 0000']);
});

test('several numbers on one card, in order, without duplicates', () => {
  const card = [
    'BEGIN:VCARD',
    'FN:Two Lines',
    'TEL;type=CELL:+971 50 111 1111',
    'TEL;type=WORK:+971 4 222 2222',
    'TEL;type=CELL:+971 50 111 1111',
    'END:VCARD',
  ].join('\n');
  assert.deepEqual(parseVCards(card)[0].phones, ['+971 50 111 1111', '+971 4 222 2222']);
});

// vCard folds a long line by breaking it and starting the next one with a space. That line break
// AND the space are both part of the fold, not of the value (RFC 6350 §3.2) — so a number split
// mid-digits rejoins with no gap. Without unfolding it arrives truncated at the break, and a
// truncated phone number is worse than no card at all.
test('unfolds a wrapped line rather than truncating it', () => {
  const folded = 'BEGIN:VCARD\r\nFN:Long\r\nTEL;type=CELL:+971 50 123\r\n 4567\r\nEND:VCARD';
  assert.deepEqual(parseVCards(folded)[0].phones, ['+971 50 1234567']);
});

// Some producers fold with a bare LF. Same rule, and the parser must not leave the continuation
// sitting on its own line where it is read as a property with no colon and dropped.
test('unfolds a bare-LF fold too', () => {
  const folded = 'BEGIN:VCARD\nFN:Long\nTEL:+971 50 123\n 4567\nEND:VCARD';
  assert.deepEqual(parseVCards(folded)[0].phones, ['+971 50 1234567']);
});

test('falls back to N when the card carries no FN, surname last', () => {
  const noFn = 'BEGIN:VCARD\nN:Khaled;Abu;;;\nTEL:+971 50 123 4567\nEND:VCARD';
  assert.equal(parseVCards(noFn)[0].name, 'Abu Khaled');
});

test('unescapes what vCard escaped', () => {
  const escaped = 'BEGIN:VCARD\nFN:Smith\\, John\nTEL:+1 555\nEND:VCARD';
  assert.equal(parseVCards(escaped)[0].name, 'Smith, John');
});

// A card with nothing readable on it must not become an empty bubble.
test('drops a block with neither a name nor a number', () => {
  assert.deepEqual(parseVCards('BEGIN:VCARD\nVERSION:3.0\nEND:VCARD'), []);
});
