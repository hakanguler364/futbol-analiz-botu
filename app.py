
"""Football analysis dashboard. Python standard library only."""
import os, json, urllib.request, urllib.parse, urllib.error, http.server, datetime, pathlib, re, time

BASE = pathlib.Path(__file__).parent
TOKEN = os.getenv("FOOTBALL_DATA_TOKEN", "").strip()
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
CACHE = {}
MATCH_CACHE = {}

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

def valid_date(value):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Tarih YYYY-MM-DD olmali")
    datetime.date.fromisoformat(value)
    return value

def matches(date):
    date = valid_date(date)
    if not TOKEN:
        raise ValueError("FOOTBALL_DATA_TOKEN Render ortaminda tanimli degil")
    cached = MATCH_CACHE.get(date)
    if cached and time.time() - cached["time"] < 300:
        return cached["matches"], False
    query = urllib.parse.urlencode({"dateFrom": date, "dateTo": date})
    data = fetch("/matches?" + query)
    items = data.get("matches", [])
    if not isinstance(items, list):
        raise ValueError("API yanitinda matches listesi yok")
    MATCH_CACHE.setdefault("by_id", {}).update(
        {m["id"]: m for m in items if m.get("id") is not None}
    )
    # Bos sonuc kalici olarak onbellege alinmaz.
    if items:
        MATCH_CACHE[date] = {"matches": items, "time": time.time()}
    else:
        MATCH_CACHE.pop(date, None)
    return items, False

def recent(team_id):
    query = urllib.parse.urlencode({"status": "FINISHED", "limit": 5})
    data = fetch(f"/teams/{team_id}/matches?{query}")
    return sorted(data.get("matches", []),
                  key=lambda x: x.get("utcDate", ""), reverse=True)[:5]

def stats(games, team_id):
    result = []
    for match in games:
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

def analyze(match):
    home, away = match["homeTeam"], match["awayTeam"]
    output = {
        "match_id": match["id"],
        "competition": match.get("competition", {}).get("name"),
        "home": home.get("name"),
        "away": away.get("name"),
        "date": match.get("utcDate"),
        "sections": {},
        "errors": []
    }
    for key, team in (("home_last5", home), ("away_last5", away)):
        try:
            output["sections"][key] = stats(recent(team["id"]), team["id"])
        except Exception as exc:
            output["sections"][key] = None
            output["errors"].append(f"{key}: {exc}")
    for key in ("head_to_head_last10", "standings", "league_goals",
                "first_half_scores", "half_time_full_time", "squad_values",
                "critical_absences", "historical_odds", "coach_changes"):
        output["sections"][key] = None
    output["warnings"] = [
        "API ucretsiz plani tum ligleri ve analiz alanlarini kapsamayabilir.",
        "Dogrulanamayan bilgiler tahmin edilmedi."
    ]
    output["status"] = "partial"
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

class Handler(http.server.BaseHTTPRequestHandler):
    def send(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/":
            try:
                body = (BASE / "index.html").read_bytes()
            except FileNotFoundError:
                self.send({"error": "index.html bulunamadi"}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        try:
            if path == "/api/status":
                self.send({
                    "football_api_configured": bool(TOKEN),
                    "telegram_configured": bool(TG_TOKEN and TG_CHAT),
                    "analyzed": len(CACHE)
                })
                return
            if path == "/api/matches":
                date = urllib.parse.parse_qs(parsed.query).get(
                    "date", [datetime.datetime.now(
                        datetime.timezone.utc).date().isoformat()]
                )[0]
                items, demo = matches(date)
                self.send({"matches": items, "demo": demo, "date": date,
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
                self.send(output)
                return
            self.send({"error": "Bulunamadi"}, 404)
        except ValueError as exc:
            self.send({"error": str(exc)}, 400)
        except Exception as exc:
            self.send({"error": str(exc)}, 502)

    def do_POST(self):
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
    print("http://localhost:" + str(port), flush=True)
    http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
                        
