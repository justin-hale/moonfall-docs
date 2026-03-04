#!/usr/bin/env node
// Dice roller for DM scene testing.
// Usage: node dice.js 2d6+3     → rolls 2d6+3, shows breakdown
//        node dice.js 1d20 1d8+5 → rolls multiple expressions

const args = process.argv.slice(2);
if (!args.length) {
  console.log("Usage: node dice.js <expression> [expression...]");
  console.log("  e.g. node dice.js 2d6+3  or  node dice.js 1d20 1d8+5");
  process.exit(1);
}

function roll(expr) {
  const match = expr.match(/^(\d+)d(\d+)([+-]\d+)?$/i);
  if (!match) return { expr, error: "invalid format" };

  const count = parseInt(match[1]);
  const sides = parseInt(match[2]);
  const mod = match[3] ? parseInt(match[3]) : 0;
  const rolls = Array.from({ length: count }, () => Math.floor(Math.random() * sides) + 1);
  const sum = rolls.reduce((a, b) => a + b, 0);
  const total = sum + mod;

  return { expr, rolls, mod, total };
}

for (const expr of args) {
  const r = roll(expr.trim());
  if (r.error) {
    console.log(`${r.expr}: ${r.error}`);
  } else {
    const modStr = r.mod ? ` ${r.mod >= 0 ? "+" : ""}${r.mod}` : "";
    console.log(`${r.expr}: [${r.rolls.join(", ")}]${modStr} = ${r.total}`);
  }
}
