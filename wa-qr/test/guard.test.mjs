/**
 * The one check that must not be got wrong.
 *
 * Linking a Business Platform number by QR risks a permanent ban on a verified
 * number carrying the company's approved templates. guardNumber is the only
 * thing standing in front of that, so it is tested rather than trusted.
 */

import assert from "node:assert/strict";
import { config, guardNumber } from "../src/config.js";

let passed = 0;
const check = (name, fn) => {
  try {
    fn();
    passed++;
    console.log(`  ok    ${name}`);
  } catch (error) {
    console.log(`  FAIL  ${name}\n        ${error.message}`);
    process.exitCode = 1;
  }
};

check("the blocked list is actually loaded", () => {
  assert.ok(config.blockedNumbers.size >= 20,
    `only ${config.blockedNumbers.size} numbers blocked — the .env is not loaded`);
});

check("a Business Platform number is refused", () => {
  const blocked = [...config.blockedNumbers][0];
  assert.throws(() => guardNumber(blocked), /Business Platform/);
});

check("every blocked number is refused, not just the first", () => {
  for (const number of config.blockedNumbers) {
    assert.throws(() => guardNumber(number), /Business Platform/, `${number} slipped through`);
  }
});

check("formatting does not get a blocked number past it", () => {
  const blocked = [...config.blockedNumbers][0];
  const spaced = blocked.replace(/^(\d{3})(\d{2})/, "+$1 $2 ");
  assert.throws(() => guardNumber(spaced), /Business Platform/,
    `"${spaced}" was allowed — the guard is comparing raw strings`);
});

check("a number kept for this purpose passes", () => {
  assert.equal(guardNumber("923001234567"), "923001234567");
});

check("an empty number is not treated as blocked", () => {
  assert.equal(guardNumber(""), "");
});

console.log(`\n  ${passed} checks passed`);
