import gameData from "./game_data.json";

export const ROOM_SIZE = 3;
export const WIN_SCORE = 15;
export const DRAFT_OPTIONS = 5;
export const GUESS_COUNTDOWN = 60;
export const DRAFT_COUNTDOWN = 30;

export const ATTRIBUTE_ORDER = ["country", "position", "club"];
export const ATTRIBUTE_LABELS = {
  country: "Country",
  position: "Position",
  club: "Club",
};

function shuffle(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function sample(arr, k) {
  if (!arr || arr.length <= k) return [...(arr || [])];
  return shuffle(arr).slice(0, k);
}

export function normalizeName(name) {
  return String(name || "")
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function clubId(value) {
  if (value && typeof value === "object") return String(value.id ?? "");
  return value == null ? "" : String(value);
}

export function clubDisplay(value) {
  if (value && typeof value === "object") {
    return String(value.name ?? value.id ?? "");
  }
  if (value == null) return "";
  const s = String(value);
  const byId = getClubsById();
  const info = byId[s];
  return info ? String(info.name || s) : s;
}

function clubValueKey(value) {
  if (value && typeof value === "object") return String(value.id ?? "");
  return String(value);
}

function sampleWeighted(pool, priorityPool, k, priorityCount) {
  pool = [...(pool || [])];
  const poolByKey = {};
  for (const x of pool) poolByKey[clubValueKey(x)] = x;
  const priorityKeys = [];
  for (const x of priorityPool || []) {
    const key = clubValueKey(x);
    if (key in poolByKey) priorityKeys.push(key);
  }
  const seen = new Set();
  const priority = [];
  for (const key of priorityKeys) {
    if (!seen.has(key)) {
      seen.add(key);
      priority.push(poolByKey[key]);
    }
  }
  const priorityKeySet = new Set(priority.map(clubValueKey));
  const others = pool.filter((x) => !priorityKeySet.has(clubValueKey(x)));

  if (pool.length <= k) return [...pool];

  let pCount = Math.min(priorityCount, k, priority.length);
  let oCount = k - pCount;
  if (oCount > others.length) {
    oCount = others.length;
    pCount = Math.min(k - oCount, priority.length);
  }

  let chosen = [];
  if (pCount > 0 && priority.length) chosen = chosen.concat(sample(priority, pCount));
  if (oCount > 0 && others.length) chosen = chosen.concat(sample(others, oCount));

  const remainingNeeded = k - chosen.length;
  if (remainingNeeded > 0) {
    const chosenKeys = new Set(chosen.map(clubValueKey));
    const remaining = pool.filter((x) => !chosenKeys.has(clubValueKey(x)));
    if (remaining.length) chosen = chosen.concat(sample(remaining, Math.min(remainingNeeded, remaining.length)));
  }
  return shuffle(chosen);
}

let clubsByIdCache = null;
export function getClubsById() {
  if (clubsByIdCache) return clubsByIdCache;
  const clubs = (gameData.options && gameData.options.clubs) || [];
  const out = {};
  for (const c of clubs) {
    if (c && typeof c === "object") {
      const cid = String(c.id ?? "");
      if (cid) out[cid] = c;
    } else if (typeof c === "string") {
      out[c] = { id: c, name: c };
    }
  }
  clubsByIdCache = out;
  return out;
}

export function sampleOptions(attribute, k = DRAFT_OPTIONS) {
  const options = gameData.options || {};
  const keyMap = { country: "countries", position: "positions", club: "clubs" };
  const key = keyMap[attribute] || attribute;
  const pool = options[key] || [];

  if (attribute === "country") {
    const priority = options.top_fifa_countries || [];
    if (priority.length) return sampleWeighted(pool, priority, k, Math.min(3, k));
  } else if (attribute === "club") {
    const priority = options.top5_league_clubs || [];
    if (priority.length) return sampleWeighted(pool, priority, k, Math.min(3, k));
  }

  if (pool.length <= k) return [...pool];
  return sample(pool, k);
}

export function clubMatches(constraintClub, playerClubs) {
  const target = clubId(constraintClub);
  if (!target) return false;
  for (const club of playerClubs || []) {
    if (clubId(club) === target) return true;
  }
  return false;
}

const nameIndex = gameData.name_index || {};
const playersById = {};
for (const p of gameData.players || []) {
  playersById[p.player_id] = p;
}

export function findPlayerMatches(guess) {
  const norm = normalizeName(guess);
  if (!norm) return [];
  const ids = nameIndex[norm] || [];
  return ids.map((id) => playersById[id]).filter(Boolean);
}

const allPlayers = gameData.players || [];

export function bestGuessForConstraints(constraints) {
  const country = constraints.country;
  const position = constraints.position;
  const club = constraints.club;

  let bestName = null;
  let bestScore = -1;
  const samplePool = allPlayers.length <= 5000 ? allPlayers : sample(allPlayers, 5000);
  for (const p of samplePool) {
    let score = 0;
    if (country && p.country === country) score += 1;
    if (position && p.position === position) score += 1;
    if (club && clubMatches(club, p.clubs || [])) score += 1;
    if (score > bestScore) {
      bestScore = score;
      bestName = p.name;
      if (bestScore === 3) break;
    }
  }
  if (bestName) return bestName;
  return allPlayers.length ? allPlayers[Math.floor(Math.random() * allPlayers.length)].name || "Unknown Player" : "Unknown Player";
}

const playerNamePairs = (allPlayers || [])
  .filter((p) => p && p.name)
  .map((p) => ({ name: p.name, norm: normalizeName(p.name), position: p.position || "" }));

export function searchPlayerNames(query, limit = 8) {
  const q = normalizeName(query);
  if (!q) return [];
  const starts = [];
  const contains = [];
  const seen = new Set();
  for (const item of playerNamePairs) {
    if (!item.norm || seen.has(item.norm)) continue;
    const out = { name: item.name, position: item.position };
    if (item.norm.startsWith(q)) {
      seen.add(item.norm);
      starts.push(out);
      if (starts.length >= limit) return starts.slice(0, limit);
    } else if (item.norm.includes(q)) {
      contains.push(out);
    }
  }
  for (const out of contains) {
    const norm = normalizeName(out.name);
    if (seen.has(norm)) continue;
    seen.add(norm);
    starts.push(out);
    if (starts.length >= limit) break;
  }
  return starts.slice(0, limit);
}

function pickBotOption(attr, options) {
  const optsArr = (options || []).filter(Boolean);
  if (!optsArr.length) return null;
  const opts = gameData.options || {};
  let priority = [];
  if (attr === "country") priority = opts.top_fifa_countries || [];
  else if (attr === "club") priority = opts.top5_league_clubs || [];

  let priorityInOptions = [];
  let others = [];
  if (attr === "club") {
    const priorityKeys = new Set(priority.map(clubId));
    priorityInOptions = optsArr.filter((o) => priorityKeys.has(clubId(o)));
    others = optsArr.filter((o) => !priorityKeys.has(clubId(o)));
  } else {
    const prioritySet = new Set(priority);
    priorityInOptions = optsArr.filter((o) => prioritySet.has(o));
    others = optsArr.filter((o) => !prioritySet.has(o));
  }
  if (priorityInOptions.length && (!others.length || Math.random() < 0.8)) {
    return priorityInOptions[Math.floor(Math.random() * priorityInOptions.length)];
  }
  return optsArr[Math.floor(Math.random() * optsArr.length)];
}

export class FooTrioGame {
  constructor(humanName) {
    this.players = [
      { id: "p1", name: humanName || "Player", isBot: false, isHost: true },
      { id: "b1", name: "Bot 1", isBot: true, isHost: false },
      { id: "b2", name: "Bot 2", isBot: true, isHost: false },
    ];
    this.scores = { p1: 0, b1: 0, b2: 0 };
    this.state = "lobby";
    this.roundNumber = 0;
    this.assignmentOffset = 0;
    this.history = [];
    this.resetRoundState();
  }

  resetRoundState() {
    this.assignments = {};
    this.draftOptions = {};
    this.draftRefreshesLeft = {};
    this.selections = {};
    this.guesses = {};
    this.roundResult = null;
    this.draftDeadline = null;
    this.guessDeadline = null;
  }

  playerList() {
    return this.players.map((p) => ({
      id: p.id,
      name: p.name,
      score: this.scores[p.id] || 0,
      isHost: !!p.isHost,
      isBot: !!p.isBot,
    }));
  }

  _orderedPids() {
    return this.players.map((p) => p.id);
  }

  startGame() {
    this.state = "lobby";
    this.roundNumber = 0;
    this.assignmentOffset = 0;
    this.history = [];
    this.scores = { p1: 0, b1: 0, b2: 0 };
    this.resetRoundState();
    return this.startRound();
  }

  startRound() {
    this.state = "drafting";
    this.roundNumber += 1;
    this.resetRoundState();
    this.draftDeadline = Date.now() + DRAFT_COUNTDOWN * 1000;
    const attrs = ATTRIBUTE_ORDER;
    this._orderedPids().forEach((pid, i) => {
      const attr = attrs[(i + this.assignmentOffset) % attrs.length];
      this.assignments[pid] = attr;
      this.draftOptions[pid] = sampleOptions(attr, DRAFT_OPTIONS);
      this.draftRefreshesLeft[pid] = attr === "country" || attr === "position" || attr === "club" ? 3 : 0;
    });
    this._autoSelectBots();
    return true;
  }

  _autoSelectBots() {
    for (const p of this.players) {
      if (!p.isBot) continue;
      if (this.selections[p.id]) continue;
      const attr = this.assignments[p.id];
      const options = this.draftOptions[p.id] || [];
      const choice = pickBotOption(attr, options);
      if (choice != null) this.selections[p.id] = choice;
    }
  }

  allSelected() {
    return this._orderedPids().every((pid) => this.selections[pid] != null);
  }

  submitSelection(pid, value) {
    if (this.state !== "drafting") return { ok: false, error: "Not in drafting phase" };
    if (!this.assignments[pid]) return { ok: false, error: "Not in this round" };
    if (this.selections[pid] != null) return { ok: false, error: "Already selected" };
    const attr = this.assignments[pid];
    const options = this.draftOptions[pid] || [];
    if (attr === "club") {
      const target = clubId(value);
      const match = options.find((o) => clubId(o) === target);
      if (!match) return { ok: false, error: "Invalid selection" };
      this.selections[pid] = match;
      return { ok: true };
    }
    if (!options.includes(value)) return { ok: false, error: "Invalid selection" };
    this.selections[pid] = value;
    return { ok: true };
  }

  autoSelectMissing() {
    let changed = false;
    for (const pid of this._orderedPids()) {
      if (this.selections[pid] != null) continue;
      let options = this.draftOptions[pid] || [];
      const attr = this.assignments[pid];
      if (!options.length && attr) {
        options = sampleOptions(attr, DRAFT_OPTIONS);
        this.draftOptions[pid] = options;
      }
      const choice = pickBotOption(attr, options);
      if (choice != null) {
        this.selections[pid] = choice;
        changed = true;
      }
    }
    return changed;
  }

  refreshDraftOptions(pid) {
    if (this.state !== "drafting") return { ok: false, error: "Not in drafting phase", options: null, refreshesLeft: 0 };
    if (!this.assignments[pid]) return { ok: false, error: "Not in this round", options: null, refreshesLeft: 0 };
    if (this.selections[pid] != null) return { ok: false, error: "Already selected", options: null, refreshesLeft: 0 };
    const attr = this.assignments[pid];
    if (!(attr === "country" || attr === "position" || attr === "club")) {
      return { ok: false, error: "Refresh not available for this attribute", options: null, refreshesLeft: 0 };
    }
    const left = this.draftRefreshesLeft[pid] || 0;
    if (left <= 0) return { ok: false, error: "No refreshes left", options: null, refreshesLeft: 0 };
    const options = sampleOptions(attr, DRAFT_OPTIONS);
    this.draftOptions[pid] = options;
    this.draftRefreshesLeft[pid] = left - 1;
    return { ok: true, options, refreshesLeft: this.draftRefreshesLeft[pid] };
  }

  currentConstraints() {
    const out = {};
    for (const [pid, attr] of Object.entries(this.assignments)) {
      if (this.selections[pid] != null) out[attr] = this.selections[pid];
    }
    return out;
  }

  startGuessing() {
    if (this.state !== "drafting") return false;
    this.state = "guessing";
    this.guesses = {};
    this.guessDeadline = Date.now() + GUESS_COUNTDOWN * 1000;
    this._autoGuessBots();
    return true;
  }

  _autoGuessBots() {
    const constraints = this.currentConstraints();
    for (const p of this.players) {
      if (!p.isBot) continue;
      if (this.guesses[p.id]) continue;
      this.guesses[p.id] = { text: bestGuessForConstraints(constraints), submitted_at: Date.now() };
    }
  }

  allGuessed() {
    return this._orderedPids().every((pid) => this.guesses[pid] != null);
  }

  submitGuess(pid, text) {
    if (this.state !== "guessing") return { ok: false, error: "Not in guessing phase" };
    if (this.guesses[pid]) return { ok: false, error: "Already guessed" };
    const guessText = String(text || "").trim();
    if (!guessText) return { ok: false, error: "Guess cannot be empty" };
    this.guesses[pid] = { text: guessText, submitted_at: Date.now() };
    return { ok: true };
  }

  _scoreGuess(guessText, constraints) {
    const matches = findPlayerMatches(guessText);
    if (!matches.length) {
      return {
        guess: guessText,
        matched_player: null,
        breakdown: { country: false, position: false, club: false },
        points: 0,
      };
    }
    let best = null;
    for (const player of matches) {
      const clubs = (player.clubs || []).map(clubId).filter(Boolean);
      const breakdown = {
        country: player.country === constraints.country,
        position: player.position === constraints.position,
        club: clubMatches(constraints.club, clubs),
      };
      const points = (breakdown.country ? 1 : 0) + (breakdown.position ? 1 : 0) + (breakdown.club ? 1 : 0);
      const cand = { points, clubHistoryLen: new Set(clubs).size, player, breakdown };
      if (!best || cand.points > best.points || (cand.points === best.points && cand.clubHistoryLen > best.clubHistoryLen)) {
        best = cand;
      }
    }
    const { player, breakdown, points } = best;
    return {
      guess: guessText,
      matched_player: {
        player_id: player.player_id,
        name: player.name,
        country: player.country,
        position: player.position,
      },
      breakdown,
      points,
    };
  }

  finalizeRound() {
    if (this.state !== "guessing") return null;
    const constraints = this.currentConstraints();
    const perPlayer = {};
    for (const pid of this._orderedPids()) {
      const guessInfo = this.guesses[pid] || { text: "" };
      const scored = this._scoreGuess(guessInfo.text || "", constraints);
      const points = scored.points || 0;
      this.scores[pid] = (this.scores[pid] || 0) + points;
      perPlayer[pid] = {
        playerId: pid,
        name: (this.players.find((p) => p.id === pid) || {}).name || "?",
        ...scored,
        totalScore: this.scores[pid],
      };
    }

    let winnerId = null;
    let draw = false;
    const vals = Object.values(this.scores);
    const maxScore = vals.length ? Math.max(...vals) : 0;
    let gameOver = false;
    if (maxScore >= WIN_SCORE) {
      const reached = this._orderedPids().filter((pid) => (this.scores[pid] || 0) >= WIN_SCORE);
      if (reached.length >= 2) {
        draw = true;
      } else {
        const candidates = this._orderedPids().filter((pid) => (this.scores[pid] || 0) === maxScore && (this.scores[pid] || 0) >= WIN_SCORE);
        candidates.sort();
        winnerId = candidates[0] || null;
      }
      gameOver = true;
    }

    this.roundResult = {
      round: this.roundNumber,
      constraints,
      assignments: Object.fromEntries(
        Object.entries(this.assignments).map(([pid, attr]) => [pid, { attribute: attr, value: this.selections[pid] }])
      ),
      results: this._orderedPids().map((pid) => perPlayer[pid]).filter(Boolean),
      standings: this.playerList(),
      winnerId,
      draw,
      gameOver,
    };
    this.history.push(this.roundResult);

    if (gameOver) {
      this.state = "game_over";
    } else {
      this.state = "result";
      this.assignmentOffset = (this.assignmentOffset + 1) % ATTRIBUTE_ORDER.length;
    }
    return this.roundResult;
  }

  draftSecondsLeft() {
    if (!this.draftDeadline) return 0;
    return Math.max(0, Math.ceil((this.draftDeadline - Date.now()) / 1000));
  }

  guessSecondsLeft() {
    if (!this.guessDeadline) return 0;
    return Math.max(0, Math.ceil((this.guessDeadline - Date.now()) / 1000));
  }
}
