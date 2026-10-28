// Davz Japan · Worker Cloudflare
// Sert le site (dossier site/) et trois petites routes qui lisent le site officiel à la demande :
//   /api/live                  scores des matchs du jour (toutes compétitions)
//   /api/match/:comp/:y/:no    détail d'un match (buts, cartons, remplacements, compositions)
//   /api/player/:id            carrière d'un joueur
const JL = "https://www.jleague.jp";
const UA = { "User-Agent": "Mozilla/5.0 (DavzJapan personal app)", "Accept-Language": "en" };
const COMPS = { j1: "J1", j2: "J2", j3: "J3", leaguecup: "LEVAIN", acle: "ACLE", acl2: "ACL2" };

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(req);
    try {
      let m;
      if (url.pathname === "/api/live") return cached(req, ctx, 45, () => live());
      if ((m = url.pathname.match(/^\/api\/match\/([a-z0-9]+)\/(\d{4})\/(\d+)\/?$/))) return cached(req, ctx, null, () => match(m[1], m[2], m[3]));
      if ((m = url.pathname.match(/^\/api\/player\/(\d+)\/?$/))) return cached(req, ctx, 86400, () => player(m[1]));
      if ((m = url.pathname.match(/^\/api\/espn\/(scoreboard|summary)$/))) return cached(req, ctx, 60, () => espn(m[1], url.searchParams));
      return json({ error: "not found" }, 404);
    } catch (e) {
      return json({ error: String(e && e.message || e) }, 502);
    }
  },
};

function json(data, status = 200, maxAge = 0) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": maxAge ? `public, max-age=${maxAge}` : "no-store" },
  });
}

async function cached(req, ctx, ttl, make) {
  const cache = caches.default;
  const key = new Request(new URL(req.url).toString(), { method: "GET" });
  const hit = await cache.match(key);
  if (hit) return hit;
  const data = await make();
  const age = ttl ?? data._ttl ?? 60;
  delete data._ttl;
  const res = json(data, 200, age);
  ctx.waitUntil(cache.put(key, res.clone()));
  return res;
}

async function getText(u) {
  const r = await fetch(u, { headers: UA, cf: { cacheTtl: 30 } });
  if (!r.ok) throw new Error(`${u} → ${r.status}`);
  return r.text();
}

// ---------- Next.js payload ----------
function payload(html) {
  const re = /self\.__next_f\.push\(\[1,"(.*?)"\]\)<\/script>/gs;
  let out = "", m;
  while ((m = re.exec(html))) {
    try { out += JSON.parse('"' + m[1] + '"'); } catch { out += m[1]; }
  }
  return out;
}
function grab(p, key, starts = "", from = 0) {
  const i = p.indexOf(`"${key}":${starts}`, from);
  if (i < 0) return null;
  const j = i + key.length + 3, op = p[j], cl = op === "[" ? "]" : op === "{" ? "}" : null;
  if (!cl) return null;
  let d = 0, ins = false, esc = false;
  for (let k = j; k < p.length; k++) {
    const c = p[k];
    if (ins) { if (esc) esc = false; else if (c === "\\") esc = true; else if (c === '"') ins = false; }
    else if (c === '"') ins = true;
    else if (c === op) d++;
    else if (c === cl && --d === 0) { try { return JSON.parse(p.slice(j, k + 1)); } catch { return null; } }
  }
  return null;
}
function nice(n) {
  if (!n) return n;
  const w = n.split(" ");
  const caps = w.filter(x => x === x.toUpperCase() || !/[a-z]/i.test(x));
  const rest = w.filter(x => !caps.includes(x));
  const t = s => s.split("-").map(p => p.slice(0, 1).toUpperCase() + p.slice(1).toLowerCase()).join("-");
  return rest.length && caps.length ? rest.join(" ") + " " + caps.map(t).join(" ") : w.map(t).join(" ");
}

// ---------- live ----------
function jstDate(offsetDays = 0) {
  const d = new Date(Date.now() + 9 * 3600e3 + offsetDays * 86400e3);
  return d.toISOString().slice(0, 10);
}
function parseBlocks(html) {
  const body = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, "");
  const re = /<div class="(m-schedule [^"]*)"[^>]*?id="(\d{10})"/g;
  const starts = [];
  let m;
  while ((m = re.exec(body))) starts.push({ i: m.index, cls: m[1], id: m[2] });
  const out = [];
  starts.forEach((s, k) => {
    const blk = body.slice(s.i, k + 1 < starts.length ? starts[k + 1].i : s.i + 20000);
    const href = blk.match(/\/match\/([a-z0-9]+)\/(\d{4})\/(\d+)/);
    if (!href) return;
    const scores = [...blk.matchAll(/m-schedule__score[^"]*"[^>]*>(\d+)</g)].map(x => +x[1]);
    const over = s.cls.includes("m-schedule--game-over");
    const stat = (blk.match(/m-schedule__(?:game-over-text|status|live-text|match-status)[^"]*"[^>]*>([^<]{1,40})</) || [])[1] || "";
    const st = over ? "post" : scores.length === 2 ? "in" : "pre";
    out.push({ id: `${href[1]}-${href[2]}-${href[3]}`, lg: COMPS[href[1]] || href[1].toUpperCase(), st, hs: st === "pre" ? null : scores[0], as: st === "pre" ? null : scores[1], clock: st === "in" ? stat.trim() : "" });
  });
  return out;
}
async function live() {
  const days = [jstDate(-1), jstDate(0)];
  const jobs = Object.keys(COMPS).map(c => getText(`${JL}/en/${c}/match/?startdate=${days[0]}&enddate=${days[1]}`).then(parseBlocks).catch(() => []));
  const all = (await Promise.all(jobs)).flat();
  const seen = new Set();
  return { at: new Date().toISOString(), matches: all.filter(x => !seen.has(x.id) && seen.add(x.id)) };
}

// ---------- match ----------
const PERIOD = { "First Half": 0, "Second Half": 45, "Extra First Half": 90, "Extra Second Half": 105, "Penalty Shootout": 120 };
const TYPE = { "goal": "Goal", "own-goal": "Own Goal", "penalty-goal": "Penalty - Scored", "yellow-card": "Yellow Card", "red-card": "Red Card", "yellow-yellow-red-card": "Red Card" };
function pidOf(p) { return (p.legacyPlayerPhotoLookup && p.legacyPlayerPhotoLookup.playerId) || ((p.href || "").match(/player\/(\d+)/) || [])[1] || null; }

async function match(comp, year, no) {
  const p = payload(await getText(`${JL}/en/match/${comp}/${year}/${no}/`));
  const home = grab(p, "homeTeam", '{"teamId"') || {};
  const away = grab(p, "awayTeam", '{"teamId"') || {};
  const stadium = grab(p, "stadium", '{"name"') || {};
  const evs = (grab(p, "events", '[{"period"') || []).slice().reverse();
  const ev = [];
  for (const e of evs) {
    const base = PERIOD[e.period] ?? 0;
    const clock = `${base + (e.time || 0)}'${e.extraTime ? "+" + e.extraTime : ""}`;
    for (const side of ["home", "away"]) {
      const list = e[side + "Players"] || [];
      const ins = list.filter(x => x.eventType === "sub-in"), outs = list.filter(x => x.eventType === "sub-out");
      ins.forEach((x, i) => ev.push([clock, "Substitution", side[0], [nice(x.name), nice(outs[i] && outs[i].name)], [pidOf(x), outs[i] && pidOf(outs[i])]]));
      list.filter(x => TYPE[x.eventType]).forEach(x => ev.push([clock, TYPE[x.eventType], side[0], [nice(x.name)], [pidOf(x)]]));
    }
  }
  // compositions : seconde apparition de homeTeam/awayTeam, avec "teamName" et "players"
  const lu = {};
  for (const [k, side] of [["homeTeam", "h"], ["awayTeam", "a"]]) {
    const t = grab(p, k, '{"teamName"');
    if (!t || !t.players) continue;
    const order = { GK: 0, DF: 1, MF: 2, FW: 3 };
    const xi = t.players.map(x => { const [pos, n] = (x.position || "").split(" "); return [n || "", nice(x.name), pos, 0, pidOf(x)]; })
      .sort((a, b) => (order[a[2]] ?? 9) - (order[b[2]] ?? 9));
    xi.forEach((x, i) => (x[3] = String(i + 1)));
    const cnt = ["DF", "MF", "FW"].map(q => xi.filter(x => x[2] === q).length).filter(Boolean);
    const subs = (t.substitutes || t.bench || t.benchPlayers || []).map(x => { const [pos, n] = (x.position || "").split(" "); return [n || "", nice(x.name), pos, 0, pidOf(x)]; });
    lu[side] = { f: cnt.join("-"), xi, sub: subs };
  }
  const over = /Full Time|試合終了/.test(p.slice(0, 200000)) && evs.length > 0;
  const status = home.score != null && away.score != null ? (over ? "post" : "in") : "pre";
  return {
    _ttl: status === "post" ? 86400 : 60,
    st: status, hs: home.score ?? null, as: away.score ?? null,
    sc: { h: (home.playerScoreList || []).map(x => [nice(x.name), x.scoreTime, !!x.ownGoal]), a: (away.playerScoreList || []).map(x => [nice(x.name), x.scoreTime, !!x.ownGoal]) },
    ev, lu,
    ven: stadium.name || null, att: stadium.numberOfPeople || null, wx: stadium.weather || null, temp: stadium.temperature || null,
  };
}

// ---------- player ----------
async function player(id) {
  const p = payload(await getText(`${JL}/en/player/${id}/`));
  const car = grab(p, "playerCareer") || [];
  car.forEach(r => {
    if (typeof r.club === "string") {
      const m = r.club.match(/playerCareer:(\d+):club/);
      r.club = m ? car[+m[1]].club : {};
    }
  });
  const info = grab(p, "information", '{"avatarPc"') || {};
  return {
    photo: info.avatarPc || null,
    car: car.map(r => [r.season && r.season.label, (r.club || {}).name, (r.club || {}).tournamentName, (r.league || {}).participation, (r.league || {}).goal, (r.leaguecup || {}).participation, (r.leaguecup || {}).goal]),
  };
}

// ---------- ESPN (statistiques des matchs de J1), relayé pour éviter le blocage du navigateur ----------
async function espn(kind, q) {
  const qs = kind === "scoreboard" ? `dates=${(q.get("dates") || "").replace(/\D/g, "")}` : `event=${(q.get("event") || "").replace(/\D/g, "")}`;
  const r = await fetch(`https://site.api.espn.com/apis/site/v2/sports/soccer/jpn.1/${kind}?${qs}`, { headers: UA });
  if (!r.ok) throw new Error("espn " + r.status);
  const d = await r.json();
  if (kind === "scoreboard") return { events: (d.events || []).map(e => ({ id: e.id, ids: e.competitions[0].competitors.map(c => c.team.id) })) };
  return { teams: (d.boxscore && d.boxscore.teams || []).map(t => ({ id: t.team.id, stats: (t.statistics || []).map(s => [s.name, s.displayValue]) })) };
}
