"""Outils partagés : téléchargement poli, lecture des données Next.js de jleague.jp, noms."""
import json, re, time, urllib.request, urllib.error

UA = {"User-Agent": "Mozilla/5.0 (DavzJapan personal app)", "Accept-Language": "en"}
JL = "https://www.jleague.jp"


def get(url, tries=3, pause=0.25, binary=False):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
                data = r.read()
            time.sleep(pause)
            return data if binary else data.decode("utf8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def payload(html):
    """Concatène les morceaux self.__next_f.push([1,"..."]) en texte lisible."""
    parts = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', html, flags=re.S)
    out = []
    for p in parts:
        try:
            out.append(json.loads('"' + p + '"'))
        except Exception:  # noqa: BLE001
            out.append(p.encode().decode("unicode_escape", "ignore"))
    return "".join(out)


def grab(p, key, starts="", start=0):
    """Valeur JSON (objet ou tableau) qui suit "key":starts, trouvée par appariement des crochets."""
    i = p.find('"%s":%s' % (key, starts), start)
    if i < 0:
        return None
    j = i + len(key) + 3
    op = p[j]
    cl = {"[": "]", "{": "}"}.get(op)
    if not cl:
        return None
    depth = 0
    ins = esc = False
    for k in range(j, len(p)):
        c = p[k]
        if ins:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                ins = False
        elif c == '"':
            ins = True
        elif c == op:
            depth += 1
        elif c == cl:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(p[j:k + 1])
                except Exception:  # noqa: BLE001
                    return None
    return None


def nice(n):
    """'NAKATANI Shinnosuke' -> 'Shinnosuke Nakatani' ; 'LEO CEARA' -> 'Leo Ceara'."""
    if not n:
        return n
    w = n.split()
    caps = [x for x in w if x.isupper() or not any(ch.isalpha() for ch in x)]
    rest = [x for x in w if x not in caps]
    t = lambda s: "-".join(p[:1].upper() + p[1:].lower() for p in s.split("-"))
    if rest and caps:
        return " ".join(rest) + " " + " ".join(t(x) for x in caps)
    return " ".join(t(x) for x in w)


def tidy_club(n):
    keep = {"FC", "SC", "AC", "RB", "MYFC", "F.C.", "S.C."}
    return " ".join(w if (w in keep or not w.isupper() or len(w) <= 2) else w.capitalize() for w in (n or "").split()).replace("･", "·")


def norm(x):
    x = (x or "").lower().replace("･", "").replace("·", "")
    x = re.sub(r"\b(fc|f\.c\.|sc|s\.c\.)\b", "", x)
    return re.sub(r"[^a-z0-9]", "", x)
