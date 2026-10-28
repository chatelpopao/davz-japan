"""Davz Japan · récupère les données officielles et écrit site/data/app.json.

Usage : python pipeline/build.py [--full]
Chaque bloc a sa propre fréquence ; les résultats précédents sont gardés dans .cache/
pour ne retélécharger que ce qui a vieilli. --full force tout.
"""
import datetime as dt
import io
import json
import os
import re
import sys
import time

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(__file__))
from common import JL, get, grab, nice, norm, payload, tidy_club  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
OUT = os.path.join(ROOT, "site", "data")
IMG = os.path.join(ROOT, "site", "img", "clubs")
for d in (CACHE, OUT, IMG):
    os.makedirs(d, exist_ok=True)

FULL = "--full" in sys.argv
NOW = time.time()
JST = dt.timezone(dt.timedelta(hours=9))
TODAY_JST = dt.datetime.now(JST).date()
SEASON = "2026-27"
SEASON_START, SEASON_END = dt.date(2026, 7, 1), dt.date(2027, 6, 30)
COMPS = {"j1": "J1", "j2": "J2", "j3": "J3", "leaguecup": "LEVAIN", "acle": "ACLE", "acl2": "ACL2"}


def cache_load(name, default=None):
    p = os.path.join(CACHE, name + ".json")
    if os.path.exists(p):
        with open(p, encoding="utf8") as f:
            return json.load(f)
    return default


def cache_save(name, data):
    with open(os.path.join(CACHE, name + ".json"), "w", encoding="utf8") as f:
        json.dump(data, f, ensure_ascii=False)


STATE = cache_load("_state", {})


def due(name, hours):
    return FULL or NOW - STATE.get(name, 0) > hours * 3600


def done(name):
    STATE[name] = NOW
    cache_save("_state", STATE)


def step(name, hours, fn):
    if not due(name, hours):
        print(f"· {name}: à jour")
        return
    t = time.time()
    try:
        fn()
        done(name)
        print(f"✓ {name} ({time.time() - t:.0f}s)")
    except Exception as e:  # noqa: BLE001
        print(f"✗ {name}: {e}")


# ------------------------------------------------------------------ clubs
def club_slugs():
    p = payload(get(f"{JL}/en/j1/standings/"))
    slugs = []
    for s in re.findall(r'\["\$","li","([a-z0-9]+)",\{"className":"o-footer__clubs-item"', p):
        if s not in slugs:
            slugs.append(s)
    fix = {"kusatsu": "gunma"}
    return [fix.get(s, s) for s in slugs[:60]]


def emblem(slug, url):
    try:
        import cairosvg
        from PIL import Image
        raw = get(JL + url, binary=True)
        png = cairosvg.svg2png(bytestring=raw, output_width=160) if url.endswith(".svg") else raw
        im = Image.open(io.BytesIO(png)).convert("RGBA")
        bb = im.getbbox()
        if bb:
            im = im.crop(bb)
        im.thumbnail((128, 128))
        im.save(os.path.join(IMG, slug + ".webp"), "WEBP", quality=88, method=6)
    except Exception as e:  # noqa: BLE001
        print("  emblème", slug, e)


def do_clubs():
    clubs = {}
    for slug in club_slugs():
        p = payload(get(f"{JL}/en/club/{slug}/"))
        basic = grab(p, "clubBasicInformation") or {}
        info = grab(p, "clubInformation") or {}
        prof = grab(p, "clubDetailProfile") or {}
        col = re.search(r'"primaryColor":"(#[0-9a-fA-F]{6})","secondaryColor":"(#[0-9a-fA-F]{6})"', p)
        pl = payload(get(f"{JL}/en/club/{slug}/player/"))
        players = grab(pl, "players", '[{"playerId"') or []
        lg = (basic.get("teamLeague") or "").upper()
        clubs[slug] = {
            "n": tidy_club(basic.get("teamNameEn") or slug), "ja": basic.get("teamNameJa"), "lg": lg,
            "c1": col.group(1) if col else "#334455", "c2": col.group(2) if col else "#ffffff",
            "st": info.get("stadiumName"), "cap": info.get("capacity"), "coach": nice(info.get("staffName")),
            "site": info.get("homepageUrlEn") or info.get("homepageUrl"),
            "rec": [info.get("win"), info.get("draw"), info.get("lose"), info.get("ranking")],
            "fd": prof.get("foundedYear"), "ht": prof.get("homeTown"), "tc": prof.get("teamColor"),
            "p": [[x.get("playerId"), nice(x.get("playerNameEn")), x.get("playerName"), x.get("uniformNo"), x.get("position"),
                   (x.get("birthday") or "")[2:12], x.get("height"), x.get("weight"), x.get("totalGameCount"), x.get("totalGoalCount")]
                  for x in players],
        }
        if basic.get("emblemUrl") and (FULL or not os.path.exists(os.path.join(IMG, slug + ".webp"))):
            emblem(slug, basic["emblemUrl"])
        print(f"  {lg} {slug} {len(players)} joueurs")
    if len(clubs) >= 50:
        cache_save("clubs", clubs)


# ------------------------------------------------------------------ fixtures
DATE_RE = re.compile(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), (\d{1,2}) ([A-Z][a-z]{2}) (\d{4}) \(JST\)")
MON = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def parse_fixtures(html):
    body = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S)
    marks = [(m.start(), dt.date(int(m.group(3)), MON[m.group(2)], int(m.group(1)))) for m in DATE_RE.finditer(body)]
    soup = BeautifulSoup(body, "lxml")
    out = []
    for el in soup.select("div.m-schedule[id]"):
        gid = el["id"]
        pos = body.find(f'id="{gid}"')
        day = None
        for mpos, d in marks:
            if mpos < pos:
                day = d
            else:
                break
        a = el.select_one("a[href*='/match/']")
        href = a["href"] if a else ""
        m = re.search(r"/match/([a-z0-9]+)/(\d{4})/(\d+)", href)
        if not m or not day:
            continue
        comp = m.group(1)
        names = [x.get_text(strip=True) for x in el.select(".m-schedule__team-name[data-media=pc]")]
        codes = [x.get_text(strip=True) for x in el.select(".m-schedule__team-name[data-media=sp]")]
        scores = [x.get_text(strip=True) for x in el.select(".m-schedule__score")]
        cls = el.get("class", [])
        over = "m-schedule--game-over" in cls
        tt = el.select_one(".m-schedule__time-text")
        status = el.select_one(".m-schedule__game-over-text, .m-schedule__status")
        venue = el.select_one(".m-schedule__info-stadium[data-media=pc]")
        tv = [x.get_text(strip=True) for x in el.select(".m-schedule__info-platform-text")]
        if len(names) < 2:
            continue
        st = "post" if over else ("in" if len(scores) == 2 and scores[0].isdigit() else "pre")
        out.append({
            "gid": gid, "comp": comp, "year": m.group(2), "no": m.group(3), "day": day.isoformat(),
            "time": tt.get_text(strip=True) if tt and re.match(r"^\d{1,2}:\d\d$", tt.get_text(strip=True)) else None,
            "names": names[:2], "codes": codes[:2],
            "hs": int(scores[0]) if st != "pre" and len(scores) == 2 and scores[0].isdigit() else None,
            "as": int(scores[1]) if st != "pre" and len(scores) == 2 and scores[1].isdigit() else None,
            "st": st, "status": status.get_text(" ", strip=True) if status else "",
            "ven": venue.get_text(strip=True) if venue else None, "jtv": tv,
        })
    return out


def months(a, b):
    d = dt.date(a.year, a.month, 1)
    while d <= b:
        nxt = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        yield d, min(nxt - dt.timedelta(days=1), b)
        d = nxt


def do_fixtures(full):
    fx = {x["gid"]: x for x in cache_load("fixtures", [])}
    if full:
        ranges = list(months(SEASON_START, SEASON_END))
    else:
        ranges = [(TODAY_JST - dt.timedelta(days=4), TODAY_JST + dt.timedelta(days=7))]
    for comp in COMPS:
        for a, b in ranges:
            try:
                rows = parse_fixtures(get(f"{JL}/en/{comp}/match/?startdate={a}&enddate={b}"))
            except Exception as e:  # noqa: BLE001
                print("  ", comp, a, e)
                continue
            for r in rows:
                fx[r["gid"]] = r
    cache_save("fixtures", list(fx.values()))
    print(f"  {len(fx)} matchs")


def do_kickoffs():
    """Heures exactes de coup d'envoi via les calendriers iCal officiels des clubs."""
    ko = cache_load("kickoffs", {})
    for slug in (cache_load("clubs", {}) or {}):
        try:
            ics = get(f"{JL}/api/club-calendar/{slug}/")
        except Exception:  # noqa: BLE001
            continue
        for uid, start in re.findall(r"UID:jleague-match-(\d+)@[^\n]*\n(?:[^\n]*\n)*?DTSTART;TZID=Asia/Tokyo:(\d{8}T\d{6})", ics):
            ko[uid] = start
    cache_save("kickoffs", ko)


# ------------------------------------------------------------------ standings & stats
def do_standings():
    out = {}
    for lg in ("j1", "j2", "j3"):
        p = payload(get(f"{JL}/en/{lg}/standings/"))
        rows = []
        for r in grab(p, "standingList") or []:
            m = re.search(r"/club/([a-z0-9]+)", (r.get("club") or {}).get("href", ""))
            if not m:
                continue
            form = [{"win": "W", "draw": "D", "loss": "L"}.get(g.get("state"), "") for g in r.get("pastGames", [])]
            rows.append([m.group(1), r["ranking"]["value"], r.get("match"), r.get("win"), r.get("draw"), r.get("loss"),
                         r.get("goalScored"), r.get("goalLost"), r.get("point"), "".join(form), r["ranking"].get("borderLine")])
        out[lg.upper()] = rows
    cache_save("standings", out)


PSTATS = "score assist shoot chance_create clean_sheet duels_won distance sprint top_speed".split()
CSTATS = "score lost score_per_game lost_per_game clean_sheet ball_rate shoot_per_game pass_count_per_game distance_per_game sprint_per_game".split()


def rankings(lg, kind, st):
    p = payload(get(f"{JL}/en/{lg}/stats/{kind}/{SEASON}/{st}/search-list/"))
    for blk in grab(p, "rankingList") or []:
        if (blk.get("stats") or {}).get("value") == st:
            return blk.get("data", [])
    return []


def do_stats():
    pl, cl = {}, {}
    for lg in ("j1", "j2", "j3"):
        L = lg.upper()
        pl[L], cl[L] = {}, {}
        for st in PSTATS:
            rows = []
            for r in rankings(lg, "player", st)[:30]:
                pid = re.search(r"/player/(\d+)", r.get("href", ""))
                rows.append([r.get("rank"), pid.group(1) if pid else None, (r.get("club") or {}).get("code"), nice(r.get("playerName")), r.get("score")])
            if rows:
                pl[L][st] = rows
        for st in CSTATS:
            rows = []
            for r in rankings(lg, "club", st):
                c = r.get("club") or {}
                rows.append([c.get("code"), c.get("fullName") or c.get("name"), r.get("score", r.get("value"))])
            if rows:
                cl[L][st] = rows
    cache_save("pstats", pl)
    cache_save("cstats", cl)


# ------------------------------------------------------------------ media
def do_videos():
    s = get("https://www.youtube.com/@JLEAGUEInternational/videos")
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", s, re.S)
    d = json.loads(m.group(1))
    out = []

    def walk(o):
        if isinstance(o, dict):
            if "lockupViewModel" in o:
                lv = o["lockupViewModel"]
                md = lv.get("metadata", {}).get("lockupMetadataViewModel", {})
                t = md.get("title", {}).get("content")
                parts = [p.get("text", {}).get("content") for r in md.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", []) for p in r.get("metadataParts", [])]
                dur = next((x for x in re.findall(r'"text": ?"(\d+:\d\d(?::\d\d)?)"', json.dumps(lv))), None)
                out.append({"id": lv.get("contentId"), "t": t, "ago": next((x for x in parts if x and "ago" in x), ""), "dur": dur})
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d)
    seen, vids = set(), []
    for v in out:
        if v["id"] and v["id"] not in seen:
            seen.add(v["id"])
            vids.append(v)
    if vids:
        cache_save("videos", vids[:40])


def do_news():
    known = {a["id"]: a for a in cache_load("news", [])}
    top = max([int(k) for k in known] or [0])
    latest = top
    for path in ("", "j1/", "j2/", "j3/", "acle/", "acl2/", "leaguecup/"):
        try:
            s = get(f"https://www.jleague.co/en/{path}news/")
            ids = [int(x) for x in re.findall(r"/en/news/article/(\d+)/", s)]
            if ids:
                latest = max(latest, max(ids))
        except Exception:  # noqa: BLE001
            pass
    start = max(top + 1, latest - 120) if top else latest - 120
    for i in range(start, latest + 1):
        try:
            s = get(f"{JL}/en/news/article/{i}/", tries=1)
        except Exception:  # noqa: BLE001
            continue
        t = re.search(r"<title>([^<]*)", s)
        title = (t.group(1) if t else "").replace(" | Official Website of J.LEAGUE", "").strip()
        if not title or "Page Not Found" in title or title.startswith("Official Website"):
            continue
        d = re.search(r"(\w{3}, \d{1,2} \w{3} \d{4}, \d\d:\d\d \(JST\))", s)
        known[str(i)] = {"id": str(i), "t": title, "d": d.group(1) if d else ""}
    items = sorted(known.values(), key=lambda a: -int(a["id"]))[:90]
    cache_save("news", items)


def do_tv():
    """Croise les matchs à venir avec le guide de Davz TV."""
    base = "https://muddy-glitter-8ba4.odinthor.workers.dev/data/"
    idx = json.loads(get(base + "index.json"))
    names = {}
    guide = {}
    for c in idx["categories"]:
        for ch in c["channels"]:
            names[ch["id"]] = (ch["name"], c.get("flag") or c["id"][:2])
        try:
            guide.update(json.loads(get(base + c["id"] + ".json")))
        except Exception:  # noqa: BLE001
            pass
    keep = {}
    pat = re.compile(r"j[\.\- ]?league|j1|afc|champions league elite|champions league two|levain|emperor|japan", re.I)
    for ch, progs in guide.items():
        for p in progs:
            txt = (p.get("t", "") + " " + p.get("d", ""))
            if pat.search(txt):
                keep.setdefault(ch, []).append({"s": p["s"], "e": p.get("e"), "t": txt[:400]})
    cache_save("tv", {"names": names, "progs": keep})


# ------------------------------------------------------------------ espn ids (J1 stats tab)
ESPN_ALIAS = {"tokyoverdy1969": "tokyov", "machidazelvia": "machida", "jefunitedichiharachiba": "chiba", "urawareddiamonds": "urawa",
              "yokohamafmarinos": "yokohamafm", "kyotosanga": "kyoto", "mitohollyhock": "mito"}


def do_espn():
    d = json.loads(get("https://site.api.espn.com/apis/site/v2/sports/soccer/jpn.1/teams"))
    clubs = cache_load("clubs", {})
    byn = {norm(c["n"]): s for s, c in clubs.items()}
    ids = {}
    for t in d["sports"][0]["leagues"][0]["teams"]:
        t = t["team"]
        k = norm(t["displayName"])
        s = byn.get(k) or ESPN_ALIAS.get(k) or next((v for kk, v in byn.items() if k in kk or kk in k), None)
        if s:
            ids[s] = t["id"]
    cache_save("espn", ids)


# ------------------------------------------------------------------ assemble
def assemble():
    clubs = cache_load("clubs", {})
    fixtures = cache_load("fixtures", [])
    ko = cache_load("kickoffs", {})
    espn = cache_load("espn", {})
    for s, e in espn.items():
        if s in clubs:
            clubs[s]["e"] = e
    byname = {norm(c["n"]): s for s, c in clubs.items()}
    foreign = {}
    codes = {}

    def slug_for(name, code):
        k = norm(name)
        if k in byname:
            return byname[k]
        s = next((v for kk, v in byname.items() if kk and (kk in k or k in kk)), None)
        if s:
            return s
        fs = "x_" + k
        foreign[fs] = {"n": tidy_club(name), "sh": code or name[:3].upper(), "lg": "OTHER", "c1": "#3A4560", "c2": "#ffffff", "p": [], "foreign": 1, "rec": [None] * 4}
        return fs

    matches = []
    for f in fixtures:
        h, a = slug_for(f["names"][0], f["codes"][0]), slug_for(f["names"][1], f["codes"][1])
        for s, c in ((h, f["codes"][0]), (a, f["codes"][1])):
            if c and s in clubs:
                codes.setdefault(s, c)
        lg = COMPS.get(f["comp"]) or {"emperor": "EMPEROR"}.get(f["comp"])
        if not lg:
            continue
        if lg in ("ACLE", "ACL2") and h.startswith("x_") and a.startswith("x_"):
            continue
        k = ko.get(f["gid"])
        tbc = False
        if f.get("time"):
            hh, mm = f["time"].split(":")
            when = dt.datetime.fromisoformat(f["day"]).replace(hour=int(hh), minute=int(mm), tzinfo=JST)
        elif k:
            when = dt.datetime.strptime(k, "%Y%m%dT%H%M%S").replace(tzinfo=JST)
        else:
            when = dt.datetime.fromisoformat(f["day"]).replace(hour=15, tzinfo=JST)
            tbc = True
        m = {"id": f"{f['comp']}-{f['year']}-{f['no']}", "lg": lg, "dt": when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
             "h": h, "a": a, "hs": f["hs"], "as": f["as"], "st": f["st"], "ven": f.get("ven")}
        if tbc and f["st"] == "pre":
            m["tbc"] = 1
        if f["st"] == "in" and f.get("status"):
            m["clock"] = f["status"]
        if f.get("jtv"):
            m["jtv"] = f["jtv"]
        matches.append(m)
    matches.sort(key=lambda m: m["dt"])
    for s, c in codes.items():
        clubs[s]["sh"] = c
    for s, c in clubs.items():
        c.setdefault("sh", norm(c["n"])[:3].upper())

    # TV
    tv = cache_load("tv", {"names": {}, "progs": {}})
    allc = {**clubs, **foreign}

    def words(s):
        n = allc[s]["n"]
        w = [x for x in re.split(r"[^A-Za-z]+", n) if len(x) > 3 and x.lower() not in ("united", "city", "club", "motors", "hyundai", "citizen")]
        return w[:2] or [n]
    now = time.time()
    for m in matches:
        if m["st"] == "post":
            continue
        k = dt.datetime.strptime(m["dt"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=dt.timezone.utc).timestamp()
        if k - now > 8 * 86400:
            continue
        hw, aw = words(m["h"]), words(m["a"])
        found = []
        for ch, progs in tv["progs"].items():
            for p in progs:
                low = p["t"].lower()
                if any(w.lower() in low for w in hw) and any(w.lower() in low for w in aw) and k - 3600 <= p["s"] <= k + 48 * 3600:
                    nm, fl = tv["names"].get(ch, [ch, ""])
                    found.append({"ch": nm, "fl": fl, "s": p["s"], "live": abs(p["s"] - k) <= 45 * 60})
        if found:
            found.sort(key=lambda x: (not x["live"], x["s"]))
            seen, ded = set(), []
            for t in found:
                key = (t["ch"], t["live"])
                if key not in seen:
                    seen.add(key)
                    ded.append(t)
            m["tv"] = ded[:4]

    # Tables
    std = cache_load("standings", {})
    tables = {L: [[r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10]] for r in rows if r[0] in clubs] for L, rows in std.items()}

    # Player & club stats
    pst = cache_load("pstats", {})
    pid2club = {p[0]: s for s, c in clubs.items() for p in c["p"]}
    stats = {L: {st: [[r[0], r[1], r[2] if r[2] in clubs else pid2club.get(r[1]), r[3], r[4]] for r in rows] for st, rows in cats.items()} for L, cats in pst.items()}
    cst = cache_load("cstats", {})
    team = {}
    for L, cats in cst.items():
        team[L] = {}
        for st, rows in cats.items():
            out = []
            for code, name, val in rows:
                s = code if code in clubs else byname.get(norm(name))
                if s and val is not None:
                    out.append([s, val])
            out.sort(key=lambda x: x[1] if st in ("lost", "lost_per_game") else -x[1])
            team[L][st] = out

    # Videos -> matchs
    vids = []
    names_sorted = sorted(((c["n"], s) for s, c in clubs.items()), key=lambda x: -len(x[0]))

    def find_club(txt):
        t = txt.lower().replace("･", "·")
        for n, s in names_sorted:
            if n.lower() in t:
                return s
        t2 = norm(txt)
        for n, s in names_sorted:
            if norm(n) and norm(n) in t2:
                return s
        return None
    for v in cache_load("videos", []):
        t = v["t"] or ""
        kind = "hl" if "HIGHLIGHTS" in t else "l20" if "Last 20" in t else "wk" if "Weekly" in t else "j2" if "Every Goal In J2" in t else "j3" if "Every Goal In J3" in t else "x"
        h = a = mid = None
        core = t
        if "|" in t and " vs " not in t.split("|")[0]:
            core = t.split("|")[1]
        if (" vs " in core or " v " in core) and "Throwback" not in t:
            left, right = re.split(r" vs | v ", core, maxsplit=1)
            h, a = find_club(left), find_club(right)
            mm = [m for m in matches if m["h"] == h and m["a"] == a and m["st"] == "post"]
            if mm:
                mid = mm[-1]["id"]
        title = re.sub(r"\s*\|\s*J\.League( \d{4}/\d\d)?\s*$", "", t).strip()
        vids.append({"id": v["id"], "t": title, "ago": v.get("ago", ""), "dur": v.get("dur"), "k": kind, "h": h, "a": a, "m": mid})

    # News tags
    toks = {}
    strip_ = lambda x: re.sub(r"^(FC|F\.C\.|S\.C\.|RB)\s|\s(FC|F\.C\.|SC)$", "", x)
    for s, c in clubs.items():
        w = strip_(c["n"]).lower().split()
        for t in {w[0], w[-1]}:
            toks.setdefault(t, set()).add(s)
    gen = {"united", "city", "club", "reds", "f.c.", "sc", "fc"}
    keys = {}
    for s, c in clubs.items():
        w = strip_(c["n"]).lower().split()
        k = {c["n"].lower()}
        if len(w) > 1:
            k.add(" ".join(w))
        for t in {w[0], w[-1]}:
            if len(toks[t]) == 1 and len(t) > 3 and t not in gen:
                k.add(t)
        keys[s] = k
    for s, extra in {"kusatsu": {"thespa", "gunma"}, "gunma": {"thespa"}, "yokohamafm": {"marinos"}, "tokyov": {"verdy"}, "cosaka": {"cerezo"}, "gosaka": {"gamba"}, "mito": {"hollyhock"}}.items():
        if s in keys:
            keys[s] |= extra
    news = []
    for n in cache_load("news", []):
        t = n["t"]
        tl = " " + re.sub(r"[^a-z0-9·. ]", " ", t.lower()) + " "
        cl = [s for s, k in keys.items() if any(re.search(r"(?<![a-z])" + re.escape(x) + r"(?![a-z])", tl) for x in k)]
        lg = next((L for L in ("J1", "J2", "J3") if f"{L} Matchweek" in t or f"{L} Match Week" in t), None)
        if not lg and ("ACL" in t or "Champions League" in t):
            lg = "ACLE"
        if not lg and "Levain" in t:
            lg = "LEVAIN"
        if not lg and cl:
            lg = clubs[cl[0]]["lg"]
        kind = "Summary" if "[Summary" in t else "Preview" if "[Preview" in t else "Injury" if "Injur" in t else "Transfer" if "Join" in t else "News"
        news.append({"id": n["id"], "t": t, "d": n["d"], "lg": lg, "c": cl, "k": kind})

    with open(os.path.join(ROOT, "pipeline", "static", "honours.json"), encoding="utf8") as f:
        honours = json.load(f)
    honours = {k: [x for x in v if x[1] and x[1] != "nan"] for k, v in honours.items()}

    app = {"updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "clubs": {**clubs, **foreign}, "tables": tables,
           "matches": matches, "stats": stats, "team": team, "honours": honours, "news": news, "videos": vids}
    with open(os.path.join(OUT, "app.json"), "w", encoding="utf8") as f:
        json.dump(app, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✓ app.json : {len(clubs)} clubs, {len(matches)} matchs, {len(news)} actus, {len(vids)} vidéos, "
          f"{os.path.getsize(os.path.join(OUT, 'app.json')) // 1024} Ko")


if __name__ == "__main__":
    step("clubs", 20, do_clubs)
    step("espn", 24 * 7, do_espn)
    step("fixtures_full", 6, lambda: do_fixtures(True))
    if not FULL:
        step("fixtures_window", 0, lambda: do_fixtures(False))
    step("kickoffs", 12, do_kickoffs)
    step("standings", 0.4, do_standings)
    step("stats", 6, do_stats)
    step("videos", 0.4, do_videos)
    step("news", 1, do_news)
    step("tv", 6, do_tv)
    assemble()
