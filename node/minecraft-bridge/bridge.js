/*
 * NovaAI Minecraft bridge.
 *
 * A Mineflayer bot exposed over a local HTTP API. NovaAI's Python game agent
 * (the LLM "brain") calls:
 *   GET  /health   -> { ok, connected }
 *   GET  /observe  -> structured world state (incl. players + hostiles)
 *   POST /act      -> { verb, args } executes a high-level action
 *
 * The brain stays in Python; this process only translates high-level verbs
 * into Mineflayer calls (follow owner, fetch items from chests, defend, etc.).
 *
 * Config comes from CLI args, falling back to environment variables, so it can
 * run either way (offline/LAN or an online Microsoft account).
 */
'use strict';

const http = require('http');
const path = require('path');
const mineflayer = require('mineflayer');
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder');
const Vec3 = require('vec3');

// ── arg / env parsing ────────────────────────────────────────────────────────
function getArg(name, envName, fallback) {
  const idx = process.argv.indexOf('--' + name);
  if (idx !== -1 && idx + 1 < process.argv.length) return process.argv[idx + 1];
  if (envName && process.env[envName] !== undefined && process.env[envName] !== '') {
    return process.env[envName];
  }
  return fallback;
}

const HOST = getArg('host', 'MC_HOST', '127.0.0.1');
const PORT = parseInt(getArg('port', 'MC_PORT', '25565'), 10);
const USERNAME = getArg('username', 'MC_USERNAME', 'NovaAI');
const BRIDGE_PORT = parseInt(getArg('bridge-port', 'MC_BRIDGE_PORT', '8767'), 10);
const AUTH = getArg('auth', 'MC_AUTH', 'offline'); // 'offline' | 'microsoft'
const OWNER = String(getArg('owner', 'MC_OWNER_USERNAME', '')).toLowerCase();
const PROFILES_FOLDER = getArg('profiles-folder', 'MC_PROFILES_FOLDER',
  path.join(__dirname, '.minecraft-auth'));
const VERSION = getArg('version', 'MC_VERSION', false); // false = auto-detect
const VIEWER_PORT = parseInt(getArg('viewer-port', 'MC_VIEWER_PORT', '8768'), 10);
const VIEWER_FIRST_PERSON =
  String(getArg('viewer-first-person', 'MC_VIEWER_FIRST_PERSON', 'true')).toLowerCase() !== 'false';

const HOSTILES = new Set([
  'zombie', 'husk', 'drowned', 'zombie_villager', 'skeleton', 'stray', 'wither_skeleton',
  'spider', 'cave_spider', 'creeper', 'witch', 'slime', 'magma_cube', 'blaze', 'ghast',
  'enderman', 'endermite', 'silverfish', 'phantom', 'pillager', 'vindicator', 'evoker',
  'ravager', 'vex', 'guardian', 'elder_guardian', 'shulker', 'hoglin', 'zoglin', 'piglin_brute',
  'warden', 'breeze', 'bogged',
]);

let bot = null;
let connected = false;
let lastError = '';
let reconnectTimer = null;
let reconnectDelay = 5000;   // grows with backoff, resets on successful spawn
let autoEating = false;
let autoEatTimer = null;
const AUTO_EAT_THRESHOLD = 17;   // eat to top up hunger so health regenerates

function startAutoEat() {
  if (autoEatTimer) return;
  // Survival: automatically eat when hunger drops, so the bot heals (natural
  // regen needs a near-full hunger bar) and doesn't starve — like a real player.
  autoEatTimer = setInterval(async () => {
    if (!bot || !connected || autoEating) return;
    if (typeof bot.food !== 'number' || bot.food > AUTO_EAT_THRESHOLD) return;
    const food = bot.inventory.items().find((i) => isFood(i.name));
    if (!food) return;
    autoEating = true;
    try {
      await bot.equip(food, 'hand');
      await bot.consume();
    } catch (e) { /* full / interrupted */ } finally {
      autoEating = false;
    }
  }, 4000);
}

function log(msg) {
  // Printed to stdout; the Python driver forwards these lines to the UI.
  // eslint-disable-next-line no-console
  console.log('[novaai-bridge] ' + msg);
}

let viewerStarted = false;
function startViewer() {
  // Browser-based 3D view of the bot's surroundings / POV — lets you watch what
  // it's doing without opening the Minecraft client. Optional dependency.
  if (!VIEWER_PORT || viewerStarted) return;
  let mineflayerViewer;
  try {
    ({ mineflayer: mineflayerViewer } = require('prismarine-viewer'));
  } catch (e) {
    log('Live view unavailable: prismarine-viewer not installed. '
      + 'Run `npm install` in node/minecraft-bridge to enable it.');
    return;
  }
  try {
    mineflayerViewer(bot, { port: VIEWER_PORT, firstPerson: VIEWER_FIRST_PERSON });
    viewerStarted = true;
    log(`live view ready at http://127.0.0.1:${VIEWER_PORT} `
      + `(${VIEWER_FIRST_PERSON ? 'first' : 'third'}-person)`);
  } catch (e) {
    log('live view failed to start: ' + ((e && e.message) || e));
  }
}

function scheduleReconnect(reason) {
  if (reconnectTimer) return;            // already scheduled
  const secs = Math.round(reconnectDelay / 1000);
  log(`disconnected (${reason}); reconnecting in ${secs}s`);
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    try {
      createBot();
    } catch (e) {
      log('reconnect failed: ' + ((e && e.message) || e));
      scheduleReconnect('retry');
    }
  }, reconnectDelay);
  reconnectDelay = Math.min(60000, Math.floor(reconnectDelay * 1.5));
}

function createBot() {
  const opts = {
    host: HOST,
    port: PORT,
    username: USERNAME,
    auth: AUTH === 'microsoft' ? 'microsoft' : 'offline',
  };
  if (AUTH === 'microsoft') {
    opts.profilesFolder = PROFILES_FOLDER;
    // Surface the device-code login prompt clearly (token is cached afterwards).
    opts.onMsaCode = (data) => {
      log('MICROSOFT LOGIN REQUIRED: go to ' + (data.verification_uri || 'https://microsoft.com/link') +
          ' and enter code ' + (data.user_code || '(see console)'));
      if (data.message) log(data.message);
    };
  }
  if (VERSION) opts.version = String(VERSION);

  // Drop the previous (dead) bot's listeners before creating a new one.
  if (bot) {
    try { bot.removeAllListeners(); } catch (e) { /* ignore */ }
  }

  bot = mineflayer.createBot(opts);
  bot.loadPlugin(pathfinder);
  try {
    bot.loadPlugin(require('mineflayer-tool').plugin);  // auto best-tool for mining
  } catch (e) { /* optional dep */ }

  bot.once('spawn', () => {
    connected = true;
    reconnectDelay = 5000;   // reset backoff after a good connection
    try {
      bot.pathfinder.setMovements(new Movements(bot));
    } catch (e) { /* ignore */ }
    startViewer();
    startAutoEat();
    log(`spawned as ${bot.username}${OWNER ? `, owner = ${OWNER}` : ''}`);
  });

  // Auto-reconnect on disconnect/kick so a server restart or blip recovers.
  bot.on('end', (reason) => {
    connected = false;
    scheduleReconnect(reason || 'end');
  });
  bot.on('kicked', (reason) => {
    lastError = 'kicked: ' + reason;
    connected = false;
    log('kicked: ' + reason);
    // 'end' usually follows and triggers the reconnect; schedule as a fallback.
    scheduleReconnect('kicked');
  });
  bot.on('error', (err) => {
    lastError = String((err && err.message) || err);
    log('error: ' + lastError);
    if (!connected) scheduleReconnect('error');   // e.g. connection refused
  });
}

// ── helpers ──────────────────────────────────────────────────────────────────
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function playerEntity(name) {
  const want = String(name || OWNER || '').toLowerCase();
  if (!want) return null;
  for (const uname in bot.players) {
    if (uname.toLowerCase() === want) {
      const p = bot.players[uname];
      if (p && p.entity) return p.entity;
    }
  }
  return null;
}

function isHostile(entity) {
  return entity && entity.name && HOSTILES.has(String(entity.name).toLowerCase());
}

function nearestVillager(maxDist) {
  maxDist = maxDist || 16;
  let best = null;
  let bestD = maxDist;
  for (const id in bot.entities) {
    const e = bot.entities[id];
    if (!e || !e.position) continue;
    if (String(e.name || '').toLowerCase() === 'villager') {
      const d = e.position.distanceTo(bot.entity.position);
      if (d < bestD) { bestD = d; best = e; }
    }
  }
  return best;
}

function nearestHostile(maxDist) {
  maxDist = maxDist || 12;
  let best = null;
  let bestD = maxDist;
  for (const id in bot.entities) {
    const e = bot.entities[id];
    if (!isHostile(e) || !e.position) continue;
    const d = e.position.distanceTo(bot.entity.position);
    if (d < bestD) { bestD = d; best = e; }
  }
  return best;
}

function armorSlotForItem(name) {
  name = String(name).toLowerCase();
  if (name.includes('helmet') || name.includes('cap') || name.includes('turtle')) return 'head';
  if (name.includes('chestplate') || name.includes('elytra')) return 'torso';
  if (name.includes('leggings')) return 'legs';
  if (name.includes('boots')) return 'feet';
  return null;
}

function armorTier(name) {
  name = String(name).toLowerCase();
  const order = ['leather', 'gold', 'golden', 'chainmail', 'iron', 'diamond', 'netherite'];
  for (let i = order.length - 1; i >= 0; i--) if (name.includes(order[i])) return i;
  return -1;
}

const FOODS = ['cooked', 'steak', 'bread', 'apple', 'carrot', 'baked_potato',
  'melon_slice', 'cookie', 'pumpkin_pie', 'beetroot_soup', 'mushroom_stew',
  'rabbit_stew', 'golden_apple', 'sweet_berries', 'glow_berries', 'honey_bottle',
  'dried_kelp', 'chicken', 'porkchop', 'beef', 'mutton', 'cod', 'salmon', 'potato'];
function isFood(name) {
  name = String(name).toLowerCase();
  return FOODS.some((f) => name.includes(f));
}

function resolveItem(name) {
  const want = String(name || '').toLowerCase();
  if (!want) return null;
  if (bot.registry.itemsByName[want]) return bot.registry.itemsByName[want];
  for (const key in bot.registry.itemsByName) {
    if (key.includes(want)) return bot.registry.itemsByName[key];
  }
  return null;
}

function entityByName(name) {
  const want = String(name || '').toLowerCase();
  if (!want) return null;
  const p = playerEntity(want);
  if (p) return p;
  let best = null;
  let bestD = 64;
  for (const id in bot.entities) {
    const e = bot.entities[id];
    if (!e || e === bot.entity || !e.position) continue;
    const nm = String(e.username || e.name || '').toLowerCase();
    if (nm && (nm === want || nm.includes(want))) {
      const d = e.position.distanceTo(bot.entity.position);
      if (d < bestD) { bestD = d; best = e; }
    }
  }
  return best;
}

// "Legit" exposure check: a block is exposed if at least one of its 6 faces
// touches air/water (i.e. you could actually see it while caving — not X-ray).
function isExposed(block) {
  if (!block || !block.position) return false;
  const offsets = [[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]];
  for (const [dx, dy, dz] of offsets) {
    const n = bot.blockAt(block.position.offset(dx, dy, dz));
    if (!n || n.name === 'air' || n.name === 'cave_air' || n.name === 'void_air'
        || n.name === 'water' || n.boundingBox === 'empty') {
      return true;
    }
  }
  return false;
}

const ORE_KEYWORDS = ['coal_ore', 'copper_ore', 'iron_ore', 'gold_ore', 'redstone_ore',
  'lapis_ore', 'diamond_ore', 'emerald_ore', 'nether_gold_ore', 'nether_quartz_ore',
  'ancient_debris'];

// ── farming data ─────────────────────────────────────────────────────────────
const CROP_MATURE_AGE = { wheat: 7, carrots: 7, potatoes: 7, beetroots: 3, nether_wart: 3 };
const CROP_TO_SEED = {
  wheat: 'wheat_seeds', carrots: 'carrot', potatoes: 'potato',
  beetroots: 'beetroot_seeds', nether_wart: 'nether_wart',
};

function idsForNames(names) {
  const ids = [];
  for (const n of names) {
    const b = bot.registry.blocksByName[n];
    if (b) ids.push(b.id);
  }
  return ids;
}

function cropAge(block) {
  try {
    if (block && block.getProperties) {
      const a = block.getProperties().age;
      if (a !== undefined) return parseInt(a, 10);
    }
  } catch (e) { /* ignore */ }
  return (block && typeof block.metadata === 'number') ? block.metadata : NaN;
}

function isMatureCrop(block) {
  if (!block) return false;
  const max = CROP_MATURE_AGE[block.name];
  if (max === undefined) return false;
  const age = cropAge(block);
  return !isNaN(age) && age >= max;
}

function findInventory(...needles) {
  return bot.inventory.items().find((i) => needles.some((n) => i.name.includes(n)));
}

// Breeding foods by animal.
const ANIMAL_FOOD = {
  cow: 'wheat', sheep: 'wheat', mooshroom: 'wheat', goat: 'wheat',
  pig: 'carrot', chicken: 'wheat_seeds', rabbit: 'carrot',
  wolf: 'beef', cat: 'cod', ocelot: 'cod', horse: 'golden_carrot',
  donkey: 'golden_carrot', llama: 'hay_block', fox: 'sweet_berries',
  panda: 'bamboo', turtle: 'seagrass', bee: 'flower', frog: 'slime_ball',
};

const FOOD_ANIMALS = ['cow', 'pig', 'chicken', 'sheep', 'rabbit', 'cod', 'salmon'];

// Tool tiers best -> worst (lower index = better).
const TOOL_TIERS = ['netherite', 'diamond', 'iron', 'golden', 'stone', 'wooden'];
function toolTier(name) {
  name = String(name).toLowerCase();
  return TOOL_TIERS.find((t) => name.startsWith(t + '_')) || '';
}

function chestBlockIds() {
  const ids = [];
  for (const n of ['chest', 'trapped_chest', 'barrel', 'ender_chest']) {
    if (bot.registry.blocksByName[n]) ids.push(bot.registry.blocksByName[n].id);
  }
  return ids;
}

// ── observation ──────────────────────────────────────────────────────────────
function observe() {
  if (!bot || !connected || !bot.entity) return { connected: false };
  const pos = bot.entity.position;
  const inventory = bot.inventory.items().map((i) => ({ name: i.name, count: i.count }));

  const nearbyBlocks = [];
  try {
    const seen = new Set();
    const base = pos.floored();
    const offsets = [[1,0,0],[-1,0,0],[0,0,1],[0,0,-1],[0,1,0],[0,-1,0],[2,0,0],[-2,0,0],[0,0,2],[0,0,-2]];
    for (const [dx,dy,dz] of offsets) {
      const block = bot.blockAt(base.offset(dx, dy, dz));
      if (block && block.name && block.name !== 'air' && !seen.has(block.name)) {
        seen.add(block.name); nearbyBlocks.push(block.name);
      }
    }
  } catch (e) { /* ignore */ }

  const players = [];
  const hostiles = [];
  try {
    for (const id in bot.entities) {
      const e = bot.entities[id];
      if (e === bot.entity || !e.position) continue;
      const d = e.position.distanceTo(pos);
      if (e.type === 'player' && d < 48) {
        players.push({ name: e.username || e.name, distance: Math.round(d) });
      } else if (isHostile(e) && d < 24) {
        hostiles.push({ name: e.name, distance: Math.round(d) });
      }
    }
  } catch (e) { /* ignore */ }
  hostiles.sort((a, b) => a.distance - b.distance);

  const ownerEnt = playerEntity(OWNER);
  return {
    connected: true,
    owner: OWNER || null,
    ownerVisible: !!ownerEnt,
    ownerDistance: ownerEnt ? Math.round(ownerEnt.position.distanceTo(pos)) : null,
    health: bot.health,
    food: bot.food,
    timeOfDay: bot.time ? bot.time.timeOfDay : undefined,
    position: { x: Math.round(pos.x), y: Math.round(pos.y), z: Math.round(pos.z) },
    inventory,
    nearbyBlocks,
    players,
    nearbyHostiles: hostiles,
  };
}

// ── actions ────────────────────────────────────────────────────────────────
function countInInventory(name) {
  return bot.inventory.items()
    .filter((i) => i.name.includes(String(name).toLowerCase()))
    .reduce((s, i) => s + i.count, 0);
}

async function findInChests(name, withdrawCount) {
  const ids = chestBlockIds();
  if (!ids.length) return { ok: false, message: 'no chest types in this version' };
  const positions = bot.findBlocks({ matching: ids, maxDistance: 32, count: 16 });
  if (!positions.length) return { ok: false, message: 'no chests nearby' };

  let total = 0;
  let withdrawn = 0;
  const found = [];
  for (const p of positions) {
    try {
      await bot.pathfinder.goto(new goals.GoalNear(p.x, p.y, p.z, 1));
      const block = bot.blockAt(p);
      if (!block) continue;
      const container = await bot.openContainer(block);
      const matches = container.containerItems().filter((i) => i.name.includes(String(name).toLowerCase()));
      const c = matches.reduce((s, i) => s + i.count, 0);
      if (c > 0) {
        found.push({ x: p.x, y: p.y, z: p.z, count: c });
        total += c;
        if (withdrawCount !== null && withdrawn < withdrawCount) {
          for (const it of matches) {
            const take = Math.min(it.count, withdrawCount - withdrawn);
            if (take > 0) {
              try { await container.withdraw(it.type, null, take); withdrawn += take; } catch (e) { /* full? */ }
            }
          }
        }
      }
      container.close();
    } catch (e) { /* skip this chest */ }
  }
  return {
    ok: true,
    total,
    withdrawn,
    chests: found.length,
    message: `found ${total} ${name} across ${found.length} chest(s)` +
             (withdrawCount !== null ? `, took ${withdrawn}` : ''),
  };
}

async function comeTo(playerName) {
  const ent = playerEntity(playerName);
  if (!ent) return { ok: false, message: `can't see ${playerName || OWNER || 'that player'}` };
  await bot.pathfinder.goto(new goals.GoalNear(ent.position.x, ent.position.y, ent.position.z, 2));
  return { ok: true, message: `reached ${playerName || OWNER}` };
}

async function ensureCraftingTable() {
  // Return a usable crafting table near the bot, placing/crafting one if needed.
  let table = bot.findBlock({ matching: idsForNames(['crafting_table']), maxDistance: 6 });
  if (table) return table;
  let tableItem = findInventory('crafting_table');
  if (!tableItem) {
    // Try to craft a crafting table (2x2, no table needed) from planks.
    const ct = bot.registry.itemsByName.crafting_table;
    if (ct) {
      const recs = bot.recipesFor(ct.id, null, 1, null);
      if (recs.length) { try { await bot.craft(recs[0], 1, null); } catch (e) { /* ignore */ } }
    }
    tableItem = findInventory('crafting_table');
  }
  if (!tableItem) return null;
  // Place it on an adjacent floor tile.
  const dirs = [[1, 0, 0], [-1, 0, 0], [0, 0, 1], [0, 0, -1]];
  for (const [dx, dy, dz] of dirs) {
    const spot = bot.entity.position.offset(dx, 0, dz);
    const at = bot.blockAt(spot);
    const below = bot.blockAt(spot.offset(0, -1, 0));
    if (at && at.name === 'air' && below && below.boundingBox === 'block') {
      try { await bot.equip(tableItem, 'hand'); await bot.placeBlock(below, new Vec3(0, 1, 0)); break; }
      catch (e) { /* try next */ }
    }
  }
  return bot.findBlock({ matching: idsForNames(['crafting_table']), maxDistance: 4 });
}

async function smeltInput(inputName, fuelName, count) {
  const fb = bot.findBlock({ matching: idsForNames(['furnace', 'blast_furnace', 'smoker']), maxDistance: 16 });
  if (!fb) return { ok: false, message: 'no furnace nearby (craft & place one first)' };
  await bot.pathfinder.goto(new goals.GoalNear(fb.position.x, fb.position.y, fb.position.z, 2));
  const input = findInventory(inputName);
  if (!input) return { ok: false, message: `no ${inputName} to smelt/cook` };
  const furnace = await bot.openFurnace(bot.blockAt(fb.position));
  try {
    try { if (furnace.outputItem()) await furnace.takeOutput(); } catch (e) { /* ignore */ }
    const c = count !== undefined ? Math.min(Number(count), input.count) : input.count;
    await furnace.putInput(input.type, null, c);
    const fuel = fuelName ? findInventory(fuelName) : findInventory('coal', 'charcoal', 'coal_block');
    let fueled = false;
    if (fuel) {
      await furnace.putFuel(fuel.type, null, Math.min(Math.max(1, Math.ceil(c / 8)), fuel.count));
      fueled = true;
    }
    furnace.close();
    return { ok: true, message: `${input.name} x${c} in the furnace` + (fueled ? '' : ' — NO FUEL, add coal!') + ' (collect with take_smelted)' };
  } catch (e) {
    try { furnace.close(); } catch (_) { /* ignore */ }
    return { ok: false, message: `smelt failed: ${(e && e.message) || e}` };
  }
}

// Place one block at (x,y,z) against any solid neighbour. itemKey = item name.
async function placeBlockAt(x, y, z, itemKey) {
  const target = new Vec3(x, y, z);
  const at = bot.blockAt(target);
  if (at && at.name !== 'air' && at.boundingBox === 'block') return true;
  if (!findInventory(itemKey)) return false;
  const refs = [[0, -1, 0], [0, 0, 1], [0, 0, -1], [1, 0, 0], [-1, 0, 0], [0, 1, 0]];
  for (const [dx, dy, dz] of refs) {
    const ref = bot.blockAt(target.offset(dx, dy, dz));
    if (ref && ref.name !== 'air' && ref.boundingBox === 'block') {
      try {
        await bot.pathfinder.goto(new goals.GoalNear(x, y, z, 3));
        const item = findInventory(itemKey);
        if (!item) return false;
        await bot.equip(item, 'hand');
        await bot.placeBlock(ref, new Vec3(-dx, -dy, -dz));
        return true;
      } catch (e) { /* try next reference */ }
    }
  }
  return false;
}

// Build a simple hollow house (walls + flat roof + a doorway) from a block in
// inventory, starting at the bot's position. Best-effort, time-budgeted.
async function buildHouse(args) {
  const w = Math.max(3, Math.min(11, Number(args.width) || 5));
  const d = Math.max(3, Math.min(11, Number(args.depth) || 5));
  const h = Math.max(3, Math.min(7, Number(args.height) || 4));
  const matName = String(args.material || '').toLowerCase();
  const mat = matName ? findInventory(matName)
    : (findInventory('planks') || findInventory('cobblestone') || findInventory('stone_brick')
      || findInventory('stone') || findInventory('dirt'));
  if (!mat) return { ok: false, message: 'no building blocks (planks/cobblestone/etc.) in inventory' };
  const key = mat.name;
  const s = bot.entity.position.floored();
  const x0 = s.x; const y0 = s.y; const z0 = s.z;
  const doorX = x0 + Math.floor(w / 2);
  const onPerim = (x, z) => x === x0 || x === x0 + w - 1 || z === z0 || z === z0 + d - 1;
  let placed = 0;
  const start = Date.now();
  const BUDGET = 150000;
  for (let y = y0; y < y0 + h && Date.now() - start < BUDGET; y++) {
    for (let x = x0; x < x0 + w; x++) {
      for (let z = z0; z < z0 + d; z++) {
        if (!onPerim(x, z)) continue;
        if (x === doorX && z === z0 && (y === y0 || y === y0 + 1)) continue;  // doorway
        if (await placeBlockAt(x, y, z, key)) placed++;
        if (Date.now() - start > BUDGET) break;
      }
    }
  }
  if (args.roof !== false) {
    const ry = y0 + h;
    for (let x = x0; x < x0 + w && Date.now() - start < BUDGET; x++) {
      for (let z = z0; z < z0 + d; z++) {
        if (await placeBlockAt(x, ry, z, key)) placed++;
      }
    }
  }
  return { ok: placed > 0, message: `built a ${w}x${d}x${h} house (${placed} blocks placed)` };
}

async function equipBestWeapon() {
  const weapon = bot.inventory.items()
    .filter((i) => i.name.includes('sword') || i.name.includes('_axe'))
    .sort((a, b) => armorTier(b.name) - armorTier(a.name))[0];
  if (weapon) {
    try { await bot.equip(weapon, 'hand'); } catch (e) { /* ignore */ }
  }
}

async function defend(seconds) {
  seconds = Math.max(1, Math.min(8, Number(seconds) || 4));
  await equipBestWeapon();
  const end = Date.now() + seconds * 1000;
  let hits = 0;
  while (Date.now() < end) {
    const target = nearestHostile(8);
    if (!target) break;
    try {
      await bot.lookAt(target.position.offset(0, target.height ? target.height * 0.8 : 1.4, 0), true);
      bot.attack(target);
      hits += 1;
    } catch (e) { /* ignore */ }
    await sleep(350);
  }
  return { ok: true, message: hits ? `fought off hostiles (${hits} hits)` : 'no hostiles in range' };
}

async function act(verb, args) {
  if (!bot || !connected) return { ok: false, message: 'not connected' };
  args = args || {};
  try {
    switch (verb) {
      case 'say':
        bot.chat(String(args.text || '').slice(0, 200));
        return { ok: true, message: 'said it' };

      case 'goto': {
        if (args.x !== undefined && args.z !== undefined) {
          const y = args.y !== undefined ? args.y : bot.entity.position.y;
          await bot.pathfinder.goto(new goals.GoalNear(args.x, y, args.z, 1));
          return { ok: true, message: `arrived near ${args.x},${y},${args.z}` };
        }
        return { ok: false, message: 'goto needs x and z' };
      }

      case 'follow': {
        const ent = playerEntity(args.player);
        if (!ent) return { ok: false, message: `can't see ${args.player || OWNER || 'owner'}` };
        bot.pathfinder.setGoal(new goals.GoalFollow(ent, 2), true);
        return { ok: true, message: `following ${args.player || OWNER}` };
      }

      case 'come':
        return await comeTo(args.player);

      case 'find_in_chests': {
        const name = String(args.name || args.item || '');
        if (!name) return { ok: false, message: 'need an item name' };
        const wc = args.withdraw === true ? (args.count !== undefined ? Number(args.count) : 1e9)
          : (args.count !== undefined && args.withdraw !== false ? Number(args.count) : null);
        return await findInChests(name, wc);
      }

      case 'withdraw': {
        const name = String(args.name || args.item || '');
        const count = args.count !== undefined ? Number(args.count) : 1e9;
        if (!name) return { ok: false, message: 'need an item name' };
        return await findInChests(name, count);
      }

      case 'bring': {
        const name = String(args.name || args.item || '');
        if (!name) return { ok: false, message: 'need an item name' };
        const count = args.count !== undefined ? Number(args.count) : null;
        // Ensure we actually have the item; otherwise grab it from chests.
        if (countInInventory(name) <= 0) {
          await findInChests(name, count !== null ? count : 1e9);
        }
        if (countInInventory(name) <= 0) return { ok: false, message: `couldn't find any ${name}` };
        const arrive = await comeTo(args.player);
        if (!arrive.ok) return arrive;
        const item = resolveItem(name);
        try {
          const ent = playerEntity(args.player);
          if (ent) await bot.lookAt(ent.position.offset(0, 1, 0));
          await bot.toss(item.id, null, count !== null ? count : undefined);
        } catch (e) { /* toss best-effort */ }
        return { ok: true, message: `brought ${name} to ${args.player || OWNER}` };
      }

      case 'attack': {
        // Attack a named player/mob if given, else the nearest hostile.
        const target = (args.target || args.name)
          ? entityByName(args.target || args.name)
          : nearestHostile(args.range || 12);
        if (!target) {
          return { ok: false, message: (args.target || args.name)
            ? `can't see ${args.target || args.name}` : 'no hostiles in range' };
        }
        await equipBestWeapon();
        await bot.lookAt(target.position.offset(0, 1.4, 0), true);
        bot.attack(target);
        return { ok: true, message: `attacked ${target.username || target.name}` };
      }

      case 'punch': {
        // One bare-fist hit on a named player/mob ("smack USERNAME").
        const target = entityByName(args.target || args.name || args.player);
        if (!target) return { ok: false, message: `can't see ${args.target || args.name || 'them'}` };
        try { await bot.unequip('hand'); } catch (e) { /* already empty */ }
        await bot.lookAt(target.position.offset(0, 1.4, 0), true);
        bot.attack(target);
        return { ok: true, message: `punched ${target.username || target.name}` };
      }

      case 'find_ores': {
        const name = String(args.name || '').toLowerCase();
        const exposedOnly = args.exposed !== false;   // legit by default
        const ids = [];
        for (const key in bot.registry.blocksByName) {
          const isOre = name
            ? (key.includes(name) && key.includes('ore'))
            : ORE_KEYWORDS.some((o) => key.includes(o));
          if (isOre) ids.push(bot.registry.blocksByName[key].id);
        }
        if (!ids.length) return { ok: false, message: 'no such ore type' };
        const positions = bot.findBlocks({ matching: ids, maxDistance: 32, count: 64 });
        const list = [];
        for (const pos of positions) {
          const b = bot.blockAt(pos);
          if (!b) continue;
          if (exposedOnly && !isExposed(b)) continue;
          list.push({ name: b.name, x: pos.x, y: pos.y, z: pos.z,
            dist: Math.round(pos.distanceTo(bot.entity.position)) });
          if (list.length >= 8) break;
        }
        list.sort((a, b) => a.dist - b.dist);
        return {
          ok: true,
          ores: list,
          message: list.length
            ? 'found ' + list.map((o) => `${o.name} @${o.x},${o.y},${o.z} (${o.dist}m)`).join('; ')
            : (exposedOnly ? 'no exposed ores nearby — dig around a cave to expose some' : 'no ores nearby'),
        };
      }

      case 'store':
      case 'deposit': {
        const name = String(args.name || args.item || '');
        if (!name) return { ok: false, message: 'need an item name' };
        const ids = chestBlockIds();
        const positions = bot.findBlocks({ matching: ids, maxDistance: 32, count: 8 });
        if (!positions.length) return { ok: false, message: 'no chest nearby' };
        const want = args.count !== undefined ? Number(args.count) : 1e9;
        let stored = 0;
        for (const p of positions) {
          if (stored >= want) break;
          try {
            await bot.pathfinder.goto(new goals.GoalNear(p.x, p.y, p.z, 1));
            const container = await bot.openContainer(bot.blockAt(p));
            const items = bot.inventory.items().filter((i) => i.name.includes(name.toLowerCase()));
            for (const it of items) {
              if (stored >= want) break;
              const take = Math.min(it.count, want - stored);
              try { await container.deposit(it.type, null, take); stored += take; } catch (e) { /* chest full */ }
            }
            container.close();
          } catch (e) { /* try next chest */ }
        }
        return { ok: stored > 0, message: stored ? `stored ${stored} ${name}` : `couldn't store ${name} (chest full or none held)` };
      }

      case 'place_at': {
        const name = String(args.name || args.block || '').toLowerCase();
        if (!name || args.x === undefined || args.z === undefined) {
          return { ok: false, message: 'place_at needs name + x,y,z' };
        }
        const invItem = bot.inventory.items().find((i) => i.name.includes(name));
        if (!invItem) return { ok: false, message: `no ${name} in inventory` };
        const y = args.y !== undefined ? args.y : Math.floor(bot.entity.position.y);
        const target = new Vec3(Math.floor(args.x), Math.floor(y), Math.floor(args.z));
        await bot.pathfinder.goto(new goals.GoalNear(target.x, target.y, target.z, 2));
        // Find a solid neighbour to place against.
        const faces = [[0,-1,0],[0,1,0],[1,0,0],[-1,0,0],[0,0,1],[0,0,-1]];
        let ref = null; let face = null;
        for (const [dx,dy,dz] of faces) {
          const nb = bot.blockAt(target.offset(dx, dy, dz));
          if (nb && nb.name !== 'air' && nb.boundingBox === 'block') { ref = nb; face = new Vec3(-dx, -dy, -dz); break; }
        }
        if (!ref) return { ok: false, message: 'no solid surface to place against there' };
        try {
          await bot.equip(invItem, 'hand');
          await bot.placeBlock(ref, face);
          return { ok: true, message: `placed ${name} at ${target.x},${target.y},${target.z}` };
        } catch (e) { return { ok: false, message: `place failed: ${(e && e.message) || e}` }; }
      }

      case 'sleep': {
        const bed = bot.findBlock({ matching: (b) => b && b.name && b.name.includes('bed'), maxDistance: 16 });
        if (!bed) return { ok: false, message: 'no bed nearby' };
        await bot.pathfinder.goto(new goals.GoalNear(bed.position.x, bed.position.y, bed.position.z, 2));
        try { await bot.sleep(bot.blockAt(bed.position)); return { ok: true, message: 'sleeping' }; }
        catch (e) { return { ok: false, message: `can't sleep: ${(e && e.message) || e}` }; }
      }

      case 'wake': {
        try { await bot.wake(); return { ok: true, message: 'woke up' }; }
        catch (e) { return { ok: false, message: 'not sleeping' }; }
      }

      // ── farming ──────────────────────────────────────────────────────────
      case 'till': {
        const hoe = findInventory('_hoe');
        if (!hoe) return { ok: false, message: 'no hoe in inventory' };
        const radius = Math.max(1, Math.min(8, Number(args.radius) || 4));
        const max = Math.max(1, Math.min(32, Number(args.count) || 8));
        const ids = idsForNames(['dirt', 'grass_block', 'coarse_dirt', 'rooted_dirt', 'dirt_path']);
        const positions = bot.findBlocks({ matching: ids, maxDistance: radius + 2, count: 96 });
        await bot.equip(hoe, 'hand');
        let tilled = 0;
        for (const p of positions) {
          if (tilled >= max) break;
          const above = bot.blockAt(p.offset(0, 1, 0));
          if (!above || above.name !== 'air') continue;
          try {
            await bot.pathfinder.goto(new goals.GoalNear(p.x, p.y, p.z, 2));
            await bot.activateBlock(bot.blockAt(p));
            tilled++;
          } catch (e) { /* skip */ }
        }
        return { ok: tilled > 0, message: tilled ? `tilled ${tilled} block(s)` : 'nothing to till nearby' };
      }

      case 'plant': {
        const seedName = String(args.seed || args.name || 'wheat_seeds').toLowerCase();
        const seed = findInventory(seedName);
        if (!seed) return { ok: false, message: `no ${seedName} in inventory` };
        const radius = Math.max(1, Math.min(8, Number(args.radius) || 4));
        const max = Math.max(1, Math.min(32, Number(args.count) || 8));
        const positions = bot.findBlocks({ matching: idsForNames(['farmland']), maxDistance: radius + 2, count: 96 });
        let planted = 0;
        for (const p of positions) {
          if (planted >= max) break;
          const above = bot.blockAt(p.offset(0, 1, 0));
          if (!above || above.name !== 'air') continue;
          try {
            await bot.pathfinder.goto(new goals.GoalNear(p.x, p.y, p.z, 2));
            await bot.equip(seed, 'hand');
            await bot.placeBlock(bot.blockAt(p), new Vec3(0, 1, 0));
            planted++;
          } catch (e) { /* skip */ }
        }
        return { ok: planted > 0, message: planted ? `planted ${planted} ${seedName}` : 'no empty farmland nearby (till first)' };
      }

      case 'harvest': {
        const radius = Math.max(1, Math.min(16, Number(args.radius) || 6));
        const max = Math.max(1, Math.min(128, Number(args.count) || 32));
        const cropName = String(args.crop || args.name || '').toLowerCase();
        const cropNames = cropName ? [cropName] : Object.keys(CROP_MATURE_AGE);
        const positions = bot.findBlocks({ matching: idsForNames(cropNames), maxDistance: radius + 2, count: 256 });
        const replant = args.replant !== false;
        let harvested = 0;
        for (const p of positions) {
          if (harvested >= max) break;
          const block = bot.blockAt(p);
          if (!isMatureCrop(block)) continue;
          try {
            await bot.pathfinder.goto(new goals.GoalNear(p.x, p.y, p.z, 1));
            const name = block.name;
            await bot.dig(bot.blockAt(p));
            harvested++;
            if (replant) {
              const seedName = CROP_TO_SEED[name];
              const seed = seedName && findInventory(seedName);
              const below = bot.blockAt(p.offset(0, -1, 0));
              if (seed && below && below.name === 'farmland') {
                try { await bot.equip(seed, 'hand'); await bot.placeBlock(below, new Vec3(0, 1, 0)); } catch (e) { /* skip */ }
              }
            }
          } catch (e) { /* skip */ }
        }
        return { ok: harvested > 0, message: harvested ? `harvested ${harvested} crop(s)` : 'no mature crops nearby' };
      }

      case 'bonemeal': {
        const bm = findInventory('bone_meal');
        if (!bm) return { ok: false, message: 'no bone meal in inventory' };
        const radius = Math.max(1, Math.min(8, Number(args.radius) || 4));
        const max = Math.max(1, Math.min(32, Number(args.count) || 8));
        const ids = [];
        for (const key in bot.registry.blocksByName) {
          if (CROP_MATURE_AGE[key] !== undefined || key.includes('sapling')) {
            ids.push(bot.registry.blocksByName[key].id);
          }
        }
        const positions = bot.findBlocks({ matching: ids, maxDistance: radius + 2, count: 64 });
        let used = 0;
        for (const p of positions) {
          if (used >= max) break;
          const block = bot.blockAt(p);
          if (block && CROP_MATURE_AGE[block.name] !== undefined && isMatureCrop(block)) continue;
          try {
            await bot.pathfinder.goto(new goals.GoalNear(p.x, p.y, p.z, 2));
            await bot.equip(bm, 'hand');
            await bot.activateBlock(bot.blockAt(p));
            used++;
          } catch (e) { /* skip */ }
        }
        return { ok: used > 0, message: used ? `used bone meal ${used}x` : 'nothing to bone-meal nearby' };
      }

      case 'plant_tree': {
        const sapName = String(args.sapling || args.name || 'sapling').toLowerCase();
        const sap = findInventory(sapName + (sapName.includes('sapling') ? '' : '_sapling')) || findInventory('sapling');
        if (!sap) return { ok: false, message: 'no sapling in inventory' };
        const radius = Math.max(1, Math.min(8, Number(args.radius) || 4));
        const max = Math.max(1, Math.min(16, Number(args.count) || 3));
        const ids = idsForNames(['grass_block', 'dirt', 'podzol', 'coarse_dirt', 'rooted_dirt']);
        const positions = bot.findBlocks({ matching: ids, maxDistance: radius + 2, count: 96 });
        let planted = 0;
        for (const p of positions) {
          if (planted >= max) break;
          const above = bot.blockAt(p.offset(0, 1, 0));
          if (!above || above.name !== 'air') continue;
          try {
            await bot.pathfinder.goto(new goals.GoalNear(p.x, p.y, p.z, 2));
            await bot.equip(sap, 'hand');
            await bot.placeBlock(bot.blockAt(p), new Vec3(0, 1, 0));
            planted++;
          } catch (e) { /* skip */ }
        }
        return { ok: planted > 0, message: planted ? `planted ${planted} sapling(s)` : 'no open ground to plant on' };
      }

      // ── smelting ─────────────────────────────────────────────────────────
      case 'smelt': {
        const inputName = String(args.input || args.name || '').toLowerCase();
        if (!inputName) return { ok: false, message: 'need an input (e.g. raw_iron)' };
        return await smeltInput(inputName, String(args.fuel || '').toLowerCase() || null, args.count);
      }

      case 'cook': {
        const RAW = ['beef', 'porkchop', 'chicken', 'mutton', 'rabbit', 'cod', 'salmon', 'potato', 'kelp'];
        let inputName = String(args.food || args.input || '').toLowerCase();
        if (!inputName) {
          const raw = bot.inventory.items().find((i) => RAW.includes(i.name));
          if (!raw) return { ok: false, message: 'no raw food to cook' };
          inputName = raw.name;
        }
        return await smeltInput(inputName, String(args.fuel || '').toLowerCase() || null, args.count);
      }

      case 'hunt': {
        const want = String(args.animal || '').toLowerCase();
        const names = want ? [want] : FOOD_ANIMALS;
        await equipBestWeapon();
        const maxKills = Math.max(1, Math.min(5, Number(args.count) || 1));
        let kills = 0;
        const start = Date.now();
        while (kills < maxKills && Date.now() - start < 15000) {
          let target = null;
          let bestD = 20;
          for (const id in bot.entities) {
            const e = bot.entities[id];
            if (!e || !e.position) continue;
            if (names.includes(String(e.name || '').toLowerCase())) {
              const dd = e.position.distanceTo(bot.entity.position);
              if (dd < bestD) { bestD = dd; target = e; }
            }
          }
          if (!target) break;
          try {
            await bot.pathfinder.goto(new goals.GoalNear(target.position.x, target.position.y, target.position.z, 2));
            const t2 = Date.now();
            while (target.isValid && Date.now() - t2 < 6000) {
              await bot.lookAt(target.position.offset(0, 0.4, 0), true);
              bot.attack(target);
              await sleep(600);
            }
            kills++;
          } catch (e) { break; }
        }
        return { ok: kills > 0, message: kills ? `hunted ${kills} animal(s) for food` : 'no food animals nearby' };
      }

      case 'build_house':
      case 'build': {
        return await buildHouse(args);
      }

      case 'take_smelted': {
        const fb = bot.findBlock({ matching: idsForNames(['furnace', 'blast_furnace', 'smoker']), maxDistance: 16 });
        if (!fb) return { ok: false, message: 'no furnace nearby' };
        await bot.pathfinder.goto(new goals.GoalNear(fb.position.x, fb.position.y, fb.position.z, 2));
        const furnace = await bot.openFurnace(bot.blockAt(fb.position));
        try {
          const out = furnace.outputItem();
          if (!out) { furnace.close(); return { ok: false, message: 'nothing smelted yet — give it time' }; }
          await furnace.takeOutput();
          furnace.close();
          return { ok: true, message: `collected ${out.count} ${out.name}` };
        } catch (e) {
          try { furnace.close(); } catch (_) { /* ignore */ }
          return { ok: false, message: `couldn't take output: ${(e && e.message) || e}` };
        }
      }

      // ── exploring / villages / trading ─────────────────────────────────────
      case 'explore': {
        const dist = Math.max(8, Math.min(128, Number(args.distance) || 48));
        const pos = bot.entity.position;
        let dx; let dz;
        const dir = String(args.direction || '').toLowerCase();
        if (dir.includes('north')) { dx = 0; dz = -1; }
        else if (dir.includes('south')) { dx = 0; dz = 1; }
        else if (dir.includes('east')) { dx = 1; dz = 0; }
        else if (dir.includes('west')) { dx = -1; dz = 0; }
        else { dx = -Math.sin(bot.entity.yaw); dz = Math.cos(bot.entity.yaw); }  // face direction
        const tx = Math.floor(pos.x + dx * dist);
        const tz = Math.floor(pos.z + dz * dist);
        try {
          await bot.pathfinder.goto(new goals.GoalNear(tx, Math.floor(pos.y), tz, 3));
          return { ok: true, message: `explored toward ${tx}, ${tz}` };
        } catch (e) {
          return { ok: false, message: `couldn't path there: ${(e && e.message) || e}` };
        }
      }

      case 'find_village':
      case 'find_villagers': {
        const villagers = [];
        for (const id in bot.entities) {
          const e = bot.entities[id];
          if (!e || !e.position || String(e.name || '').toLowerCase() !== 'villager') continue;
          villagers.push({
            x: Math.round(e.position.x), y: Math.round(e.position.y), z: Math.round(e.position.z),
            dist: Math.round(e.position.distanceTo(bot.entity.position)),
          });
        }
        villagers.sort((a, b) => a.dist - b.dist);
        const bell = bot.findBlock({ matching: idsForNames(['bell']), maxDistance: 64 });
        let message;
        if (villagers.length) {
          message = `${villagers.length} villager(s): `
            + villagers.slice(0, 5).map((v) => `@${v.x},${v.y},${v.z} (${v.dist}m)`).join('; ');
        } else if (bell) {
          message = `village bell at ${bell.position.x},${bell.position.y},${bell.position.z} — go closer to load villagers`;
        } else {
          message = 'no village in range — explore further';
        }
        return { ok: villagers.length > 0 || !!bell, villagers, message };
      }

      case 'list_trades': {
        const v = nearestVillager(args.range || 16);
        if (!v) return { ok: false, message: 'no villager nearby (explore/come to one first)' };
        await bot.pathfinder.goto(new goals.GoalNear(v.position.x, v.position.y, v.position.z, 2));
        const win = await bot.openVillager(v);
        try {
          const trades = (win.trades || []).map((t, i) => {
            const ins = [t.inputItem1, t.inputItem2].filter(Boolean)
              .map((it) => `${it.count}x ${it.name || it.displayName || it.type}`).join(' + ');
            const out = t.outputItem
              ? `${t.outputItem.count}x ${t.outputItem.name || t.outputItem.displayName}` : '?';
            return `[${i}] ${ins} -> ${out}${t.tradeDisabled ? ' (out of stock)' : ''}`;
          });
          win.close();
          return { ok: true, trades, message: trades.length ? trades.join(' | ') : 'this villager has no trades' };
        } catch (e) {
          try { win.close(); } catch (_) { /* ignore */ }
          return { ok: false, message: `couldn't read trades: ${(e && e.message) || e}` };
        }
      }

      case 'trade': {
        const v = nearestVillager(args.range || 16);
        if (!v) return { ok: false, message: 'no villager nearby' };
        await bot.pathfinder.goto(new goals.GoalNear(v.position.x, v.position.y, v.position.z, 2));
        const win = await bot.openVillager(v);
        try {
          let index = args.index;
          if ((index === undefined || index === null) && (args.item || args.want)) {
            const want = String(args.item || args.want).toLowerCase();
            index = (win.trades || []).findIndex(
              (t) => t.outputItem && String(t.outputItem.name || '').includes(want));
          }
          if (index === undefined || index === null || index < 0) {
            win.close();
            return { ok: false, message: 'specify a trade index (use list_trades) or a valid item' };
          }
          const trade = (win.trades || [])[index];
          if (!trade) { win.close(); return { ok: false, message: `no trade #${index}` }; }
          if (trade.tradeDisabled) { win.close(); return { ok: false, message: `trade #${index} is out of stock` }; }
          const count = Math.max(1, Number(args.count) || 1);
          await bot.trade(win, index, count);
          win.close();
          return { ok: true, message: `traded #${index} x${count}` };
        } catch (e) {
          try { win.close(); } catch (_) { /* ignore */ }
          return { ok: false, message: `trade failed: ${(e && e.message) || e}` };
        }
      }

      case 'defend':
        return await defend(args.seconds);

      case 'mine':
      case 'collect': {
        let block;
        if (args.x !== undefined && args.z !== undefined) {
          // Mine a specific coordinate (e.g. an ore located via find_ores).
          const y = args.y !== undefined ? args.y : Math.floor(bot.entity.position.y);
          const pos = new Vec3(Math.floor(args.x), Math.floor(y), Math.floor(args.z));
          await bot.pathfinder.goto(new goals.GoalNear(pos.x, pos.y, pos.z, 1));
          block = bot.blockAt(pos);
          if (!block || block.name === 'air') return { ok: false, message: 'nothing to mine there' };
        } else {
          const name = String(args.name || args.block || '').toLowerCase();
          if (!name) return { ok: false, message: 'need a block name or coordinates' };
          const ids = [];
          for (const key in bot.registry.blocksByName) {
            if (key.includes(name)) ids.push(bot.registry.blocksByName[key].id);
          }
          if (!ids.length) return { ok: false, message: `unknown block ${name}` };
          const found = bot.findBlock({ matching: ids, maxDistance: 64 });
          if (!found) return { ok: false, message: `no ${name} nearby` };
          await bot.pathfinder.goto(new goals.GoalNear(found.position.x, found.position.y, found.position.z, 1));
          block = bot.blockAt(found.position) || found;
        }
        // Equip the best available tool — required for ores, much faster for stone/wood.
        try { if (bot.tool) await bot.tool.equipForBlock(block, {}); } catch (e) { /* ignore */ }
        if (typeof bot.canDigBlock === 'function' && !bot.canDigBlock(block)) {
          return { ok: false, message: `can't mine ${block.name} yet — need a better/correct tool` };
        }
        try { await bot.lookAt(block.position.offset(0.5, 0.5, 0.5), true); } catch (e) { /* ignore */ }
        await bot.dig(block);
        return { ok: true, message: `mined ${block.name}` };
      }

      case 'equip': {
        const name = String(args.name || args.item || '').toLowerCase();
        if (!name) return { ok: false, message: 'need an item name' };
        const item = bot.inventory.items().find((i) => i.name.includes(name));
        if (!item) return { ok: false, message: `no ${name} in inventory` };
        const dest = String(args.where || armorSlotForItem(item.name) || 'hand');
        await bot.equip(item, dest);
        return { ok: true, message: `equipped ${item.name} (${dest})` };
      }

      case 'equip_armor': {
        const slots = {
          head: ['helmet', 'cap', 'turtle'],
          torso: ['chestplate'],
          legs: ['leggings'],
          feet: ['boots'],
        };
        const equipped = [];
        for (const [slot, kws] of Object.entries(slots)) {
          const cands = bot.inventory.items().filter((i) => kws.some((k) => i.name.includes(k)));
          if (!cands.length) continue;
          cands.sort((a, b) => armorTier(b.name) - armorTier(a.name));
          try { await bot.equip(cands[0], slot); equipped.push(cands[0].name); } catch (e) { /* skip */ }
        }
        return { ok: true, message: equipped.length ? `equipped ${equipped.join(', ')}` : 'no armor in inventory' };
      }

      case 'eat': {
        const food = bot.inventory.items().find((i) => isFood(i.name));
        if (!food) return { ok: false, message: 'no food in inventory' };
        try {
          await bot.equip(food, 'hand');
          await bot.consume();
          return { ok: true, message: `ate ${food.name}` };
        } catch (e) {
          return { ok: false, message: `couldn't eat (full?): ${(e && e.message) || e}` };
        }
      }

      case 'craft': {
        const name = String(args.name || args.item || '').toLowerCase();
        const item = bot.registry.itemsByName[name];
        if (!item) return { ok: false, message: `unknown item ${name}` };
        const want = Math.max(1, Number(args.count) || 1);
        // 2x2 recipes (planks, sticks, table) need no bench; try that first.
        let recipes = bot.recipesFor(item.id, null, want, null);
        let table = null;
        if (!recipes.length) {
          table = await ensureCraftingTable();   // find / craft+place a bench
          if (table) recipes = bot.recipesFor(item.id, null, want, table);
        }
        if (!recipes.length) {
          return { ok: false, message: `can't craft ${name} — missing ingredients`
            + (table ? '' : ' or a crafting table') };
        }
        try {
          await bot.craft(recipes[0], want, table || null);
          return { ok: true, message: `crafted ${want}x ${name}` };
        } catch (e) {
          return { ok: false, message: `craft failed: ${(e && e.message) || e}` };
        }
      }

      case 'place_table': {
        const table = await ensureCraftingTable();
        return table
          ? { ok: true, message: 'crafting table ready' }
          : { ok: false, message: 'no crafting table and no planks to make one' };
      }

      case 'gather': {
        // Mine several of a block type from the area (bounded so it fits a tick).
        const name = String(args.name || args.block || '').toLowerCase();
        if (!name) return { ok: false, message: 'need a block name' };
        const want = Math.max(1, Math.min(16, Number(args.count) || 4));
        const ids = [];
        for (const key in bot.registry.blocksByName) {
          if (key.includes(name)) ids.push(bot.registry.blocksByName[key].id);
        }
        if (!ids.length) return { ok: false, message: `unknown block ${name}` };
        let got = 0;
        const start = Date.now();
        while (got < want && Date.now() - start < 15000) {
          const found = bot.findBlock({ matching: ids, maxDistance: 48 });
          if (!found) break;
          try {
            await bot.pathfinder.goto(new goals.GoalNear(found.position.x, found.position.y, found.position.z, 1));
            const block = bot.blockAt(found.position) || found;
            try { if (bot.tool) await bot.tool.equipForBlock(block, {}); } catch (e) { /* ignore */ }
            if (typeof bot.canDigBlock === 'function' && !bot.canDigBlock(block)) break;
            await bot.dig(block);
            got++;
          } catch (e) { break; }
        }
        return { ok: got > 0, message: got ? `gathered ${got} ${name}` : `couldn't gather ${name}` };
      }

      // ── fishing ───────────────────────────────────────────────────────────
      case 'fish': {
        const rod = findInventory('fishing_rod');
        if (!rod) return { ok: false, message: 'no fishing rod (craft one: 3 sticks + 2 string)' };
        const water = bot.findBlock({ matching: idsForNames(['water']), maxDistance: 24 });
        if (!water) return { ok: false, message: 'no water nearby to fish in' };
        try {
          await bot.pathfinder.goto(new goals.GoalNear(water.position.x, water.position.y, water.position.z, 4));
          await bot.equip(rod, 'hand');
          await bot.lookAt(water.position.offset(0.5, 0.6, 0.5), true);
          await bot.fish();   // casts, waits for a bite, reels in
          return { ok: true, message: 'caught something!' };
        } catch (e) {
          try { if (bot.usingHeldItem) await bot.activateItem(); } catch (_) { /* reel in */ }
          return { ok: false, message: `fishing failed: ${(e && e.message) || e}` };
        }
      }

      // ── animal breeding ───────────────────────────────────────────────────
      case 'breed': {
        let type = String(args.animal || args.name || '').toLowerCase();
        const near = [];
        for (const id in bot.entities) {
          const e = bot.entities[id];
          if (!e || !e.position) continue;
          const nm = String(e.name || '').toLowerCase();
          if (ANIMAL_FOOD[nm] && e.position.distanceTo(bot.entity.position) < 16) {
            near.push({ e, nm, d: e.position.distanceTo(bot.entity.position) });
          }
        }
        if (!near.length) return { ok: false, message: 'no breedable animals nearby' };
        if (!type) {
          const counts = {};
          near.forEach((a) => { counts[a.nm] = (counts[a.nm] || 0) + 1; });
          type = Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0];
        }
        const foodName = String(args.food || ANIMAL_FOOD[type] || '').toLowerCase();
        const food = foodName && findInventory(foodName);
        if (!food) return { ok: false, message: `need ${foodName || 'the right food'} to breed ${type}` };
        const targets = near.filter((a) => a.nm === type).sort((a, b) => a.d - b.d).slice(0, 2);
        if (targets.length < 2) return { ok: false, message: `need 2 ${type} close together` };
        let fed = 0;
        for (const t of targets) {
          try {
            await bot.pathfinder.goto(new goals.GoalNear(t.e.position.x, t.e.position.y, t.e.position.z, 2));
            await bot.equip(food, 'hand');
            await bot.lookAt(t.e.position.offset(0, 0.4, 0), true);
            await bot.activateEntity(t.e);
            fed++;
          } catch (e) { /* skip */ }
        }
        return { ok: fed >= 2, message: fed >= 2 ? `fed two ${type} — they'll breed` : `only managed to feed ${fed} ${type}` };
      }

      // ── auto-upgrade tools ────────────────────────────────────────────────
      case 'upgrade_tools': {
        const toolKinds = ['pickaxe', 'axe', 'shovel', 'sword', 'hoe'];
        const table = await ensureCraftingTable();
        const made = [];
        for (const kind of toolKinds) {
          const owned = bot.inventory.items().filter((i) => i.name.endsWith('_' + kind));
          const bestOwned = owned.length
            ? Math.min(...owned.map((i) => {
              const idx = TOOL_TIERS.indexOf(toolTier(i.name));
              return idx === -1 ? 99 : idx;
            }))
            : 99;
          for (let ti = 0; ti < bestOwned && ti < TOOL_TIERS.length; ti++) {
            const item = bot.registry.itemsByName[`${TOOL_TIERS[ti]}_${kind}`];
            if (!item) continue;
            const recs = bot.recipesFor(item.id, null, 1, table || null);
            if (recs.length) {
              try { await bot.craft(recs[0], 1, table || null); made.push(`${TOOL_TIERS[ti]}_${kind}`); } catch (e) { /* skip */ }
              break;  // crafted the best tier we can for this tool
            }
          }
        }
        try { await equipBestWeapon(); } catch (e) { /* ignore */ }
        return {
          ok: made.length > 0,
          message: made.length ? `crafted ${made.join(', ')}` : 'no better tools craftable with current materials',
        };
      }

      case 'place': {
        const name = String(args.name || args.block || '').toLowerCase();
        const invItem = bot.inventory.items().find((i) => i.name.includes(name));
        if (!invItem) return { ok: false, message: `no ${name} in inventory` };
        const ref = bot.blockAt(bot.entity.position.offset(0, -1, 0));
        if (!ref) return { ok: false, message: 'no reference block to place on' };
        await bot.equip(invItem, 'hand');
        await bot.placeBlock(ref, { x: 0, y: 1, z: 0 });
        return { ok: true, message: `placed ${name}` };
      }

      case 'drop': {
        const name = String(args.name || args.item || '');
        const item = resolveItem(name);
        if (!item) return { ok: false, message: `unknown item ${name}` };
        await bot.toss(item.id, null, args.count !== undefined ? Number(args.count) : undefined);
        return { ok: true, message: `dropped ${name}` };
      }

      case 'look': {
        const yaw = args.yaw !== undefined ? args.yaw : bot.entity.yaw;
        const pitch = args.pitch !== undefined ? args.pitch : 0;
        await bot.look(yaw, pitch, false);
        return { ok: true, message: 'looked around' };
      }

      case 'stop':
        try { bot.pathfinder.setGoal(null); } catch (e) { /* ignore */ }
        bot.clearControlStates();
        return { ok: true, message: 'stopped' };

      case 'wait':
        return { ok: true, message: 'waited' };

      default:
        return { ok: false, message: `unknown verb ${verb}` };
    }
  } catch (e) {
    return { ok: false, message: String((e && e.message) || e) };
  }
}

// ── HTTP server ──────────────────────────────────────────────────────────────
function sendJson(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { 'Content-Type': 'application/json' });
  res.end(body);
}

const server = http.createServer((req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    return sendJson(res, 200, { ok: true, connected, lastError });
  }
  if (req.method === 'GET' && req.url === '/observe') {
    return sendJson(res, 200, observe());
  }
  if (req.method === 'POST' && req.url === '/act') {
    let data = '';
    req.on('data', (chunk) => { data += chunk; });
    req.on('end', async () => {
      let payload = {};
      try { payload = JSON.parse(data || '{}'); } catch (e) { /* ignore */ }
      const result = await act(payload.verb, payload.args);
      sendJson(res, 200, result);
    });
    return;
  }
  sendJson(res, 404, { ok: false, message: 'not found' });
});

createBot();
server.listen(BRIDGE_PORT, '127.0.0.1', () => {
  log(`listening on 127.0.0.1:${BRIDGE_PORT}, connecting to ${HOST}:${PORT} (auth=${AUTH})`);
});
