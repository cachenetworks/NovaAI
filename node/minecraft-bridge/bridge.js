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
        const target = nearestHostile(args.range || 12);
        if (!target) return { ok: false, message: 'no hostiles in range' };
        await equipBestWeapon();
        await bot.lookAt(target.position.offset(0, 1.4, 0), true);
        bot.attack(target);
        return { ok: true, message: `attacked ${target.name}` };
      }

      case 'defend':
        return await defend(args.seconds);

      case 'mine':
      case 'collect': {
        const name = String(args.name || args.block || '').toLowerCase();
        if (!name) return { ok: false, message: 'need a block name' };
        const ids = [];
        for (const key in bot.registry.blocksByName) {
          if (key.includes(name)) ids.push(bot.registry.blocksByName[key].id);
        }
        if (!ids.length) return { ok: false, message: `unknown block ${name}` };
        const found = bot.findBlock({ matching: ids, maxDistance: 64 });
        if (!found) return { ok: false, message: `no ${name} nearby` };
        await bot.pathfinder.goto(new goals.GoalNear(found.position.x, found.position.y, found.position.z, 1));
        const block = bot.blockAt(found.position) || found;
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
        const tableId = bot.registry.blocksByName.crafting_table
          ? [bot.registry.blocksByName.crafting_table.id] : [];
        const table = tableId.length ? bot.findBlock({ matching: tableId, maxDistance: 8 }) : null;
        const recipes = bot.recipesFor(item.id, null, 1, table || null);
        if (!recipes.length) return { ok: false, message: `no recipe for ${name} (need ingredients/table?)` };
        await bot.craft(recipes[0], args.count || 1, table || null);
        return { ok: true, message: `crafted ${name}` };
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
