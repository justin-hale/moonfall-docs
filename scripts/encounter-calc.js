#!/usr/bin/env node
// 5e 2024 encounter difficulty calculator.
//
// Usage:
//   node encounter-calc.js --party-level 5 --party-size 4 \
//     --enemies '12hp/14ac/+5/7avg,45hp/16ac/+7/11avg'
//
// Enemy format: HPhp/ACac/+ATK/AVGDAMAGEavg  (comma-separated for multiple)

const args = process.argv.slice(2);

function parseArgs(args) {
  const opts = {};
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--party-level") opts.partyLevel = parseInt(args[++i]);
    else if (args[i] === "--party-size") opts.partySize = parseInt(args[++i]);
    else if (args[i] === "--enemies") opts.enemies = args[++i];
  }
  return opts;
}

function parseEnemy(str) {
  const m = str.match(/(\d+)hp\/(\d+)ac\/\+(\d+)\/(\d+)avg/i);
  if (!m) return null;
  return { hp: +m[1], ac: +m[2], atk: +m[3], avgDmg: +m[4] };
}

// 5e 2024 XP thresholds per character by level (low / medium / hard / deadly)
const XP_THRESHOLDS = {
  1:  [25, 50, 75, 100],
  2:  [50, 100, 150, 200],
  3:  [75, 150, 225, 400],
  4:  [125, 250, 375, 500],
  5:  [250, 500, 750, 1100],
  6:  [300, 600, 900, 1400],
  7:  [350, 750, 1100, 1700],
  8:  [450, 900, 1400, 2100],
  9:  [550, 1100, 1600, 2400],
  10: [600, 1200, 1900, 2800],
  11: [800, 1600, 2400, 3600],
  12: [1000, 2000, 3000, 4500],
  13: [1100, 2200, 3400, 5100],
  14: [1250, 2500, 3800, 5700],
  15: [1400, 2800, 4300, 6400],
  16: [1600, 3200, 4800, 7200],
  17: [2000, 3900, 5900, 8800],
  18: [2100, 4200, 6300, 9500],
  19: [2400, 4900, 7300, 10900],
  20: [2800, 5700, 8500, 12700],
};

// Rough CR-to-XP mapping based on monster HP+offense (simplified heuristic)
function estimateCR(enemy) {
  const defensiveScore = enemy.hp * (enemy.ac / 13);
  const offensiveScore = enemy.avgDmg * ((enemy.atk + 5) / 10);
  const combined = (defensiveScore + offensiveScore) / 2;

  if (combined <= 10) return { cr: "1/8", xp: 25 };
  if (combined <= 20) return { cr: "1/4", xp: 50 };
  if (combined <= 35) return { cr: "1/2", xp: 100 };
  if (combined <= 55) return { cr: "1", xp: 200 };
  if (combined <= 80) return { cr: "2", xp: 450 };
  if (combined <= 110) return { cr: "3", xp: 700 };
  if (combined <= 140) return { cr: "4", xp: 1100 };
  if (combined <= 175) return { cr: "5", xp: 1800 };
  if (combined <= 210) return { cr: "6", xp: 2300 };
  if (combined <= 250) return { cr: "7", xp: 2900 };
  if (combined <= 300) return { cr: "8", xp: 3900 };
  if (combined <= 350) return { cr: "9", xp: 5000 };
  if (combined <= 410) return { cr: "10", xp: 5900 };
  return { cr: "11+", xp: 7200 };
}

// Encounter multiplier based on number of enemies (5e DMG)
function encounterMultiplier(numEnemies) {
  if (numEnemies === 1) return 1;
  if (numEnemies === 2) return 1.5;
  if (numEnemies <= 6) return 2;
  if (numEnemies <= 10) return 2.5;
  if (numEnemies <= 14) return 3;
  return 4;
}

// Estimate rounds to resolve combat
function estimateRounds(enemies, partySize, partyLevel) {
  const totalEnemyHP = enemies.reduce((s, e) => s + e.hp, 0);
  // Rough party DPR estimate: level * 2 per character
  const partyDPR = partySize * partyLevel * 2;
  const roundsToKillEnemies = Math.ceil(totalEnemyHP / Math.max(partyDPR, 1));

  const enemyDPR = enemies.reduce((s, e) => s + e.avgDmg * 0.65, 0); // ~65% hit rate
  const partyHP = partySize * (8 + partyLevel * 5); // rough average
  const roundsToDownParty = Math.ceil(partyHP / Math.max(enemyDPR, 1));

  return { roundsToKillEnemies, roundsToDownParty, partyDPR, enemyDPR: Math.round(enemyDPR) };
}

// Main
const opts = parseArgs(args);

if (!opts.partyLevel || !opts.partySize || !opts.enemies) {
  console.log("Usage: node encounter-calc.js --party-level N --party-size N --enemies 'HPhp/ACac/+ATK/AVGavg,...'");
  console.log("  e.g. node encounter-calc.js --party-level 5 --party-size 4 --enemies '12hp/14ac/+5/7avg,45hp/16ac/+7/11avg'");
  process.exit(1);
}

const enemies = opts.enemies.split(",").map(s => parseEnemy(s.trim())).filter(Boolean);
if (!enemies.length) {
  console.error("Error: Could not parse enemy stats. Format: HPhp/ACac/+ATK/AVGavg");
  process.exit(1);
}

const thresholds = XP_THRESHOLDS[opts.partyLevel];
if (!thresholds) {
  console.error(`Error: No data for party level ${opts.partyLevel} (supports 1-20)`);
  process.exit(1);
}

// Calculate
const enemyData = enemies.map(e => ({ ...e, ...estimateCR(e) }));
const rawXP = enemyData.reduce((s, e) => s + e.xp, 0);
const multiplier = encounterMultiplier(enemies.length);
const adjustedXP = Math.round(rawXP * multiplier);

const budget = {
  easy: thresholds[0] * opts.partySize,
  medium: thresholds[1] * opts.partySize,
  hard: thresholds[2] * opts.partySize,
  deadly: thresholds[3] * opts.partySize,
};

let difficulty;
if (adjustedXP < budget.easy) difficulty = "TRIVIAL";
else if (adjustedXP < budget.medium) difficulty = "EASY";
else if (adjustedXP < budget.hard) difficulty = "MEDIUM";
else if (adjustedXP < budget.deadly) difficulty = "HARD";
else difficulty = "DEADLY";

const rounds = estimateRounds(enemies, opts.partySize, opts.partyLevel);

// Output
console.log(`\n=== Encounter Analysis ===\n`);
console.log(`Party: ${opts.partySize} PCs at level ${opts.partyLevel}`);
console.log(`Enemies: ${enemies.length}`);

enemyData.forEach((e, i) => {
  console.log(`  ${i + 1}. HP ${e.hp} | AC ${e.ac} | +${e.atk} to hit | ${e.avgDmg} avg dmg | est. CR ${e.cr} (${e.xp} XP)`);
});

console.log(`\nRaw XP: ${rawXP} | Multiplier: x${multiplier} (${enemies.length} enemies) | Adjusted XP: ${adjustedXP}`);
console.log(`XP Budget: Easy ${budget.easy} / Medium ${budget.medium} / Hard ${budget.hard} / Deadly ${budget.deadly}`);
console.log(`\nDifficulty: ${difficulty}`);
console.log(`\nAction Economy: ${enemies.length} enemies vs ${opts.partySize} PCs (ratio ${(enemies.length / opts.partySize).toFixed(1)}:1)`);
console.log(`\nEstimated Duration:`);
console.log(`  Party kills enemies in ~${rounds.roundsToKillEnemies} rounds (party DPR ~${rounds.partyDPR})`);
console.log(`  Enemies down party in ~${rounds.roundsToDownParty} rounds (enemy DPR ~${rounds.enemyDPR})`);

if (rounds.roundsToDownParty <= 3) {
  console.log(`\n⚠  WARNING: Enemies can drop the party fast. Consider reducing enemy damage or count.`);
}
if (rounds.roundsToKillEnemies <= 1) {
  console.log(`\n⚠  WARNING: Enemies will die very quickly. Consider adding HP or more enemies.`);
}
if (enemies.length > opts.partySize * 2) {
  console.log(`\n⚠  WARNING: Heavy action economy advantage for enemies. Consider fewer enemies with more HP.`);
}

console.log("");
