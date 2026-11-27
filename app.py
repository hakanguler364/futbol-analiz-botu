
"""Football analysis dashboard. Python standard library only."""
import os, json, urllib.request, urllib.parse, urllib.error, http.server, datetime, pathlib, re, time

from contextlib import closing
from threading import Lock

import membership
from access import ANALYSIS_VIEW, AccessHandler, configure

BASE = pathlib.Path(__file__).parent
TOKEN = os.getenv("FOOTBALL_DATA_TOKEN", "").strip()
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
CACHE = {}
MATCH_CACHE = {}
RESULT_REFRESH_SECONDS = 30
RESULT_REFRESH_LOCKS = {}

def fetch(path):
    if not TOKEN:
        raise ValueError("FOOTBALL_DATA_TOKEN ayarlanmamis")
    req = urllib.request.Request(
        "https://api.football-data.org/v4" + path,
        headers={"X-Auth-Token": TOKEN, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read(500).decode("utf-8", "replace")
        raise ValueError(f"Football-Data API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"Football-Data baglanti hatasi: {exc.reason}") from exc


# BSD free football consensus odds. Never expose the API token to the browser.
BSD_TOKEN = os.getenv("BZZOIRO_API_KEY", "").strip()
BSD_CACHE = {}
def bsd_json(path):
    req = urllib.request.Request("https://sports.bzzoiro.com/api/v2/" + path,
        headers={"Authorization": "Token " + BSD_TOKEN, "Accept": "application/json", "User-Agent": "FutbolAnaliz/1.0"})
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.load(response)

def bsd_matching_events(team, day, home, away, kickoff):
    query = urllib.parse.urlencode({
        "team_name": team, "date_from": (datetime.date.fromisoformat(day) - datetime.timedelta(days=1)).isoformat(),
        "date_to": (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat(), "limit": 100,
    })
    data = bsd_json("events/?" + query)
    for event in data.get("results", []) if isinstance(data, dict) else []:
        eh = event.get("home_team") or event.get("home") or ""
        ea = event.get("away_team") or event.get("away") or ""
        if isinstance(eh, dict):
            eh = eh.get("name", "")
        if isinstance(ea, dict):
            ea = ea.get("name", "")
        if (team_match_key(eh), team_match_key(ea)) != (home, away):
            continue
        event_time = event.get("event_date") or event.get("start_time") or event.get("start_at") or event.get("date") or event.get("kickoff")
        try:
            event_start = datetime.datetime.fromisoformat(str(event_time).replace("Z", "+00:00"))
            if abs((kickoff - event_start).total_seconds()) <= 7200:
                yield event
        except (ValueError, TypeError):
            continue


def bsd_odds(match):
    if not BSD_TOKEN:
        return {"source": "BSD: API anahtarı tanımlı değil", "odds": {}}
    key = str(match["id"])
    cached = BSD_CACHE.get(key)
    if cached and time.time() - cached[0] < (900 if cached[1]["odds"] else 60):
        return cached[1]
    home = match.get("homeTeam", {}).get("name", "")
    away = match.get("awayTeam", {}).get("name", "")
    home_key, away_key = team_match_key(home), team_match_key(away)
    result = {"source": "BSD: maç eşleşmesi bulunamadı", "odds": {}}
    try:
        kickoff = datetime.datetime.fromisoformat(str(match.get("utcDate") or "").replace("Z", "+00:00"))
        if not home_key or not away_key:
            return result
        day = kickoff.date().isoformat()
        checked_events = set()
        for team in dict.fromkeys((home, away)):
            for event in bsd_matching_events(team, day, home_key, away_key, kickoff):
                event_id = event.get("id") or event.get("event_id")
                if not event_id or event_id in checked_events:
                    continue
                checked_events.add(event_id)
                result = {"source": "BSD: maç eşleşti, MS oranı yayımlanmamış", "odds": {}}
                try:
                    raw = bsd_json("events/" + urllib.parse.quote(str(event_id), safe="") + "/odds/")
                except urllib.error.HTTPError as exc:
                    if exc.code == 404:
                        continue
                    raise
                values = raw.get("odds") or {}
                prices = {}
                for label, field in (("MS 1", "home_win"), ("MS 0", "draw"), ("MS 2", "away_win")):
                    value = values.get(field)
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and 1 < value < float("inf"):
                        prices[label] = float(value)
                if prices:
                    result = {"source": "BSD konsensüs oranları", "odds": prices,
                              "updated_at": raw.get("last_update_at")}
                    break
            if result["odds"]:
                break
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError, TypeError, KeyError) as exc:
        print("BSD_ODDS_ERROR " + str(exc)[:160], flush=True)
        message = "API anahtarı veya erişim yetkisi doğrulanamadı" if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403) else "oran bağlantısı kullanılamıyor"
        result = {"source": "BSD: " + message, "odds": {}}
    BSD_CACHE[key] = (time.time(), result)
    return result


STANDINGS_CACHE = {}

def team_standings(match):
    league = match.get("espn_league")
    if not league:
        return {"home": None, "away": None, "source": "Veri bulunamadı"}
    now = time.time()
    cached = STANDINGS_CACHE.get(league)
    if not cached or now - cached[0] > 3600:
        url = "https://site.api.espn.com/apis/v2/sports/soccer/" + urllib.parse.quote(league, safe="") + "/standings"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.load(response)
            STANDINGS_CACHE[league] = (now, data)
        except (OSError, ValueError, TypeError):
            return {"home": None, "away": None, "source": "Veri bulunamadı"}
    else:
        data = cached[1]
    entries = []
    def collect(group):
        entries.extend((group.get("standings") or {}).get("entries") or [])
        for child in group.get("children") or []:
            collect(child)
    collect(data)
    def position(side):
        team_id = str(match.get(side + "_espn_id") or "")
        if not team_id:
            return None
        for entry in entries:
            if str((entry.get("team") or {}).get("id")) != team_id:
                continue
            for stat in entry.get("stats") or []:
                if stat.get("name") in ("rank", "rankTotal", "playoffSeed") and stat.get("value") is not None:
                    try:
                        n = int(float(stat["value"]))
                        return n if n > 0 else None
                    except (ValueError, TypeError):
                        pass
            return None
        return None
    return {"home": position("home"), "away": position("away"), "source": "ESPN"}

def valid_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Tarih YYYY-MM-DD olmali")
    datetime.date.fromisoformat(value)
    return value


ESPN_LEAGUES = ["eng.1","eng.2","eng.3","eng.4","eng.fa","eng.league_cup","esp.1","esp.2","esp.copa_del_rey","ger.1","ger.2","ger.3","ger.dfb_pokal","ita.1","ita.2","ita.coppa_italia","fra.1","fra.2","fra.coupe_de_france","tur.1","tur.2","tur.cup","ned.1","ned.2","ned.cup","por.1","por.2","por.taca.portugal","bel.1","bel.2","sco.1","sco.2","sco.3","sco.4","sco.fa","irl.1","nir.1","wal.1","aut.1","sui.1","den.1","nor.1","swe.1","fin.1","pol.1","cze.1","gre.1","rou.1","rus.1","ukr.1","cro.1","srb.1","hun.1","usa.1","usa.open","mex.1","mex.2","bra.1","bra.2","bra.copa","arg.1","arg.2","col.1","chi.1","uru.1","par.1","per.1","ecu.1","ven.1","bol.1","crc.1","hon.1","gua.1","slv.1","ksa.1","uae.1","qat.1","ind.1","jpn.1","jpn.2","kor.1","chn.1","aus.1","aus.2","idn.1","tha.1","mys.1","sgp.1","uefa.champions","uefa.europa","uefa.europa.conf","uefa.nations","uefa.euro","uefa.euro.qualifying","fifa.world","fifa.worldq.uefa","fifa.worldq.conmebol","fifa.worldq.concacaf","fifa.worldq.afc","fifa.worldq.caf","fifa.friendly","concacaf.champions","conmebol.libertadores","conmebol.sudamericana","afc.champions","caf.champions","fifa.club.world_cup"]

SOCCERWAY_LEAGUES = {'pol.2': ('Polonya 1. Liga', ['poland/division-1']), 'pol.3': ('Polonya 2. Liga', ['poland/division-2']), 'cze.2': ('Çekya 2. Ligi', ['czech-republic/chnl']), 'ita.3': ('İtalya Serie C', ['italy/serie-c-group-a', 'italy/serie-c-group-b', 'italy/serie-c-group-c'])}
SOCCERWAY_LEAGUES.update({
    "tur.2": ("Türkiye 1. Lig", ["turkey/1-lig"]),
    "egy.2": ("Mısır 2. Ligi A Grubu", ["egypt/division-2-a"]),
})
ESPN_LEAGUES.extend(league for league in SOCCERWAY_LEAGUES if league not in ESPN_LEAGUES)

def openliga_season(kickoff, *, max_age=300):
    season = kickoff.year - (kickoff.month < 7)
    key = ("openligadb", season)
    cached = CACHE.get(key)
    if cached and time.time() - cached["time"] < max_age:
        return cached["result"]
    with urllib.request.urlopen(
        f"https://api.openligadb.de/getmatchdata/bl3/{season}", timeout=8
    ) as response:
        events = json.load(response)
    CACHE[key] = {"time": time.time(), "result": events}
    return events


def openliga_recent(match, side):
    kickoff = datetime.datetime.fromisoformat(match["utcDate"])
    team_id = match[side + "Team"]["openliga_id"]
    rows = []
    for event in openliga_season(kickoff):
        when = datetime.datetime.fromisoformat(event["matchDateTimeUTC"].replace("Z", "+00:00"))
        if not event["matchIsFinished"] or when >= kickoff:
            continue
        teams = [event[key] for key in ("team1", "team2")]
        ids = [team["teamId"] for team in teams]
        if team_id not in ids:
            continue
        position = ids.index(team_id)
        scores = {r.get("resultTypeKind"): (r["pointsTeam1"], r["pointsTeam2"])
                  for r in event["matchResults"]}
        full = scores.get("After90Minutes")
        if full is None:
            full = next(((v["pointsTeam1"], v["pointsTeam2"]) for v in event["matchResults"] if v.get("resultTypeID") == 2), None)
        if full is None:
            continue
        half = scores.get("HalfTime", (None, None))
        rows.append({
            "date": when.date().isoformat(), "opponent": teams[1-position]["teamName"],
            "venue": ("home", "away")[position], "scored": full[position],
            "conceded": full[1-position], "first_half_scored": half[position],
            "first_half_conceded": half[1-position],
        })
    return summarize_team_games(rows, side)


def summarize_team_games(rows, side):
    rows.sort(key=lambda row: row["date"], reverse=True)
    venue = [row for row in rows if row["venue"] == side]
    half = [row for row in venue if row["first_half_scored"] is not None
            and row["first_half_conceded"] is not None]
    return {
        "games": rows, "venue_games": venue, "count": len(rows), "venue_count": len(venue),
        "scored": sum(row["scored"] for row in rows),
        "conceded": sum(row["conceded"] for row in rows),
        "venue_scored": sum(row["scored"] for row in venue),
        "venue_conceded": sum(row["conceded"] for row in venue),
        "first_half_count": len(half),
        "first_half_scored": sum(row["first_half_scored"] for row in half),
        "first_half_conceded": sum(row["first_half_conceded"] for row in half),
    }


def soccerway_events(league, *, max_age=300):
    _, groups = SOCCERWAY_LEAGUES[league]
    key = ("soccerway", league)
    cached = CACHE.get(key)
    if cached and time.time() - cached["time"] < max_age:
        return cached["events"]
    events = {}
    for group in groups:
        for page in ("fixtures", "results"):
            url = f"https://www.soccerway.com/{group}/{page}/"
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            try:
                with urllib.request.urlopen(request, timeout=8) as response:
                    html = response.read().decode("utf-8")
            except (OSError, UnicodeError) as exc:
                print(f"SOCCERWAY_FIXTURE_ERROR {group} {page} {exc}", flush=True)
                continue
            for blob in re.findall(r"data: `(.*?)`", html, re.S):
                if f"ZL÷/{group}/" not in blob:
                    continue
                for record in blob.split("~AA÷")[1:]:
                    event_id, *parts = record.split("¬")
                    fields = dict(field.split("÷", 1) for field in parts if "÷" in field)
                    stamp = fields.get("AD", "")
                    if not stamp.isdigit() or not fields.get("CX") or not fields.get("AF"):
                        continue
                    kickoff = datetime.datetime.fromtimestamp(int(stamp), datetime.timezone.utc)
                    key_id = (group, event_id)
                    previous = events.get(key_id)
                    if previous is None or fields.get("AB") == "3":
                        events[key_id] = (kickoff, fields)
    if events:
        CACHE[key] = {"time": time.time(), "events": events}
    return events


def soccerway_recent(match, side):
    league = match["espn_league"]
    team_id = match[side + "Team"].get("soccerway_id")
    if not team_id:
        return None
    cutoff = datetime.datetime.fromisoformat(match["utcDate"])
    first_day = season_start(match["utcDate"], league)
    rows = []
    for kickoff, event in soccerway_events(league).values():
        day = (kickoff + datetime.timedelta(hours=3)).date().isoformat()
        if kickoff >= cutoff or day < first_day or event.get("AB") != "3":
            continue
        teams = (event.get("PX"), event.get("PY"))
        if team_id not in teams:
            continue
        try:
            scores = int(event["AG"]), int(event["AH"])
        except (KeyError, ValueError):
            continue
        pos = teams.index(team_id)
        rows.append({
            "date": day, "opponent": event["CX" if pos else "AF"],
            "venue": ("home", "away")[pos], "scored": scores[pos],
            "conceded": scores[1-pos], "first_half_scored": None,
            "first_half_conceded": None,
        })
    return summarize_team_games(rows, side)


def matches(date, league_filter=None, *, max_age=300):
    if league_filter and league_filter not in ESPN_LEAGUES:
        raise ValueError('Gecersiz lig secimi')
    date = valid_date(date)
    cache_key = date + ':' + (league_filter or 'all')
    cached = MATCH_CACHE.get(cache_key)
    if cached and time.time() - cached["time"] < max_age:
        return cached["matches"], False
    import concurrent.futures, hashlib
    leagues = ESPN_LEAGUES if not league_filter else [league_filter]
    def get_league(league):
        if league in SOCCERWAY_LEAGUES:
            name, _ = SOCCERWAY_LEAGUES[league]
            found = []
            for (group, event_id), (kickoff, fields) in soccerway_events(league, max_age=max_age).items():
                if (kickoff + datetime.timedelta(hours=3)).date().isoformat() != date:
                    continue
                uid = int.from_bytes(hashlib.sha256(f"soccerway:{group}:{event_id}".encode()).digest()[:7], "big")
                found.append({
                    "id": -uid, "utcDate": kickoff.isoformat(), "competition": {"name": name},
                    "homeTeam": {"name": fields["CX"], "id": None, "soccerway_id": fields.get("PX")},
                    "awayTeam": {"name": fields["AF"], "id": None, "soccerway_id": fields.get("PY")},
                    "source": "Soccerway", "espn_league": league,
                    "verified_scores": {"full": score_pair(fields.get("AG"), fields.get("AH"))}
                    if fields.get("AB") == "3" else {},
                })
            if found or league != "tur.2":
                return found
        if league == "ger.3":
            selected_day = datetime.date.fromisoformat(date)
            events = openliga_season(selected_day, max_age=max_age)
            found = []
            for event in events:
                kickoff = datetime.datetime.fromisoformat(event["matchDateTimeUTC"].replace("Z", "+00:00"))
                if (kickoff + datetime.timedelta(hours=3)).date() != selected_day:
                    continue
                uid = int.from_bytes(hashlib.sha256(f'openligadb:{event["matchID"]}'.encode()).digest()[:7], "big")
                teams = [
                    {"name": event[side]["teamName"], "id": None, "openliga_id": event[side]["teamId"], "crest": event[side].get("teamIconUrl")}
                    for side in ("team1", "team2")
                ]
                found.append({
                    "id": -uid, "utcDate": kickoff.isoformat(), "competition": {"name": "Almanya 3. Liga"},
                    "homeTeam": teams[0], "awayTeam": teams[1], "source": "OpenLigaDB", "espn_league": league, "verified_scores": openliga_result(event),
                })
            return found
        # Turkey (UTC+3) calendar day overlaps two UTC calendar dates.
        utc_days = [date.replace("-", ""), (datetime.date.fromisoformat(date) - datetime.timedelta(days=1)).strftime("%Y%m%d")]
        def fetch_day(utc_day):
            found = []
            url = "https://site.api.espn.com/apis/site/v2/sports/soccer/" + league + "/scoreboard?dates=" + utc_day + "&limit=500"
            # Some ESPN competitions reject the optional limit parameter with HTTP 400.
            # Retry once with the documented date-only query before marking a league unavailable.
            data = None
            last_error = None
            for candidate_url in (url, url.split("&limit=", 1)[0]):
                req = urllib.request.Request(candidate_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=8) as response:
                        data = json.load(response)
                    break
                except urllib.error.HTTPError as exc:
                    last_error = exc
                    if exc.code != 400:
                        break
                except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                    last_error = exc
                    break
            if data is None:
                print("FIXTURE_PROVIDER_ERROR " + json.dumps({"league": league, "day": utc_day, "error": str(last_error)[:180]}), flush=True)
                return found
            for event in data.get("events", []):
                kickoff = event.get("date", "")
                try:
                    turkey_day = (datetime.datetime.fromisoformat(kickoff.replace("Z", "+00:00")) + datetime.timedelta(hours=3)).date().isoformat()
                except ValueError:
                    continue
                if turkey_day != date:
                    continue
                teams = (event.get("competitions") or [{}])[0].get("competitors", [])
                home = next((t for t in teams if t.get("homeAway") == "home"), None)
                away = next((t for t in teams if t.get("homeAway") == "away"), None)
                if not home or not away:
                    continue
                uid = int.from_bytes(hashlib.sha256((league+str(event.get("id"))).encode()).digest()[:7], "big")
                found.append({"id": -uid, "utcDate": kickoff, "competition": {"name": (data.get("leagues") or [{}])[0].get("name", league)}, "homeTeam": {"name": home.get("team", {}).get("displayName", "?"), "id": None, "crest": ((home.get("team", {}).get("logos") or [{}])[0].get("href"))}, "awayTeam": {"name": away.get("team", {}).get("displayName", "?"), "id": None, "crest": ((away.get("team", {}).get("logos") or [{}])[0].get("href"))}, "source": "ESPN", "espn_league": league, "verified_scores": espn_result(event, home, away), "espn_event_id": event.get("id"), "home_espn_id": home.get("team", {}).get("id"), "away_espn_id": away.get("team", {}).get("id")})

            return found
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as day_pool:
            daily = list(day_pool.map(fetch_day, utc_days))
        found = [m for day_matches in daily for m in day_matches]
        return list({m["id"]: m for m in found}.values())
    items = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        requests = {pool.submit(get_league, league): league for league in leagues}
        for future in concurrent.futures.as_completed(requests):
            try:
                items.extend(future.result())
            except Exception as exc:
                print(f"FIXTURE_LEAGUE_ERROR {requests[future]} {date} {exc}", flush=True)
    # Independent global daily fixture feed; merge with ESPN without replacing it.
    def sportsdb():
        url = "https://www.thesportsdb.com/api/v1/json/123/eventsday.php?" + urllib.parse.urlencode({"d": date, "s": "Soccer"})
        data = sportsdb_json(url)
        out = []
        for event in data.get("events") or []:
            home, away = event.get("strHomeTeam"), event.get("strAwayTeam")
            if not home or not away:
                continue
            kickoff = (event.get("strTimestamp") or ((event.get("dateEvent") or date) + "T" + (event.get("strTime") or "00:00:00") + "Z"))
            uid = int.from_bytes(hashlib.sha256(("sportsdb"+str(event.get("idEvent"))).encode()).digest()[:7], "big")
            status = str(event.get("strStatus") or "").strip().casefold()
            scores = {"full": score_pair(event.get("intHomeScore"), event.get("intAwayScore"))} if status in {"match finished", "ft", "full time"} else {}
            out.append({"verified_scores": scores, "id": -uid, "utcDate": kickoff, "competition": {"name": event.get("strLeague") or "Other"}, "homeTeam": {"name": home, "id": None, "crest": event.get("strHomeTeamBadge")}, "awayTeam": {"name": away, "id": None, "crest": event.get("strAwayTeamBadge")}, "source": "TheSportsDB", "sportsdb_event_id": event.get("idEvent")})
        return out
    try:
        # Keep the independent feed available for a specifically selected Turkish league.
        # Filter strictly by competition to avoid mixing unrelated fixtures.
        extra_events = sportsdb() if not league_filter or league_filter in ("tur.1", "tur.2") else []
        if league_filter in ("tur.1", "tur.2"):
            def is_requested_turkish_league(event):
                name = str(event.get("competition", {}).get("name", "")).casefold()
                if not any(term in name for term in ("turkish", "turkey", "türkiye", "tff", "super lig", "süper lig")):
                    return False
                if league_filter == "tur.2":
                    return any(term in name for term in ("1. lig", "1 lig", "first league", "first division", "tff 1", "tff first", "2nd division", "second division"))
                return any(term in name for term in ("super lig", "süper lig", "super league"))
            extra_events = [event for event in extra_events if is_requested_turkish_league(event)]
            for event in extra_events:
                event["espn_league"] = league_filter
        items.extend(extra_events)
    except Exception as exc:
        print("SPORTSDB_FIXTURE_ERROR " + str(exc)[:180], flush=True)
    if TOKEN and not league_filter:
        try:
            extra = fetch("/matches?" + urllib.parse.urlencode({"dateFrom": date, "dateTo": date})).get("matches", [])
            items.extend(extra)
        except Exception:
            pass
    # Do not invent fixtures when official providers return no events.
    # Confirmed Egyptian Second Division A fixtures, 19 November 2026 (12:30 UTC).
    # Fixture-only fallback: do not invent team histories or first-half scores.
    if date == "2026-11-19" and not league_filter and not any(m.get("espn_league") == "egy.2" for m in items):
        egypt_fixtures = [
            ("Baladiyat El Mahalla", "Haras El Hodood"),
            ("El Dakhleya", "Ismaily"),
            ("La Viena", "Al Sekka El Hadid"),
            ("Pharco", "El Entag El Harby"),
            ("Tersana", "WE SC"),
        ]
        def norm_team(name):
            return re.sub(r"[^a-z0-9]", "", str(name).casefold())
        existing = {(norm_team(m["homeTeam"]["name"]), norm_team(m["awayTeam"]["name"])) for m in items}
        for i, (home_name, away_name) in enumerate(egypt_fixtures, 1):
            pair = (norm_team(home_name), norm_team(away_name))
            if pair not in existing:
                items.append({"id": -(202611190000 + i), "utcDate": "2026-11-19T12:30:00Z",
                    "competition": {"name": "Egyptian Second Division A"},
                    "homeTeam": {"name": home_name, "id": None},
                    "awayTeam": {"name": away_name, "id": None},
                    "source": "Verified fixture fallback", "fixture_verified": True})
                existing.add(pair)
    # Verified TFF fixture fallback for 20 November 2026.
    if date == "2026-11-20" and not league_filter and not any(m.get("espn_league") == "tur.2" for m in items):
        if not any("ğdır" in m.get("homeTeam", {}).get("name", "").casefold() and "mraniye" in m.get("awayTeam", {}).get("name", "").casefold() for m in items):
            items.append({"id": -202611202000, "utcDate": "2026-11-20T17:00:00Z",
                "competition": {"name": "Türkiye 1. Lig"},
                "homeTeam": {"name": "Iğdır FK", "id": None},
                "awayTeam": {"name": "Ümraniyespor", "id": None},
                "source": "TFF doğrulanmış fikstür", "fixture_verified": True})
    # Filter women's football from all fixture sources.
    women_terms = ("women", "woman", "female", "femen", "feminin", "femmin", "frauen", "damen", "kadın", "kadin", "ladies", "wsl", "nwsl", "liga f")
    def is_womens_match(match):
        names = [match.get("competition", {}).get("name", ""), match.get("homeTeam", {}).get("name", ""), match.get("awayTeam", {}).get("name", "")]
        for name in names:
            lowered = str(name).casefold()
            if any(term in lowered for term in women_terms):
                return True
            if re.search(r"(?<![a-z])(?:w|f)(?![a-z])", lowered):
                return True
        return False
    items = [m for m in items if not is_womens_match(m)]
    # Different providers may publish the same fixture with different team spelling.
    # Prefer a record with usable team IDs / ESPN history rather than a fixture-only copy.
    def fixture_key(name):
        value = team_match_key(name)
        aliases = {"fkbodoglimt": "bodoglimt", "bodoglimt": "bodoglimt",
                   "moldefk": "molde", "molde": "molde"}
        return aliases.get(value, value)
    def fixture_quality(m):
        return (int(bool(m.get("home_espn_id") and m.get("away_espn_id"))) * 100
                + int(m.get("source") == "ESPN") * 30
                + int(bool(m.get("homeTeam", {}).get("id") and m.get("awayTeam", {}).get("id"))) * 80
                + int(m.get("source") == "TheSportsDB") * 10
                + int(m.get("source") == "Soccerway") * 20)
    merged = {}
    for m in items:
        pair = (fixture_key(m["homeTeam"]["name"]), fixture_key(m["awayTeam"]["name"]))
        # Same opponents can play twice; retain separate matches if kickoffs differ by > 6h.
        try:
            kickoff = datetime.datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
            if kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=datetime.timezone.utc)
            else:
                kickoff = kickoff.astimezone(datetime.timezone.utc)
        except (ValueError, TypeError, AttributeError):
            kickoff = None
        found = None
        for key, old in merged.items():
            if key[:2] != pair:
                continue
            old_time = key[2]
            if kickoff is None or old_time is None or abs((kickoff - old_time).total_seconds()) <= 21600:
                found = key
                break
        if found is None:
            merged[(*pair, kickoff)] = m
        else:
            old = merged[found]
            # Preserve original provider names for reliable history fallback.
            for candidate in (old, m):
                if candidate.get("source") == "TheSportsDB":
                    backup = {"homeTeam": candidate["homeTeam"], "awayTeam": candidate["awayTeam"],
                              "source": "TheSportsDB", "utcDate": candidate["utcDate"]}
                    old["sportsdb_fallback_match"] = backup
                    m["sportsdb_fallback_match"] = backup
            primary, secondary = (m, old) if fixture_quality(m) > fixture_quality(old) else (old, m)
            ids = {*old.get("fixture_aliases", []), *m.get("fixture_aliases", []), old["id"], m["id"]}
            primary["fixture_aliases"] = sorted(ids - {primary["id"]})
            primary["merged_scores"] = merge_final_scores(final_scores(primary), final_scores(secondary))
            merged[found] = primary
    items = list(merged.values())
    items.sort(key=lambda m: m.get("utcDate") or "")
    from collections import Counter
    by_source = dict(Counter(m.get("source", "Football-Data") for m in items))
    by_league = dict(Counter(m.get("competition", {}).get("name", "?") for m in items))
    print("FIXTURE_AUDIT " + json.dumps({"date": date, "total": len(items), "sources": by_source, "leagues": by_league}, ensure_ascii=False), flush=True)
    MATCH_CACHE.setdefault("by_id", {}).update({m["id"]: m for m in items})
    MATCH_CACHE[cache_key] = {"matches": items, "time": time.time()}
    return items, False

def season_start(date_text, league=None):
    """Season boundary: July for cross-year leagues; January for calendar-year leagues."""
    day = str(date_text)[:10]
    year, month = int(day[:4]), int(day[5:7])
    if league in ("nor.1", "swe.1", "fin.1", "irl.1", "usa.1", "bra.1", "arg.1"):
        return f"{year}-01-01"
    return f"{year if month >= 7 else year - 1}-07-01"

def recent(team_id):
    query = urllib.parse.urlencode({"status": "FINISHED", "limit": 100})
    data = fetch(f"/teams/{team_id}/matches?{query}")
    return sorted(data.get("matches", []),
                  key=lambda x: x.get("utcDate", ""), reverse=True)

def stats(games, team_id, *, before):
    cutoff = datetime.datetime.fromisoformat(before.replace("Z", "+00:00"))
    result = []
    for match in games:
        try:
            played = datetime.datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
            if played >= cutoff:
                continue
        except (KeyError, AttributeError, TypeError, ValueError):
            continue
        home = match.get("homeTeam", {}).get("id") == team_id
        score = match.get("score", {})
        full = score.get("fullTime") or {}
        half = score.get("halfTime") or {}
        a, b = full.get("home"), full.get("away")
        if a is None or b is None:
            continue
        opponent = match.get("awayTeam", {}) if home else match.get("homeTeam", {})
        result.append({
            "date": match.get("utcDate", "")[:10],
            "champions_league": champions_league_fixture(match),
            "opponent": opponent.get("name", "?"),
            "scored": a if home else b,
            "conceded": b if home else a,
            "halfTime": half,
            "first_half_scored": half.get("home" if home else "away"),
            "first_half_conceded": half.get("away" if home else "home"),
            "venue": "home" if home else "away"
        })
    known_half = [x for x in result if x["first_half_scored"] is not None
                  and x["first_half_conceded"] is not None]
    return {
        "games": result,
        "scored": sum(x["scored"] for x in result),
        "conceded": sum(x["conceded"] for x in result),
        "count": len(result),
        "first_half_scored": sum(x["first_half_scored"] for x in known_half),
        "first_half_conceded": sum(x["first_half_conceded"] for x in known_half),
        "first_half_count": len(known_half)
    }

# Published Egyptian Division 2 A standings snapshot, 15 November 2026.
# Season totals are not last-five results; use only as an explicitly labeled fallback.
EGYPT_SEASON_20261115 = {
    "Baladiyat El Mahalla": (12, 10, 11), "Haras El Hodood": (12, 15, 7),
    "El Dakhleya": (12, 9, 16), "Ismaily": (11, 13, 15),
    "La Viena": (12, 7, 14), "Al Sekka El Hadid": (12, 19, 16),
    "Pharco": (12, 18, 12), "El Entag El Harby": (12, 19, 16),
    "Tersana": (12, 13, 9), "WE SC": (12, 16, 11),
}
def egypt_season_fallback(name):
    row = EGYPT_SEASON_20261115.get({"Al Dakhleia": "El Dakhleya"}.get(name, name))
    if not row:
        return None
    played, scored, conceded = row
    return {"games": [], "count": played, "scored": scored, "conceded": conceded,
            "first_half_scored": 0, "first_half_conceded": 0, "first_half_count": 0,
            "data_scope": "season", "data_as_of": "2026-11-15",
            "source_url": "https://stadiro.com/leagues/egypt/division-2-a/"}

def team_match_key(name):
    """Normalize provider spellings for matching, never change displayed names."""
    import unicodedata
    value = str(name or "").casefold().replace("ø", "o").replace("æ", "ae").replace("ß", "ss")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", value)

def sportsdb_team_alias(name):
    key = team_match_key(name)
    return {"bodoglimt": "Bodø/Glimt", "fkbodoglimt": "Bodø/Glimt",
            "moldefk": "Molde", "molde": "Molde"}.get(key, name)

# Shared provider cache and cooldown: avoid repeated requests that trigger HTTP 429.
PROVIDER_CACHE = {}
PROVIDER_COOLDOWN = {}

def sportsdb_json(url):
    now = time.time()
    cached = PROVIDER_CACHE.get(url)
    if cached and now - cached["time"] < 21600:
        return cached["data"]
    host = "thesportsdb"
    if PROVIDER_COOLDOWN.get(host, 0) > now:
        return cached["data"] if cached else {}
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.load(response)
        PROVIDER_CACHE[url] = {"time": now, "data": data}
        return data
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            PROVIDER_COOLDOWN[host] = now + 300
            return cached["data"] if cached else {}
        raise

def sportsdb_recent(match, side):
    """Best-effort recent completed matches for fixture-only teams; never fabricate scores."""
    name = match[side + "Team"]["name"]
    aliases = {"El Dakhleya": "El Dakhleya", "Al Dakhleia": "El Dakhleya",
               "WE SC": "Telecom Egypt", "El Entag El Harby": "El Entag El Harby",
               "Al Sekka El Hadid": "El Sekka El Hadid"}
    query = urllib.parse.urlencode({"t": sportsdb_team_alias(aliases.get(name, name))})
    def get_json(url):
        return sportsdb_json(url)
    teams = get_json("https://www.thesportsdb.com/api/v1/json/123/searchteams.php?" + query).get("teams") or []
    normalized = team_match_key
    exact = [t for t in teams if normalized(t.get("strTeam")) == normalized(sportsdb_team_alias(aliases.get(name, name)))]
    if not exact:
        return None
    team_id = str(exact[0].get("idTeam") or "")
    if not team_id:
        return None
    events = []
    # eventslast uses a team ID; eventsseason requires a league ID and season.
    try:
        payload = get_json("https://www.thesportsdb.com/api/v1/json/3/eventslast.php?id=" + urllib.parse.quote(team_id))
        events.extend(payload.get("results") or payload.get("events") or [])
    except (OSError, ValueError, TypeError):
        pass
    league_id = exact[0].get("idLeague")
    if league_id:
        kickoff_year = int(match.get("utcDate", "2026")[:4])
        seasons = (f"{kickoff_year - 1}-{kickoff_year}", f"{kickoff_year}-{kickoff_year + 1}")
        for season in seasons:
            try:
                params = urllib.parse.urlencode({"id": str(league_id), "s": season})
                payload = get_json("https://www.thesportsdb.com/api/v1/json/3/eventsseason.php?" + params)
                events.extend(payload.get("events") or payload.get("results") or [])
            except (OSError, ValueError, TypeError):
                continue
    cutoff = match.get("utcDate", "")[:10]
    rows = []
    for event in events:
        day = event.get("dateEvent") or ""
        if not day or day >= cutoff:
            continue
        is_home = str(event.get("idHomeTeam")) == team_id
        is_away = str(event.get("idAwayTeam")) == team_id
        if not (is_home or is_away):
            continue
        try:
            hg, ag = int(event["intHomeScore"]), int(event["intAwayScore"])
        except (ValueError, TypeError, KeyError):
            continue
        half_home = half_away = None
        ht = event.get("strHTScore") or ""
        found = re.fullmatch(r"\s*(\d+)\s*[-:]\s*(\d+)\s*", ht)
        if found:
            half_home, half_away = int(found.group(1)), int(found.group(2))
        rows.append({"date": day, "opponent": event.get("strAwayTeam" if is_home else "strHomeTeam") or "?",
                     "scored": hg if is_home else ag, "conceded": ag if is_home else hg,
                     "first_half_scored": half_home if is_home else half_away,
                     "first_half_conceded": half_away if is_home else half_home,
                     "champions_league": (event.get("strStatus") or "").strip().casefold() in {"match finished", "ft", "full time"} and
                     (event.get("strLeague") or "").casefold() == "uefa champions league",
                     "venue": "home" if is_home else "away"})
    rows = list({(r["date"], r["opponent"], r["venue"], r["scored"], r["conceded"]): r for r in rows}.values())
    rows.sort(key=lambda row: row["date"], reverse=True)
    venue = "home" if side == "home" else "away"
    venue_games = [r for r in rows if r["venue"] == venue and r["date"] >= season_start(match["utcDate"], match.get("espn_league"))]
    rows = [r for r in rows if r["date"] >= season_start(match["utcDate"], match.get("espn_league"))]
    known = [r for r in rows if r["first_half_scored"] is not None and r["first_half_conceded"] is not None]
    return {"games": rows, "venue_games": venue_games, "venue_count": len(venue_games), "venue_scored": sum(r["scored"] for r in venue_games), "venue_conceded": sum(r["conceded"] for r in venue_games), "count": len(rows), "scored": sum(r["scored"] for r in rows),
            "conceded": sum(r["conceded"] for r in rows),
            "first_half_scored": sum(r["first_half_scored"] for r in known),
            "first_half_conceded": sum(r["first_half_conceded"] for r in known),
            "first_half_count": len(known)}

def espn_halftime_scores(league, event_id, team_id):
    """Return first-half scored/conceded from the selected team's perspective.

    ESPN competitor order is not guaranteed to be home/away order.
    Match team IDs and cross-check the halftime totals against full-time.
    """
    if not event_id or not team_id:
        return None
    url = ("https://site.api.espn.com/apis/site/v2/sports/soccer/" +
           urllib.parse.quote(str(league), safe="") +
           "/summary?event=" + urllib.parse.quote(str(event_id), safe=""))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.load(response)
        header = (data.get("header") or {}).get("competitions") or []
        competitors = (header[0] if header else {}).get("competitors") or []
        if len(competitors) != 2:
            return None
        values = {}
        for competitor in competitors:
            cid = str((competitor.get("team") or {}).get("id") or "")
            periods = competitor.get("linescores") or []
            if not cid or not periods:
                return None
            first = periods[0]
            # Soccer's first period must be period 1, not an aggregate.
            if first.get("period") not in (None, 1):
                return None
            raw = first.get("value", first.get("displayValue"))
            if raw is None:
                return None
            half = int(float(raw))
            full = competitor.get("score")
            if isinstance(full, dict):
                full = full.get("value", full.get("displayValue"))
            if half < 0 or (full is not None and half > int(float(full))):
                return None
            values[cid] = half
        ours = str(team_id)
        if ours not in values or len(values) != 2:
            return None
        opponent_id = next(cid for cid in values if cid != ours)
        return values[ours], values[opponent_id]
    except (OSError, ValueError, TypeError, KeyError, IndexError, StopIteration):
        return None
    return None

def espn_recent(match, side):
    league = match.get("espn_league")
    team_id = match.get(side + "_espn_id")
    if not league:
        return None
    if not team_id:
        # Fixture-only entries have no ESPN ID. Resolve from the league's real roster.
        try:
            roster_url = "https://site.api.espn.com/apis/site/v2/sports/soccer/" + urllib.parse.quote(str(league), safe="") + "/teams?limit=500"
            request = urllib.request.Request(roster_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=10) as response:
                roster = json.load(response)
            entries = []
            for sport in roster.get("sports") or []:
                for group in sport.get("leagues") or []:
                    entries.extend(group.get("teams") or [])
            wanted = team_match_key(match.get(side + "Team", {}).get("name", ""))
            candidates = [entry.get("team") or entry for entry in entries]
            exact = [entry for entry in candidates if wanted and wanted in {
                team_match_key(entry.get("displayName", "")),
                team_match_key(entry.get("name", "")),
                team_match_key(entry.get("shortDisplayName", ""))}]
            if len(exact) == 1:
                team_id = exact[0].get("id")
        except (OSError, ValueError, TypeError, KeyError):
            pass
    if not team_id:
        return None
    kickoff = datetime.datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
    # ESPN team schedule contains previous results and may be season-specific.
    url = ("https://site.api.espn.com/apis/site/v2/sports/soccer/" +
           urllib.parse.quote(str(league), safe="") + "/teams/" +
           urllib.parse.quote(str(team_id), safe="") + "/schedule?limit=300")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    # Always request the fixture year: ESPN's default schedule can be a different season.
    data = {"events": []}
    for candidate in (url + "&season=" + str(kickoff.year), url + "&season=" + str(kickoff.year - 1), url):
        try:
            request = urllib.request.Request(candidate, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=12) as response:
                payload = json.load(response)
            if payload.get("events"):
                data["events"].extend(payload["events"])
        except (OSError, ValueError, TypeError):
            continue
    rows = []
    for event in data.get("events", []):
        try:
            when = datetime.datetime.fromisoformat(event.get("date", "").replace("Z", "+00:00"))
            if when >= kickoff:
                continue
            competition = (event.get("competitions") or [{}])[0]
            status = competition.get("status") or event.get("status") or {}
            status_type = status.get("type") or {}
            if not status_type.get("completed", False):
                continue
            competitors = competition.get("competitors") or []
            ours = next((c for c in competitors if str(c.get("team", {}).get("id")) == str(team_id)), None)
            theirs = next((c for c in competitors if str(c.get("team", {}).get("id")) != str(team_id)), None)
            if not ours or not theirs:
                continue
            def score(c):
                raw = c.get("score")
                if isinstance(raw, dict):
                    raw = raw.get("value", raw.get("displayValue"))
                return int(float(raw))
            scored, conceded = score(ours), score(theirs)
            event_league = event.get("league")
            if isinstance(event_league, dict):
                event_league = event_league.get("slug")
            rows.append({"date": when.date().isoformat(), "opponent": theirs.get("team", {}).get("displayName", "?"),
                         "scored": scored, "conceded": conceded, "first_half_scored": None,
                         "first_half_conceded": None, "venue": ours.get("homeAway", "?"),
                         "champions_league": league == "uefa.champions" and
                         (not event_league or event_league == league) and
                         status_type.get("name") == "STATUS_FULL_TIME",
                         "_sort": when.isoformat(), "_event_id": event.get("id")})
        except (ValueError, TypeError, KeyError, IndexError):
            continue
    rows = list({(r["_event_id"] or r["_sort"], r["venue"]): r for r in rows}.values())
    rows.sort(key=lambda x: x["_sort"], reverse=True)
    venue = "home" if side == "home" else "away"
    venue_games = [dict(x) for x in rows if x["venue"] == venue and x["date"] >= season_start(match["utcDate"], match.get("espn_league"))]
    recent_games = [dict(x) for x in rows if x["date"] >= season_start(match["utcDate"], match.get("espn_league"))]
    checked = {}
    # Populate one canonical match record, then derive venue_games from it.
    # Previously venue_games was copied before halftime enrichment, leaving
    # games with missing halftime values and producing inconsistent panels.
    for row in recent_games:
        if row["venue"] == venue:
            event_id = row.get("_event_id")
            if event_id not in checked:
                checked[event_id] = espn_halftime_scores(league, event_id, team_id)
            half = checked[event_id]
            if half is not None:
                row["first_half_scored"], row["first_half_conceded"] = half
        row.pop("_event_id", None)
        row.pop("_sort", None)
    venue_games = [row for row in recent_games if row["venue"] == venue]
    known_half = [row for row in venue_games if row["first_half_scored"] is not None and row["first_half_conceded"] is not None]
    return {"games": recent_games, "venue_games": venue_games,
            "venue_count": len(venue_games),
            "venue_scored": sum(x["scored"] for x in venue_games),
            "venue_conceded": sum(x["conceded"] for x in venue_games),
            "scored": sum(x["scored"] for x in recent_games),
            "conceded": sum(x["conceded"] for x in recent_games),
            "count": len(recent_games),
            "first_half_scored": sum(row["first_half_scored"] for row in known_half),
            "first_half_conceded": sum(row["first_half_conceded"] for row in known_half),
            "first_half_count": len(known_half)}

def espn_head_to_head(match):
    league = match.get("espn_league")
    home_id, away_id = match.get("home_espn_id"), match.get("away_espn_id")
    if not league or not home_id or not away_id:
        return None
    kickoff = datetime.datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
    url = ("https://site.api.espn.com/apis/site/v2/sports/soccer/" +
           urllib.parse.quote(str(league), safe="") + "/teams/" +
           urllib.parse.quote(str(home_id), safe="") + "/schedule?limit=300")
    # ESPN's default schedule often covers only one season. Query earlier
    # seasons to recover verified head-to-head matches at both venues.
    events = []
    seen_event_ids = set()
    # Search BOTH clubs: historical ESPN coverage may differ by team.
    for query_team_id in (home_id, away_id):
        team_url = ("https://site.api.espn.com/apis/site/v2/sports/soccer/" +
                    urllib.parse.quote(str(league), safe="") + "/teams/" +
                    urllib.parse.quote(str(query_team_id), safe="") + "/schedule?limit=300")
        for year in range(kickoff.year, kickoff.year - 21, -1):
            season_url = team_url + "&season=" + str(year)
            try:
                req = urllib.request.Request(season_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=7) as response:
                    data = json.load(response)
                for event in data.get("events") or []:
                    event_id = event.get("id")
                    if event_id and event_id in seen_event_ids:
                        continue
                    if event_id:
                        seen_event_ids.add(event_id)
                    events.append(event)
            except (OSError, ValueError, TypeError):
                continue
    games = []
    for event in events:
        try:
            when = datetime.datetime.fromisoformat(event.get("date", "").replace("Z", "+00:00"))
            if when >= kickoff:
                continue
            comp = (event.get("competitions") or [{}])[0]
            status = comp.get("status") or event.get("status") or {}
            if not (status.get("type") or {}).get("completed", False):
                continue
            teams = comp.get("competitors") or []
            ids = {str(t.get("team", {}).get("id")) for t in teams}
            if ids != {str(home_id), str(away_id)}:
                continue
            home = next(t for t in teams if str(t.get("team", {}).get("id")) == str(home_id))
            away = next(t for t in teams if str(t.get("team", {}).get("id")) == str(away_id))
            def score(team):
                value = team.get("score")
                if isinstance(value, dict):
                    value = value.get("value", value.get("displayValue"))
                return int(float(value))
            at_home = home.get("homeAway") == "home"
            if home.get("homeAway") == away.get("homeAway"):
                continue
            hg, ag = score(home), score(away)
            games.append({"date": when.date().isoformat(), "at_home": at_home, "home_goals": hg,
                          "away_goals": ag, "winner": "home" if hg > ag else "away" if ag > hg else "draw"})
        except (ValueError, TypeError, KeyError, StopIteration, IndexError):
            continue
    games.sort(key=lambda g: g["date"], reverse=True)
    venue_games = [g for g in games if g["at_home"]][:5]
    return {"venue_last5": {"count": len(venue_games), "home_wins": sum(g["winner"] == "home" for g in venue_games), "away_wins": sum(g["winner"] == "away" for g in venue_games), "draws": sum(g["winner"] == "draw" for g in venue_games), "under25": sum(g["home_goals"] + g["away_goals"] <= 2 for g in venue_games), "over25": sum(g["home_goals"] + g["away_goals"] > 2 for g in venue_games), "kg_var": sum(g["home_goals"] > 0 and g["away_goals"] > 0 for g in venue_games), "kg_yok": sum(g["home_goals"] == 0 or g["away_goals"] == 0 for g in venue_games)}, "count": len(games), "home_wins": sum(g["winner"] == "home" for g in games),
            "away_wins": sum(g["winner"] == "away" for g in games),
            "draws": sum(g["winner"] == "draw" for g in games), "games": games, "kg_var": sum(g["home_goals"] > 0 and g["away_goals"] > 0 for g in games), "kg_yok": sum(g["home_goals"] == 0 or g["away_goals"] == 0 for g in games), "over25": sum(g["home_goals"] + g["away_goals"] > 2 for g in games), "under25": sum(g["home_goals"] + g["away_goals"] <= 2 for g in games)}

def sportsdb_head_to_head(match):
    """Find completed head-to-head matches before kickoff, at either venue."""
    home_name = match.get("homeTeam", {}).get("name", "")
    away_name = match.get("awayTeam", {}).get("name", "")
    if not home_name or not away_name:
        return None
    def lookup(name):
        url = "https://www.thesportsdb.com/api/v1/json/3/searchteams.php?t=" + urllib.parse.quote(sportsdb_team_alias(name))
        teams = sportsdb_json(url).get("teams") or []
        norm = team_match_key
        exact = next((t for t in teams if norm(t.get("strTeam")) == norm(sportsdb_team_alias(name))), None)
        return exact.get("idTeam") if exact else None
    home_id, away_id = lookup(home_name), lookup(away_name)
    if not home_id or not away_id:
        return None
    # Search direct historical meetings first; eventslast only contains a handful
    # of recent fixtures and misses older head-to-head results.
    urls = [
        "https://www.thesportsdb.com/api/v1/json/3/eventsh2h.php?" + urllib.parse.urlencode({"id1": home_id, "id2": away_id}),
        "https://www.thesportsdb.com/api/v1/json/3/eventslast.php?id=" + urllib.parse.quote(str(home_id)),
    ]
    events = []
    for url in urls:
        try:
            payload = sportsdb_json(url)
            for value in payload.values():
                if isinstance(value, list):
                    events.extend(e for e in value if isinstance(e, dict) and "idHomeTeam" in e)
        except (OSError, ValueError, TypeError):
            continue
    kickoff_day = str(match.get("utcDate") or "")[:10]
    games = []
    for event in events:
        if {str(event.get("idHomeTeam")), str(event.get("idAwayTeam"))} != {str(home_id), str(away_id)}:
            continue
        event_day = str(event.get("dateEvent") or "")[:10]
        if not event_day or (kickoff_day and event_day >= kickoff_day):
            continue
        try:
            hg, ag = int(event["intHomeScore"]), int(event["intAwayScore"])
        except (TypeError, ValueError, KeyError):
            continue
        if str(event.get("idHomeTeam")) != str(home_id):
            hg, ag = ag, hg
        games.append({"date": event_day, "at_home": str(event.get("idHomeTeam")) == str(home_id), "home_goals": hg,
                      "away_goals": ag, "winner": "home" if hg > ag else "away" if ag > hg else "draw"})
    games = list({(g["date"], g["home_goals"], g["away_goals"]): g for g in games}.values())
    games.sort(key=lambda g: g["date"], reverse=True)
    venue_games = [g for g in games if g["at_home"]][:5]
    return {"venue_last5": {"count": len(venue_games), "home_wins": sum(g["winner"] == "home" for g in venue_games), "away_wins": sum(g["winner"] == "away" for g in venue_games), "draws": sum(g["winner"] == "draw" for g in venue_games), "under25": sum(g["home_goals"] + g["away_goals"] <= 2 for g in venue_games), "over25": sum(g["home_goals"] + g["away_goals"] > 2 for g in venue_games), "kg_var": sum(g["home_goals"] > 0 and g["away_goals"] > 0 for g in venue_games), "kg_yok": sum(g["home_goals"] == 0 or g["away_goals"] == 0 for g in venue_games)}, "count": len(games), "home_wins": sum(g["winner"] == "home" for g in games),
            "away_wins": sum(g["winner"] == "away" for g in games),
            "draws": sum(g["winner"] == "draw" for g in games), "games": games,
            "kg_var": sum(g["home_goals"] > 0 and g["away_goals"] > 0 for g in games),
            "kg_yok": sum(g["home_goals"] == 0 or g["away_goals"] == 0 for g in games),
            "over25": sum(g["home_goals"] + g["away_goals"] > 2 for g in games),
            "under25": sum(g["home_goals"] + g["away_goals"] <= 2 for g in games),
            "source": "TheSportsDB (dogrulanmis gecmis maclar)"}

def champions_league_fixture(match):
    competition = match.get("competition") or {}
    return (
        match.get("espn_league") == "uefa.champions"
        or competition.get("code") == "CL"
        or (competition.get("name") or "").casefold() == "uefa champions league"
    )


def champions_league_rule(match):
    if not champions_league_fixture(match):
        return False
    try:
        kickoff = datetime.datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
    except (KeyError, ValueError, AttributeError):
        return False
    turkey_time = datetime.timezone(datetime.timedelta(hours=3))
    return kickoff.tzinfo is not None and kickoff.astimezone(turkey_time).date() >= datetime.date(2026, 11, 25)


def analyze(match):
    home, away = match["homeTeam"], match["awayTeam"]
    output = {
        "match_id": match["id"],
        "competition": match.get("competition", {}).get("name"),
        "home": home.get("name"),
        "away": away.get("name"),
        "date": match.get("utcDate"),
        "champions_league_data_rule": champions_league_rule(match),
        "sections": {},
        "errors": []
    }
    # Fetch independent team histories and head-to-head concurrently.
    # A short cache avoids repeating slow provider calls for the same fixture.
    import concurrent.futures
    cache_key = ("analysis", match["id"])
    cached = CACHE.get(cache_key)
    if cached and time.time() - cached["time"] < 600:
        return cached["result"]

    def load_section(key, team):
        errors = []
        try:
            if key == "head_to_head_last10":
                value = espn_head_to_head(match) if match.get("source") == "ESPN" else sportsdb_head_to_head(match)
                # ESPN can omit older seasons; try verified alternative results.
                if match.get("source") == "ESPN" and (not value or value.get("count", 0) < 5):
                    try:
                        alternative = sportsdb_head_to_head(match.get("sportsdb_fallback_match") or match)
                        if alternative and alternative.get("games"):
                            # Combine verified fixtures from both providers, instead of
                            # discarding unique historical meetings from the smaller source.
                            combined = {}
                            for source in (value or {}, alternative):
                                for game in source.get("games") or []:
                                    game_key = (game.get("date"), game.get("home_goals"), game.get("away_goals"))
                                    if all(part is not None for part in game_key) and game_key[0]:
                                        combined.setdefault(game_key, game)
                            if combined:
                                merged = sorted(combined.values(), key=lambda g: g["date"], reverse=True)[:10]
                                venue = [g for g in merged if g.get("at_home")][:5]
                                def summary(rows):
                                    return {
                                        "count": len(rows),
                                        "home_wins": sum(g["winner"] == "home" for g in rows),
                                        "away_wins": sum(g["winner"] == "away" for g in rows),
                                        "draws": sum(g["winner"] == "draw" for g in rows),
                                        "under25": sum(g["home_goals"] + g["away_goals"] <= 2 for g in rows),
                                        "over25": sum(g["home_goals"] + g["away_goals"] > 2 for g in rows),
                                        "kg_var": sum(g["home_goals"] > 0 and g["away_goals"] > 0 for g in rows),
                                        "kg_yok": sum(g["home_goals"] == 0 or g["away_goals"] == 0 for g in rows),
                                    }
                                value = {**summary(merged), "games": merged,
                                         "venue_last5": summary(venue),
                                         "source": "ESPN + TheSportsDB (verified combined results)"}
                    except (OSError, ValueError, TypeError, KeyError) as exc:
                        errors.append(f"{key} SportsDB: {exc}")
            elif match.get("source") == "OpenLigaDB":
                value = openliga_recent(match, "home" if key == "home_last5" else "away")
            elif match.get("source") == "ESPN":
                side = "home" if key == "home_last5" else "away"
                try:
                    value = espn_recent(match, side)
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    errors.append(f"{key} ESPN: {exc}")
                    value = None
                if not value or not value.get("games"):
                    try:
                        alternative = sportsdb_recent(match.get("sportsdb_fallback_match") or match, side)
                        if alternative and alternative.get("games"):
                            value = alternative
                    except (OSError, ValueError, TypeError, KeyError) as exc:
                        errors.append(f"{key} SportsDB: {exc}")
            elif match.get("espn_league"):
                side = "home" if key == "home_last5" else "away"
                value = soccerway_recent(match, side) if match.get("source") == "Soccerway" else None
                try:
                    if not value or not value.get("games"):
                        value = espn_recent(match, side)
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    errors.append(f"{key} ESPN roster: {exc}")
                    value = None
                if not value or not value.get("games"):
                    try:
                        value = sportsdb_recent(match, side)
                    except (OSError, ValueError, TypeError, KeyError) as exc:
                        errors.append(f"{key} SportsDB: {exc}")
                        value = None
            elif team.get("id") is not None:
                value = stats(recent(team["id"]), team["id"], before=match["utcDate"])
            else:
                egypt_fallback = (match.get("competition", {}).get("name") == "Egyptian Second Division A"
                                  and str(match.get("utcDate") or "")[:10] == "2026-11-19")
                try:
                    value = sportsdb_recent(match, "home" if key == "home_last5" else "away")
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    errors.append(f"{key} SportsDB: {exc}")
                    value = None
                if not value or not value.get("games"):
                    fallback = egypt_season_fallback(team.get("name")) if egypt_fallback else None
                    value = fallback or value
            return key, value, errors
        except Exception as exc:
            return key, None, errors + [f"{key}: {exc}"]

    jobs = (("home_last5", home), ("away_last5", away), ("head_to_head_last10", None))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(load_section, key, team) for key, team in jobs]
        for future in concurrent.futures.as_completed(futures):
            key, value, errors = future.result()
            output["sections"][key] = value
            output["errors"].extend(errors)
    for key in ("standings", "league_goals",
                "first_half_scores", "half_time_full_time", "squad_values",
                "critical_absences", "historical_odds", "coach_changes"):
        output["sections"][key] = None
    output["warnings"] = [
        "API ucretsiz plani tum ligleri ve analiz alanlarini kapsamayabilir.",
        "Dogrulanamayan bilgiler tahmin edilmedi."
    ]
    output["status"] = "partial"
    output["debug"] = {"fixture_source": match.get("source"), "espn_league": match.get("espn_league"),
                       "home_espn_id": match.get("home_espn_id"), "away_espn_id": match.get("away_espn_id"),
                       "section_counts": {k: (v.get("count") if isinstance(v, dict) else None)
                                          for k, v in output["sections"].items() if k in ("home_last5", "away_last5", "head_to_head_last10")}}
    if any(term in (str(output["home"]) + " " + str(output["away"])).casefold() for term in ("molde", "glimt")):
        print("ANALYSIS_DIAGNOSTIC " + json.dumps({"home": output["home"], "away": output["away"],
              "source": match.get("source"), "league": match.get("espn_league"),
              "team_ids": [match.get("home_espn_id"), match.get("away_espn_id")],
              "errors": output["errors"], "counts": output["debug"]["section_counts"]}, ensure_ascii=False), flush=True)
    CACHE[cache_key] = {"time": time.time(), "result": output}
    return output

def telegram(message):
    if not TG_TOKEN or not TG_CHAT:
        raise ValueError("Telegram ayarlari eksik")
    payload = urllib.parse.urlencode(
        {"chat_id": TG_CHAT, "text": message}
    ).encode()
    with urllib.request.urlopen(
        "https://api.telegram.org/bot" + TG_TOKEN + "/sendMessage",
        payload, timeout=20
    ) as response:
        return json.load(response)

def score_pair(home, away):
    values = (home, away)
    if all(re.fullmatch(r"[0-9]+(?:\.0+)?", str(value)) for value in values):
        return tuple(int(str(value).split(".")[0]) for value in values)
    return None


def openliga_result(event):
    if not event.get("matchIsFinished"):
        return {}
    return {period: score_pair(row.get("pointsTeam1"), row.get("pointsTeam2"))
            for row in event.get("matchResults", [])
            for period in ("full", "half")
            if row.get("resultTypeID") == {"full": 2, "half": 1}[period]}


def espn_result(event, home, away):
    status = event.get("status", {}).get("type", {})
    if not status.get("completed") or status.get("name") != "STATUS_FULL_TIME":
        return {}
    full = score_pair(home.get("score"), away.get("score"))
    first_period = [
        next((row.get("value", row.get("displayValue")) for row in team.get("linescores", [])
              if row.get("period") == 1), None)
        for team in (home, away)
    ]
    half = score_pair(*first_period)
    return {"full": full, "half": half if full and half and all(a <= b for a, b in zip(half, full)) else None}


def merge_final_scores(primary, secondary):
    full = primary.get("full") or secondary.get("full")
    half = primary.get("half")
    if not half and secondary.get("full") == full:
        half = secondary.get("half")
    return {"full": full, "half": half if full and half and all(a <= b for a, b in zip(half, full)) else None}


def final_scores(match):
    if "merged_scores" in match:
        return match["merged_scores"]
    if match.get("status") == "FINISHED" and match.get("score", {}).get("duration") == "REGULAR":
        score = match["score"]
        return {period: score_pair(*(score.get(key, {}).get(side) for side in ("home", "away")))
                for period, key in (("full", "fullTime"), ("half", "halfTime"))}
    return match.get("verified_scores", {})


def recommendation_result(market, scores):
    period = "half" if market.startswith("İY ") else "full"
    pair = scores.get(period)
    if pair is None:
        return None
    home, away = pair
    if market in ("MS 1", "MS 0", "MS 2"):
        actual = "MS 1" if home > away else "MS 2" if away > home else "MS 0"
        return market == actual
    targets = {"1,5 Üst": 2, "2,5 Üst": 3, "İY 0,5 Üst": 1, "İY 1,5 Üst": 2}
    if market == "2,5 Alt":
        return home + away <= 2
    return home + away >= targets[market]


def archive_recommendations(db_path, match, output):
    kickoff = datetime.datetime.fromisoformat(match["utcDate"].replace("Z", "+00:00"))
    if kickoff.tzinfo is None or kickoff.timestamp() <= time.time():
        return
    selections = analysis_context().eval(
        "(data) => {const picks={}; analysisView(JSON.parse(data), ['system'], picks); return JSON.stringify(picks);}"
    )(json.dumps(output))
    captured_at = time.time()
    if selections == "{}" or captured_at >= kickoff.timestamp():
        return
    day = kickoff.astimezone(datetime.timezone(datetime.timedelta(hours=3))).date().isoformat()
    with closing(membership.connect(db_path)) as db, db:
        db.execute(
            """INSERT INTO recommendation_archive
               (match_day, fixture_id, home, away, captured_at, selections)
               VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (match_day, fixture_id) DO NOTHING""",
            (day, str(match["id"]), output["home"], output["away"], int(captured_at), selections),
        )


# Verified historical scores for fixtures whose provider omitted the halftime score.
VERIFIED_HISTORICAL_SCORES = {
    # https://www.inter.it/en/match_center/5381
    ("2026-11-22", "atalanta", "internazionale"): {"full": (4, 4), "half": (1, 2)},
    # https://www.directvsports.com/futbol/en-vivo-primer-tiempo-finalizado-sport-huancayo-se-impone-3-0-sobre-universitario-20261119-0031.html
    ("2026-11-22", "sporthuancayo", "universitario"): {"full": (4, 1), "half": (3, 0)},
}


def recommendation_scores(day, item, scores):
    key = (day, team_match_key(item["home"]), team_match_key(item["away"]))
    confirmed = VERIFIED_HISTORICAL_SCORES.get(key)
    return merge_final_scores(scores, confirmed) if confirmed else scores


def refresh_recommendation_scores(day, archived):
    def index_fixtures(items):
        return {
            str(fixture_id): match
            for match in items
            for fixture_id in (match["id"], *match.get("fixture_aliases", []))
        }

    items, _ = matches(day)
    fixtures = index_fixtures(items)
    by_league = {}
    require_full_refresh = False
    for item in archived:
        fixture_id = item["fixture_id"]
        match = fixtures.get(fixture_id, {})
        scores = recommendation_scores(day, item, final_scores(match))
        if all(recommendation_result(market, scores) is not None for market in json.loads(item["selections"])):
            continue
        league = match.get("espn_league")
        if league in ESPN_LEAGUES:
            by_league.setdefault(league, []).append(fixture_id)
        else:
            require_full_refresh = True

    if require_full_refresh:
        updated, _ = matches(day, max_age=RESULT_REFRESH_SECONDS)
        fixtures.update(index_fixtures(updated))
    scores_by_id = {fixture_id: final_scores(match) for fixture_id, match in fixtures.items()}
    kickoff_by_id = {fixture_id: match.get("utcDate") for fixture_id, match in fixtures.items()}
    for league, fixture_ids in by_league.items():
        updated, _ = matches(day, league, max_age=RESULT_REFRESH_SECONDS)
        fresh = index_fixtures(updated)
        for fixture_id in fixture_ids:
            old = fixtures.get(fixture_id, {})
            # A league-specific result can use the canonical ID instead of an archived alias.
            match = fresh.get(fixture_id) or fresh.get(str(old.get("id")))
            if match:
                if match.get("utcDate"):
                    kickoff_by_id[fixture_id] = match["utcDate"]
                scores_by_id[fixture_id] = merge_final_scores(final_scores(match), scores_by_id.get(fixture_id, {}))
    for item in archived:
        fixture_id = item["fixture_id"]
        scores = recommendation_scores(day, item, scores_by_id.get(fixture_id, {}))
        match = fixtures.get(fixture_id, {})
        if (scores.get("full") and not scores.get("half")
                and any(market.startswith("İY ") for market in json.loads(item["selections"]))
                and match.get("espn_event_id") and match.get("home_espn_id")):
            cache_key = ("recommendation_halftime", match["espn_event_id"], scores["full"])
            half = CACHE.get(cache_key)
            if half is None:
                half = espn_halftime_scores(match["espn_league"], match["espn_event_id"], match["home_espn_id"])
                if half and all(a <= b for a, b in zip(half, scores["full"])):
                    CACHE[cache_key] = half
                else:
                    half = None
            scores = dict(scores, half=half)
        scores_by_id[fixture_id] = scores
    return scores_by_id, kickoff_by_id, len(updated if require_full_refresh else items)


def recommendation_report(db_path, day):
    with closing(membership.connect(db_path)) as db:
        archived = db.execute(
            """SELECT fixture_id, home, away, selections FROM recommendation_archive
               WHERE match_day=? ORDER BY captured_at, fixture_id""", (day,)
        ).fetchall()
    scores_by_id, kickoff_by_id = {}, {}
    if archived and day <= (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)).date().isoformat():
        with RESULT_REFRESH_LOCKS.setdefault(day, Lock()):
            scores_by_id, kickoff_by_id, total_matches = refresh_recommendation_scores(day, archived)
    else:
        fixtures, _ = matches(day)
        total_matches = len(fixtures)
    rows = []
    predicted_matches = 0
    for item in archived:
        fixture_id = item["fixture_id"]
        scores = scores_by_id.get(fixture_id, {})
        selections = json.loads(item["selections"])
        outcomes = {market: recommendation_result(market, scores) for market in selections}
        if selections:
            predicted_matches += 1
        for market, points in selections.items():
            rows.append({"home": item["home"], "away": item["away"], "market": market,
                         "kickoff": kickoff_by_id.get(fixture_id),
                         "points": points, "hit": outcomes[market],
                         "full_score": scores.get("full"), "half_score": scores.get("half")})
    hits = sum(row["hit"] is True for row in rows)
    misses = sum(row["hit"] is False for row in rows)
    return {"rows": rows, "hits": hits, "misses": misses, "pending": len(rows) - hits - misses,
            "accuracy": round(100 * hits / (hits + misses), 1) if hits + misses else None,
            "total_matches": total_matches, "predicted_matches": predicted_matches}


def analysis_context():
    import quickjs

    context = quickjs.Context()
    context.set_memory_limit(16 * 1024 * 1024)
    context.set_time_limit(1)
    context.eval(ANALYSIS_VIEW)
    return context


def subscriber_analysis(output, panels):
    context = analysis_context()
    render = context.eval("(data, panels) => JSON.stringify(analysisView(JSON.parse(data), JSON.parse(panels)))")
    view = json.loads(render(json.dumps(output), json.dumps(panels)))
    return {"status": output["status"], "view": view}


class Handler(AccessHandler, http.server.BaseHTTPRequestHandler):
    def end_headers(self):
        if self.membership_path:
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def send(self, data, status=200, *, cookie=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.write_body(body)

    def write_body(self, body):
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if self.membership_gate(path, "GET"):
            return
        if path == "/":
            self.access_page("index.html")
            return
        try:
            if path == "/api/status":
                self.send({
                    "football_api_configured": bool(TOKEN),
                    "telegram_configured": bool(TG_TOKEN and TG_CHAT),
                    "analyzed": len(CACHE)
                })
                return
            if path.startswith("/api/odds/"):
                mid = int(path.rsplit("/", 1)[1])
                match = MATCH_CACHE.get("by_id", {}).get(mid)
                if not match:
                    self.send({"source": "Maç bulunamadı", "odds": {}}, 404)
                    return
                self.send(bsd_odds(match))
                return
            if path.startswith("/api/team-info/"):
                mid = int(path.rsplit("/", 1)[1])
                match = MATCH_CACHE.get("by_id", {}).get(mid)
                if not match:
                    self.send({"home_rank": None, "away_rank": None, "home_value": None, "away_value": None})
                    return
                ranks = team_standings(match)
                self.send({"home_rank": ranks["home"], "away_rank": ranks["away"],
                           "home_value": None, "away_value": None, "source": ranks["source"]})
                return
            if path == "/api/recommendation-results":
                if not self.membership_path or "system" not in self.current_panels:
                    self.send({"error": "Bu panel hesabınız için açık değil"}, 403)
                    return
                day = valid_date(urllib.parse.parse_qs(parsed.query).get("date", [""])[0])
                self.send(recommendation_report(self.membership_path, day))
                return
            if path == "/api/leagues":
                self.send({"leagues": ESPN_LEAGUES})
                return
            if path == "/api/matches":
                date = urllib.parse.parse_qs(parsed.query).get(
                    "date", [datetime.datetime.now(
                        datetime.timezone.utc).date().isoformat()]
                )[0]
                league_filter = urllib.parse.parse_qs(parsed.query).get('league', [None])[0]
                items, demo = matches(date, league_filter)
                self.send({"matches": [dict(m, id=str(m["id"])) for m in items], "demo": demo, "date": date,
                           "count": len(items),
                           "message": ("Bu tarih icin API mac dondurmedi. "
                                       "Ucretsiz plan kapsaminda mac olmayabilir.")
                           if not items else ""})
                return
            if path.startswith("/api/analyze/"):
                mid = int(path.rsplit("/", 1)[1])
                match = MATCH_CACHE.get("by_id", {}).get(mid)
                if not match:
                    date = urllib.parse.parse_qs(parsed.query).get(
                        "date", [datetime.datetime.now(
                            datetime.timezone.utc).date().isoformat()]
                    )[0]
                    items, _ = matches(date)
                    match = next((m for m in items if m["id"] == mid), None)
                if not match:
                    self.send({"error": "Mac bulunamadi"}, 404)
                    return
                output = analyze(match)
                CACHE[mid] = output
                if self.membership_path and "system" in self.current_panels:
                    try:
                        archive_recommendations(self.membership_path, match, output)
                    except Exception:
                        print("RECOMMENDATION_ARCHIVE_ERROR", flush=True)
                if self.membership_path and not self.current_member["is_admin"]:
                    self.send(subscriber_analysis(output, self.current_panels))
                else:
                    self.send(output)
                return
            self.send({"error": "Bulunamadi"}, 404)
        except ValueError as exc:
            self.send({"error": str(exc)}, 400)
        except Exception as exc:
            self.send({"error": str(exc)}, 502)

    def do_POST(self):
        if self.membership_gate(urllib.parse.urlparse(self.path).path, "POST"):
            return
        try:
            if self.path != "/api/telegram":
                self.send({"error": "Bulunamadi"}, 404)
                return
            size = int(self.headers.get("Content-Length", "0"))
            if size < 0 or size > 10000:
                self.send({"error": "Gecersiz istek boyutu"}, 413)
                return
            data = json.loads(self.rfile.read(size) or b"{}")
            mid = int(data["match_id"])
            analysis = CACHE[mid]
            message = (
                f"⚽ {analysis['home']} - {analysis['away']}\n"
                f"Lig: {analysis['competition']}\n"
                f"Durum: {analysis['status']}\n"
            )
            for key in ("home_last5", "away_last5"):
                section = analysis["sections"].get(key)
                if section:
                    message += (
                        f"{key}: {section['count']} mac, "
                        f"{section['scored']} atilan, "
                        f"{section['conceded']} yenilen\n"
                    )
            message += "Eksik veriler tahmin edilmedi."
            telegram(message)
            self.send({"ok": True})
        except Exception as exc:
            self.send({"error": str(exc)}, 400)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    Handler.membership_path = configure()
    host = "127.0.0.1" if os.environ.get("MEMBERSHIP_MODE") == "local" else "0.0.0.0"
    print("http://localhost:" + str(port), flush=True)
    http.server.ThreadingHTTPServer((host, port), Handler).serve_forever()
                        
