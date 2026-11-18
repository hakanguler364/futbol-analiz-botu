"""Football analysis dashboard. Python standard library only."""
import os, json, urllib.request, urllib.parse, urllib.error, http.server, datetime, pathlib, re
BASE=pathlib.Path(__file__).parent
TOKEN=os.getenv('FOOTBALL_DATA_TOKEN','')
TG_TOKEN=os.getenv('TELEGRAM_BOT_TOKEN','')
TG_CHAT=os.getenv('TELEGRAM_CHAT_ID','')
CACHE={}
MATCH_CACHE={}
def fetch(path):
    if not TOKEN: raise ValueError('FOOTBALL_DATA_TOKEN ayarlanmamış')
    req=urllib.request.Request('https://api.football-data.org/v4'+path,headers={'X-Auth-Token':TOKEN})
    try:
        with urllib.request.urlopen(req,timeout=20) as r: return json.load(r)
    except urllib.error.HTTPError as e:
        raise ValueError('Football-Data API HTTP '+str(e.code)) from e
def valid_date(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError('Tarih YYYY-MM-DD olmalı')
    datetime.date.fromisoformat(value)
    return value
def sample(date):
    return [{'id':101,'utcDate':date+'T19:00:00Z','status':'SCHEDULED','competition':{'name':'Örnek Lig'},'homeTeam':{'id':1,'name':'Örnek Ev'},'awayTeam':{'id':2,'name':'Örnek Deplasman'}}]
def matches(date):
    date=valid_date(date)
    if not TOKEN:return sample(date),True
    if date not in MATCH_CACHE:
        q=urllib.parse.urlencode({'dateFrom':date,'dateTo':date})
        data=fetch('/matches?'+q)
        MATCH_CACHE[date]=data.get('matches',[])
        MATCH_CACHE.setdefault('by_id',{}).update({m['id']:m for m in MATCH_CACHE[date]})
    return MATCH_CACHE[date],False
def recent(team_id):
    d=fetch('/teams/'+str(team_id)+'/matches?status=FINISHED&limit=5')
    return sorted(d.get('matches',[]),key=lambda x:x.get('utcDate',''),reverse=True)[:5]
def stats(games,team_id):
    result=[]
    for m in games:
        h=m.get('homeTeam',{}).get('id')==team_id
        full=m.get('score',{}).get('fullTime',{})
        a,b=full.get('home'),full.get('away')
        if a is None or b is None:continue
        result.append({'date':m.get('utcDate','')[:10],'opponent':(m.get('awayTeam') if h else m.get('homeTeam',{})).get('name','?'),'scored':a if h else b,'conceded':b if h else a,'halfTime':m.get('score',{}).get('halfTime')})
    return {'games':result,'scored':sum(x['scored'] for x in result),'conceded':sum(x['conceded'] for x in result),'count':len(result)}
def analyze(m):
    home=m['homeTeam'];away=m['awayTeam']
    out={'match_id':m['id'],'competition':m.get('competition',{}).get('name'),'home':home.get('name'),'away':away.get('name'),'date':m.get('utcDate'),'sections':{},'errors':[]}
    for key,team in [('home_last5',home),('away_last5',away)]:
        try:out['sections'][key]=stats(recent(team['id']),team['id']) if TOKEN else None
        except Exception as e:out['errors'].append(key+': '+str(e))
    for k in ['head_to_head_last10','standings','league_goals','first_half_scores','half_time_full_time','squad_values','critical_absences','historical_odds','coach_changes']:
        out['sections'][k]=None
    out['warnings']=['Bu veri kaynağı/planı tüm ligleri ve tüm analiz başlıklarını garanti etmez.','Boş alanlar doğrulanamadı; tahmin edilmedi.']
    out['status']='partial' if TOKEN else 'demo'
    return out
def telegram(message):
    if not TG_TOKEN or not TG_CHAT:raise ValueError('Telegram ayarları eksik')
    payload=urllib.parse.urlencode({'chat_id':TG_CHAT,'text':message}).encode()
    with urllib.request.urlopen('https://api.telegram.org/bot'+TG_TOKEN+'/sendMessage',payload,timeout=20) as r:return json.load(r)
class Handler(http.server.BaseHTTPRequestHandler):
    def send(self,data,status=200):
        b=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def do_GET(self):
        parsed=urllib.parse.urlparse(self.path)
        path=parsed.path
        if path=='/':
            b=(BASE/'index.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
        try:
            if path=='/api/matches':
                date=urllib.parse.parse_qs(parsed.query).get('date',[datetime.datetime.now(datetime.timezone.utc).date().isoformat()])[0]
                ms,demo=matches(date);self.send({'matches':ms,'demo':demo,'date':date});return
            if path=='/api/status':self.send({'football_api_configured':bool(TOKEN),'telegram_configured':bool(TG_TOKEN and TG_CHAT),'analyzed':len(CACHE)});return
            if path.startswith('/api/analyze/'):
                mid=int(path.rsplit('/',1)[1])
                m=MATCH_CACHE.get('by_id',{}).get(mid)
                if not m:
                    date=urllib.parse.parse_qs(parsed.query).get('date',[datetime.datetime.now(datetime.timezone.utc).date().isoformat()])[0]
                    ms,demo=matches(date);m=next((x for x in ms if x['id']==mid),None)
                if not m:self.send({'error':'Maç bulunamadı'},404);return
                out=analyze(m);CACHE[mid]=out;self.send(out);return
            self.send({'error':'Bulunamadı'},404)
        except ValueError as e:self.send({'error':str(e)},400)
        except Exception as e:self.send({'error':str(e)},502)
    def do_POST(self):
        try:
            if self.path!='/api/telegram':self.send({'error':'Bulunamadı'},404);return
            n=int(self.headers.get('Content-Length','0'))
            if n>10000:self.send({'error':'Çok büyük istek'},413);return
            data=json.loads(self.rfile.read(n) or '{}');mid=int(data['match_id']);a=CACHE[mid]
            msg=f"⚽ {a['home']} - {a['away']}\nLig: {a['competition']}\nDurum: {a['status']}\n"
            for k in ['home_last5','away_last5']:
                s=a['sections'][k]
                if s:msg+=f"{k}: {s['count']} maç, {s['scored']} atılan, {s['conceded']} yenilen\n"
            msg+='Eksik veriler tahmin edilmedi.'
            telegram(msg);self.send({'ok':True})
        except Exception as e:self.send({'error':str(e)},400)
if __name__=='__main__':
    port=int(os.getenv('PORT','8080'));print('http://localhost:'+str(port));http.server.ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
        
