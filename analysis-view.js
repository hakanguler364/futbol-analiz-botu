const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({
'&':'&amp;','<':'&lt;','>':'&gt;',
'"':'&quot;',"'":'&#39;'
}[c]));

function matchResultScores(home,away,h2h){
 const hg=home?.games||[],ag=away?.games||[];
 const validGoals=x=>x&&Number.isFinite(x.count)&&x.count>=5&&Number.isFinite(x.scored)&&Number.isFinite(x.conceded);
 if(!validGoals(home)||!validGoals(away)||hg.length<3||ag.length<3)return {ms1:null,ms0:null,ms2:null,note:'Yeterli doğrulanmış maç verisi yok'};
 const ha=home.scored/home.count,hc=home.conceded/home.count,aa=away.scored/away.count,ac=away.conceded/away.count;
 const clamp=x=>Math.max(0,Math.min(1,x));
 const recent=x=>x.slice(0,5),wins=x=>x.filter(g=>g.scored>g.conceded).length/x.length,draws=x=>x.filter(g=>g.scored===g.conceded).length/x.length;
 const hr=recent(hg),ar=recent(ag),hv=hg.filter(g=>g.venue==='home').slice(0,5),av=ag.filter(g=>g.venue==='away').slice(0,5);
 const venueStats=games=>({count:games.length,scored:games.reduce((n,g)=>n+Number(g.scored),0),conceded:games.reduce((n,g)=>n+Number(g.conceded),0)});
 const homeVenue=venueStats(hg.filter(g=>g.venue==='home'&&Number.isFinite(g.scored)&&Number.isFinite(g.conceded)));
 const awayVenue=venueStats(ag.filter(g=>g.venue==='away'&&Number.isFinite(g.scored)&&Number.isFinite(g.conceded)));
 const venueGoalsReady=homeVenue.count>=3&&awayVenue.count>=3;
 const vhAttack=venueGoalsReady?homeVenue.scored/homeVenue.count:ha;
 const vhConcede=venueGoalsReady?homeVenue.conceded/homeVenue.count:hc;
 const vaAttack=venueGoalsReady?awayVenue.scored/awayVenue.count:aa;
 const vaConcede=venueGoalsReady?awayVenue.conceded/awayVenue.count:ac;
 const generalGoalEdge=clamp(.5+(ha-aa)*.23+(ac-hc)*.23);
 const venueGoalEdge=clamp(.5+(vhAttack-vaAttack)*.23+(vaConcede-vhConcede)*.23);
 const homeEdge=venueGoalsReady? .35*generalGoalEdge+.65*venueGoalEdge:generalGoalEdge;
 const formEdge=clamp(.5+(wins(hr)-wins(ar))*.5);
 const venueEdge=hv.length>=3&&av.length>=3?clamp(.5+(wins(hv)-wins(av))*.5):.5;
 const venueH=h2h?.venue_last5?.count>=3?h2h.venue_last5:null;
 const h2hData=h2h?.count>=5?h2h:null;
 const h2hEdge=h2hData?clamp((h2hData.home_wins+.5*h2hData.draws)/h2hData.count):.5;
 const venueH2hEdge=venueH?clamp((venueH.home_wins+.5*venueH.draws)/venueH.count):.5;
 const recentH2h=h2h?.games?.slice().sort((a,b)=>String(b.date||'').localeCompare(String(a.date||''))).slice(0,5)||[];
 const recentH2hEdge=recentH2h.length>=3?clamp((recentH2h.filter(g=>g.winner==='home').length+.5*recentH2h.filter(g=>g.winner==='draw').length)/recentH2h.length):.5;
 const edge=clamp(.5+(homeEdge-.5)*.35+(formEdge-.5)*.15+(venueEdge-.5)*.15+(h2hEdge-.5)*.15+(venueH2hEdge-.5)*.1+(recentH2hEdge-.5)*.1);
 const attackClose=clamp(1-Math.abs(vhAttack-vaAttack)/1.2),defenseClose=clamp(1-Math.abs(vhConcede-vaConcede)/1.2);
 const recentDraw=(draws(hr)+draws(ar))/2;
 const h2hDraw=h2hData?h2hData.draws/h2hData.count:null;
 const venueDraw=hv.length>=3&&av.length>=3?(draws(hv)+draws(av))/2:null;
 const weighted=[[attackClose,25],[defenseClose,20],[recentDraw,25],[h2hDraw,20],[venueDraw,10]].filter(([v])=>v!==null);
 const drawEvidence=weighted.reduce((t,[v,w])=>t+v*w,0)/weighted.reduce((t,[v,w])=>t+w,0);
 // Independent model points, not probabilities; high draw evidence reduces winner confidence.
 const draw=clamp(drawEvidence);
 const winnerScale=1-.55*draw;
 const breakdown={homeScored:ha,homeConceded:hc,awayScored:aa,awayConceded:ac,homeVenueCount:homeVenue.count,awayVenueCount:awayVenue.count,homeVenueScored:homeVenue.count?homeVenue.scored/homeVenue.count:null,homeVenueConceded:homeVenue.count?homeVenue.conceded/homeVenue.count:null,awayVenueScored:awayVenue.count?awayVenue.scored/awayVenue.count:null,awayVenueConceded:awayVenue.count?awayVenue.conceded/awayVenue.count:null,venueGoalsReady};
 return {breakdown,ms1:Math.round(100*edge*winnerScale),ms0:Math.round(100*draw),ms2:Math.round(100*(1-edge)*winnerScale),note:(h2hData?'İkili rekabet: '+h2hData.home_wins+' ev galibiyeti · '+h2hData.draws+' beraberlik · '+h2hData.away_wins+' dep galibiyeti ('+h2hData.count+' maç). ':'İkili rekabet verisi sınırlı. ')+(venueGoalsReady?'İç/dış saha gol verisi ağırlığı %65. ':'İç/dış saha gol verisi yetersiz; genel ortalamalar kullanıldı. ')+'Model puanı · olasılık değildir'};
}
function matchResultCards(p){
 const entries=[['MS 1','Ev sahibi',p.ms1],['MS 0','Beraberlik',p.ms0],['MS 2','Deplasman',p.ms2]];
 const cards=entries.map(([label,name,score])=>{
  if(!Number.isFinite(score))return '';
  return '<div class="ms-score-item"><b>'+label+'</b><small>'+name+'</small><strong style="color:'+predictionColor(score)+'">'+score+'</strong><small>puan</small></div>';
 }).join('');
 return cards?'<div class="ms-score-grid">'+cards+'</div>':'';
}
function matchResultPanel(p,privateAwayForm,privateTrial){
 const drawRisk=p.ms1!==null&&p.ms0!==null&&Math.abs(p.ms1-p.ms0)<5;
 const drawWarning=drawRisk?'<p style="color:#ffcf56;font-weight:700">⚠️ Beraberlik riski yüksek — MS 1 ile MS 0 arasında 5 puandan az fark var.</p>':'';
 const info=p.breakdown||{};
 const fmt=x=>Number.isFinite(x)?x.toFixed(2):'';
 const general='<div class="inner"><h4>📊 Genel Performans</h4><small>Ev sahibi: attığı '+fmt(info.homeScored)+' / yediği '+fmt(info.homeConceded)+' gol/maç</small><p><small>Deplasman: attığı '+fmt(info.awayScored)+' / yediği '+fmt(info.awayConceded)+' gol/maç</small></p></div>';
 const venue='<div class="inner"><h4>🏟️ İç Saha / Deplasman Performansı</h4><small>Ev sahibi iç saha ('+(info.homeVenueCount||0)+' maç): attığı '+fmt(info.homeVenueScored)+' / yediği '+fmt(info.homeVenueConceded)+' gol/maç</small><p><small>Deplasman dış saha ('+(info.awayVenueCount||0)+' maç): attığı '+fmt(info.awayVenueScored)+' / yediği '+fmt(info.awayVenueConceded)+' gol/maç</small></p><small>'+(info.venueGoalsReady?'Gol karşılaştırmasında iç/dış saha %65, genel %35 ağırlıklı.':'İç/dış saha verisi yetersiz: gol karşılaştırmasında genel ortalama kullanılıyor.')+'</small></div>';
 return '<div class="panel full"><h3>🏆 Maç Sonucu (90 Dakika)</h3>'+matchResultCards(p)+privateTrial+drawWarning+general+venue+privateAwayForm+'<small>'+esc(p.note)+'</small></div>';
}

function predictionColor(p){return p>=80?'#34e981':'#ff7889';}
function analysisView(r, enabled, archive=null, fixture=null) {
const a=r.sections?.home_last5,b=r.sections?.away_last5;
const h=r.sections?.head_to_head_last10;
const venueCount=(section,venue,half)=>{const rows=(section?.venue_games||section?.games||[]).filter(x=>x.venue===venue);return rows.filter(x=>half?(Number.isFinite(x.first_half_scored)&&Number.isFinite(x.first_half_conceded)):true).length;};
const counts={
 home:venueCount(a,'home',false),
 away:venueCount(b,'away',false),
 homeHalf:venueCount(a,'home',true),
 awayHalf:venueCount(b,'away',true)
};
const limitedMatchData=Math.min(...Object.values(counts))<8;
const color=p=>p>=75?'#34e981':p>=50?'#ffcf56':'#ff7889';
const scoreClass=p=>p>=75?'score-green':p>=50?'score-yellow':'score-red';
const metric=(label,value)=>'<div class="metric"><span>'+label+'</span><b>'+value+'</b></div>';
const bar=(label,p)=>{if(p===null)return '';const v=Math.max(0,Math.min(99,Math.round(p)));return '<div class="metric"><span>'+label+'</span><b class="'+scoreClass(v)+'">'+v+' puan</b></div><div class="bar-track"><div class="bar-fill" style="width:'+v+'%;background:'+color(v)+'"></div></div>';};
const valid=s=>s&&s.data_scope!=='season'&&Number.isFinite(s.count)&&s.count>0;
const pct=(s,venue,field)=>{const g=(s?.venue_games||s?.games||[]).filter(x=>x.venue===venue&&Number.isFinite(x[field]));return g.length?Math.round(100*g.filter(x=>x[field]>0).length/g.length):null;};
const goalCountValid=value=>Number.isInteger(value)&&value>=0;
const verifiedVenueGames=(section,venue,scored,conceded)=>
 (section?.venue_games||section?.games||[]).filter(game=>
  game.venue===venue&&goalCountValid(game[scored])&&goalCountValid(game[conceded]));
const homeHalf=verifiedVenueGames(a,'home','first_half_scored','first_half_conceded');
const awayHalf=verifiedVenueGames(b,'away','first_half_scored','first_half_conceded');
const averageHalf=games=>games.reduce((sum,game)=>sum+game.first_half_scored+game.first_half_conceded,0)/games.length;
const lambda=homeHalf.length>=5&&awayHalf.length>=5?(averageHalf(homeHalf)+averageHalf(awayHalf))/2:null;
const fullCounts=[verifiedVenueGames(a,'home','scored','conceded').length,
 verifiedVenueGames(b,'away','scored','conceded').length];
const fullDataReady=(section,count)=>valid(section)&&section.count>=5&&
 goalCountValid(section.scored)&&goalCountValid(section.conceded)&&count>=5;

const poissonOver=(l,k)=>l===null?null:100*(1-Math.exp(-l)*Array.from({length:k+1},(_,i)=>{let factorial=1;for(let j=2;j<=i;j++)factorial*=j;return Math.pow(l,i)/factorial;}).reduce((x,y)=>x+y,0));
const fullLambda=fullDataReady(a,fullCounts[0])&&fullDataReady(b,fullCounts[1])?((a.scored+a.conceded)/a.count+(b.scored+b.conceded)/b.count)/2:null;
const avg=(s,field)=>valid(s)?(s[field]/s.count):null;
const fmtAvg=v=>v===null?'':v.toFixed(2).replace('.',',');
const goalValueColor=v=>v===null?'':v>1?'score-green':v<1?'score-red':'';
const halfRows=[[r.home,'home','İç saha',homeHalf],[r.away,'away','Deplasman',awayHalf]]
 .filter(([, , ,games])=>games.length).map(([team,side,venue,games])=>{
  const scored=games.reduce((sum,game)=>sum+game.first_half_scored,0);
  const conceded=games.reduce((sum,game)=>sum+game.first_half_conceded,0);
  return '<tr><td><b class="team-name-'+side+'">'+esc(team)+'</b><br><small>'+venue+'</small></td>'+
   '<td>'+games.length+'</td><td>'+scored+'</td><td>'+conceded+'</td>'+
   '<td>'+fmtAvg(scored/games.length)+'</td><td>'+fmtAvg(conceded/games.length)+'</td></tr>';
 }).join('');
const halfMini=halfRows?'<div class="panel half-mini-panel"><h3>⏱ İlk Yarı Gol Analizi</h3>'+
 '<table class="compact-table"><tr><th>Takım</th><th>Maç</th><th>Attı</th><th>Yedi</th><th>Ort. Attı</th><th>Ort. Yedi</th></tr>'+
 halfRows+'</table></div>':'';
const goalsPanel='<div class="panel"><h3>⚽ Gol İstatistikleri (Genel)</h3><table class="compact-table"><tr><th>Takım</th><th>Attı</th><th>Yedi</th><th>Ort. Attı</th><th>Ort. Yedi</th></tr>'+[[r.home,a],[r.away,b]].map(([n,x])=>'<tr><td><b class="team-name-'+(n===r.home?'home':'away')+'">'+esc(n)+'</b></td><td class="'+goalValueColor(avg(x,'scored'))+'">'+(valid(x)?x.scored:'—')+'</td><td class="'+goalValueColor(avg(x,'conceded'))+'">'+(valid(x)?x.conceded:'—')+'</td><td>'+fmtAvg(avg(x,'scored'))+'</td><td>'+fmtAvg(avg(x,'conceded'))+'</td></tr>').join('')+'</table><small>Veri kapsamı: '+(a?.count??0)+' / '+(b?.count??0)+' maç</small></div>';
const venueSummary=(s,venue)=>{const g=(s?.venue_games||s?.games||[]).filter(x=>x.venue===venue).slice(0,5);return g.length?g.filter(x=>x.scored>x.conceded).length+'G '+g.filter(x=>x.scored===x.conceded).length+'B '+g.filter(x=>x.scored<x.conceded).length+'M':'';};
const venuePerformance=(s,venue)=>{const g=(s?.venue_games||s?.games||[]).filter(x=>x.venue===venue&&Number.isFinite(x.scored)&&Number.isFinite(x.conceded)).slice(0,5);if(g.length<5)return '';const wins=g.filter(x=>x.scored>x.conceded).length,losses=g.filter(x=>x.scored<x.conceded).length,draws=g.filter(x=>x.scored===x.conceded).length;if(draws>=3)return '<span class="muted">Performansı dengeli (beraberlik ağırlıklı)</span>';return wins>=3&&wins>losses?'<span class="score-green">Performansı yüksek</span>':losses>=3&&losses>wins?'<span class="score-red">Performansı düşük</span>':'<span class="muted">Performansı dengeli</span>';};
const avgPanel='<div class="panel"><h3>🏠 Kendi Sahası / Deplasman (Son 5)</h3>'+metric('<span class="team-name-home">'+esc(r.home)+'</span> (Ev)',venueSummary(a,'home')+' · '+venuePerformance(a,'home'))+metric('<span class="team-name-away">'+esc(r.away)+'</span> (Dep)',venueSummary(b,'away')+' · '+venuePerformance(b,'away'))+'</div>';
const recentH2hGames=(h?.games||[]).filter(game=>
 /^\d{4}-\d{2}-\d{2}$/.test(game.date)&&goalCountValid(game.home_goals)&&goalCountValid(game.away_goals)
).sort((left,right)=>right.date.localeCompare(left.date)).slice(0,10);
const countH2h=predicate=>recentH2hGames.filter(predicate).length;
const latestH2h={
 count:recentH2hGames.length,
 home_wins:countH2h(game=>game.home_goals>game.away_goals),
 away_wins:countH2h(game=>game.away_goals>game.home_goals),
 draws:countH2h(game=>game.home_goals===game.away_goals),
 over25:countH2h(game=>game.home_goals+game.away_goals>=3),
 kg_var:countH2h(game=>game.home_goals>0&&game.away_goals>0)
};
const drawRate=latestH2h.count?Math.round(100*latestH2h.draws/latestH2h.count):null;
const drawAlert=latestH2h.count>=5&&drawRate>=50;
const h2hNotice=latestH2h.count<10
 ?'<div class="data-warning amber">⚠️ Kendi aralarında oynadığı doğrulanmış maç sayısı yetersiz. <span>'+latestH2h.count+'/10 maç</span></div>'
 :'';
const rivalryLabel=(x)=>{if(!x?.count)return '';const w=Number(x.home_wins)||0,d=Number(x.draws)||0,l=Number(x.away_wins)||0;if(d>=Math.ceil(x.count*.5)||Math.abs(w-l)<=1)return 'İkili rekabet dengeli';return w>l?'Ev sahibi galibiyet üstünlüğü':'Deplasman galibiyet üstünlüğü';};
const rivalryTag=(x)=>!x?.count?'':'<div class="metric"><span>📈 Galibiyet performansı</span><b>'+rivalryLabel(x)+'</b></div>';
const rivalryRecent=(games,venueOnly=false)=>{const sorted=(Array.isArray(games)?games:[]).filter(g=>g&&/^\\d{4}-\\d{2}-\\d{2}/.test(String(g.date||''))&&['home','away','draw'].includes(g.winner)&&(!venueOnly||g.at_home===true)).sort((a,b)=>String(b.date).localeCompare(String(a.date))).slice(0,5);if(!sorted.length)return '';const hw=sorted.filter(g=>g.winner==='home').length,aw=sorted.filter(g=>g.winner==='away').length,d=sorted.length-hw-aw;const label=d>=3||hw===aw?'Dengeli':hw>aw?'Ev sahibi üstün':'Deplasman üstün';const first=sorted[0].winner;let streak=0;if(first!=='draw'){for(const g of sorted){if(g.winner!==first)break;streak++;}}return '<div class="metric"><span>Son '+sorted.length+' ikili maç</span><b>'+hw+'G Ev · '+d+'B · '+aw+'G Dep — '+label+'</b></div>'+(streak>=2?'<div class="metric"><span>🔥 Güncel galibiyet serisi</span><b>'+(first==='home'?'Ev sahibi':'Deplasman')+' üst üste '+streak+' galibiyet</b></div>':'<div class="metric"><span>Güncel galibiyet serisi</span><b>Yok</b></div>');};
const h2hCountRow=(label,count,total=latestH2h.count,threshold=7,percentage=false)=>{
 const green=count>=threshold;
 return '<div class="metric"'+(green?' style="background:#75e8a6;color:#102026;border-radius:5px;padding:5px 8px"':'')+
  '><span>'+label+'</span><b class="'+(green?'':'score-red')+'">'+count+'/'+total+(percentage?' — %'+Math.round(100*count/total):'')+'</b></div>';
};
const h2hPanel='<div class="panel"><h3>🤝 Kendi Aralarındaki Son 10 Doğrulanmış Maç</h3>'+
 (latestH2h.count?'<div class="metric"><span class="team-name-home">'+esc(r.home)+': <b>'+latestH2h.home_wins+
 '</b></span><span>Beraberlik: <b>'+latestH2h.draws+'</b></span><span class="team-name-away">'+esc(r.away)+': <b>'+latestH2h.away_wins+
 '</b></span></div>'+metric('🤝 Beraberlik oranı','%'+drawRate+' ('+latestH2h.draws+'/'+latestH2h.count+')')+
 h2hCountRow('2,5 Üst',latestH2h.over25)+h2hCountRow('KG Var',latestH2h.kg_var)+
 (drawAlert?'<div class="recommend">⚠️ Beraberlik eğilimi yüksek — dikkat!</div>':'')+
 rivalryTag(latestH2h)+'<small>'+latestH2h.count+' doğrulanmış geçmiş karşılaşma. Geçmiş oranlar tahmin garantisi değildir.</small>'
 :'<small>Doğrulanmış geçmiş eşleşme bulunamadı.</small>')+h2hNotice+'</div>';
const venueH=h?.venue_last5;
const venueHPanel='<div class="panel"><h3>🏟 Kendi Aralarında Ev Sahibinin Sahasında (Son 5)</h3>'+(venueH?.count<5?'<div class="data-warning '+(venueH?.count<3?'red':'amber')+'">⚠️ SINIRLI İÇ SAHA REKABET VERİSİ <span>Bulunan: '+(venueH?.count||0)+' / 5 maç</span></div>':'')+(venueH?.count?
metric(esc(r.home)+' galibiyet',venueH.home_wins)+metric('Beraberlik',venueH.draws)+metric(esc(r.away)+' galibiyet',venueH.away_wins)+rivalryTag(venueH)+rivalryRecent(h?.games,true)+
h2hCountRow('⚽ 2,5 Üst',venueH.over25,venueH.count,4,true)+
h2hCountRow('🤝 KG Var',venueH.kg_var,venueH.count,4,true)+
'<small>'+venueH.count+'/5 doğrulanmış karşılaşma. Üst ve KG Var oranları yalnızca bu sahadaki ikili maçlara dayanır; tahmin garantisi değildir.</small>':
'<small>Bu sahada doğrulanmış karşılaşma bulunamadı.</small>')+'</div>';
const homeAttack=avg(a,'scored'),awayConcede=avg(b,'conceded'),awayAttack=avg(b,'scored'),homeConcede=avg(a,'conceded');
const comparePanel='<div class="panel"><h3>📊 Karşılaştırmalı Analiz (90 Dakika)</h3>'+[['🏠 Ev sahibi gol atma (Ort.)',homeAttack],['🏠 Ev sahibi gol yeme (Ort.)',homeConcede],['✈️ Deplasman gol atma (Ort.)',awayAttack],['✈️ Deplasman gol yeme (Ort.)',awayConcede]].map(([n,v])=>'<div class="metric"><span>'+n+'</span><b class="'+goalValueColor(v)+'">'+fmtAvg(v)+'</b></div><div class="bar-track"><div class="bar-fill" style="width:'+(v===null?0:Math.min(100,v/2*100))+'%;background:'+(v===null?'#68798e':v<0.85?'#ff7c99':v>=1.25?'#43e982':'#ffe05a')+'"></div></div>').join('')+'<small>Genel maç ortalaması; ilk yarı ortalaması değildir.</small></div>';
const homeHalfAttack=pct(a,'home','first_half_scored'),awayHalfDefense=pct(b,'away','first_half_conceded');
const awayHalfAttack=pct(b,'away','first_half_scored'),homeHalfDefense=pct(a,'home','first_half_conceded');
const homeDefenseRisk=homeHalfAttack!==null&&awayHalfDefense!==null&&homeHalfAttack>75&&awayHalfDefense<40;
const awayDefenseRisk=awayHalfAttack!==null&&homeHalfDefense!==null&&awayHalfAttack>75&&homeHalfDefense<40;
const defenseRiskCount=Number(homeDefenseRisk)+Number(awayDefenseRisk);
const halfScore=poissonOver(lambda,0),adjustedHalfScore=halfScore===null?null:Math.max(0,halfScore-15*defenseRiskCount),generalScore=poissonOver(fullLambda,1);
const scores={over15:generalScore,homeHalf:homeHalf.length>=5?Math.round(100*homeHalf.filter(game=>game.first_half_scored>0).length/homeHalf.length):null,awayHalf:awayHalf.length>=5?Math.round(100*awayHalf.filter(game=>game.first_half_scored>0).length/awayHalf.length):null,half05:adjustedHalfScore,half15:poissonOver(lambda,1)};
const championsRule=r.champions_league_data_rule===true;
let championsHalfRisk=false,championsHomeHalfRisk=false;
let championsFullCounts=null,halfCounts=[homeHalf.length,awayHalf.length];
if(championsRule){
 const kickoffDay=r.date.slice(0,10);
 const year=Number(kickoffDay.slice(0,4));
 const seasonStart=(year-(Number(kickoffDay.slice(5,7))<7))+'-07-01';
 const venueResults=(section,venue)=>(section?.venue_games||section?.games||[])
  .filter(row=>row.champions_league===true&&row.venue===venue&&row.date>=seasonStart&&row.date<kickoffDay)
  .sort((left,right)=>right.date.localeCompare(left.date));
 const latestWithScores=(rows,scored,conceded)=>rows.filter(row=>
  [row[scored],row[conceded]].every(goals=>Number.isInteger(goals)&&goals>=0)).slice(0,5);
 const homeRows=venueResults(a,'home'),awayRows=venueResults(b,'away');
 const fullHome=latestWithScores(homeRows,'scored','conceded');
 const fullAway=latestWithScores(awayRows,'scored','conceded');
 const halfHome=latestWithScores(homeRows,'first_half_scored','first_half_conceded');
 const halfAway=latestWithScores(awayRows,'first_half_scored','first_half_conceded');
 championsFullCounts=[fullHome.length,fullAway.length];
 halfCounts=[halfHome.length,halfAway.length];
 const averageTotal=(rows,scored,conceded)=>rows.reduce((sum,row)=>sum+row[scored]+row[conceded],0)/rows.length;
 const rate=(rows,field)=>100*rows.filter(row=>row[field]>0).length/rows.length;
 scores.over15=fullHome.length===5&&fullAway.length===5
  ?poissonOver((averageTotal(fullHome,'scored','conceded')+averageTotal(fullAway,'scored','conceded'))/2,1):null;
 scores.homeHalf=null;
 scores.half05=null;
 if(halfHome.length===5&&halfAway.length===5){
  const homeAttackRate=rate(halfHome,'first_half_scored');
  const awayConcedeRate=rate(halfAway,'first_half_conceded');
  const homeRisk=homeAttackRate>75&&awayConcedeRate<40;
  const awayRisk=rate(halfAway,'first_half_scored')>75&&rate(halfHome,'first_half_conceded')<40;
  const halfMean=(averageTotal(halfHome,'first_half_scored','first_half_conceded')+
   averageTotal(halfAway,'first_half_scored','first_half_conceded'))/2;
  scores.homeHalf=(homeAttackRate+awayConcedeRate)/2;
  scores.half05=Math.max(0,poissonOver(halfMean,0)-15*(Number(homeRisk)+Number(awayRisk)));
  championsHalfRisk=homeRisk||awayRisk;
  championsHomeHalfRisk=homeRisk;
 }
}
const msResult=matchResultScores(a,b,h);
const verifiedAwayResults=verifiedVenueGames(b,'away','scored','conceded')
 .filter(game=>!r.date||!game.date||game.date.slice(0,10)<r.date.slice(0,10))
 .sort((left,right)=>String(right.date||'').localeCompare(String(left.date||''))).slice(0,5);
const awayScoreless=verifiedAwayResults.filter(game=>game.scored===0).length;
const scorelessAdjustment=verifiedAwayResults.length===5&&awayScoreless>=3&&Number.isFinite(msResult.ms1);
if(scorelessAdjustment){
 msResult.ms1=Math.min(100,msResult.ms1+3);
 msResult.ms0=Math.max(0,msResult.ms0-3);
}
const privateAwayForm=enabled===null&&verifiedAwayResults.length
 ?'<div class="inner">'+metric(esc(r.away)+' · Gol atamadığı deplasman maçı',
 awayScoreless+'/'+verifiedAwayResults.length)+'<small>'+
 (scorelessAdjustment?'MS 1 +3 puan · MS 0 −3 puan':verifiedAwayResults.length<5?'Puan etkisi için 5 doğrulanmış deplasman maçı gerekli.':'Puan etkisi için en az 3/5 gerekli.')+'</small></div>'
 :'';
scores.ms1=msResult.ms1;scores.ms0=msResult.ms0;scores.ms2=msResult.ms2;
const riskFlag=(homeAttack!==null&&homeAttack<1)||(awayConcede!==null&&awayConcede<1)||lambda===null||defenseRiskCount>0;
const recommended=[['1,5 Üst',championsRule?null:generalScore],['2,5 Alt',fullLambda===null?null:100-poissonOver(fullLambda,2)],['İY 0,5 Üst',championsRule?null:adjustedHalfScore],['İY 1,5 Üst',poissonOver(lambda,1)]].filter(x=>x[1]!==null).sort((x,y)=>y[1]-x[1]);
const safest=recommended.find(x=>!riskFlag||x[0]!=='İY 0,5 Üst')||recommended[0];
const msOptions=[['MS 1',msResult.ms1],['MS 0',msResult.ms0],['MS 2',msResult.ms2]].filter(x=>Number.isFinite(x[1])).sort((a,b)=>b[1]-a[1]);
const msLeader=msOptions[0],msRisk=msOptions[1];
const msClose=msLeader&&msRisk&&(msLeader[1]-msRisk[1]<5);
const msSummary=msLeader?'<div class="inner"><h4>🏆 Maç Sonucu Önerisi</h4><div class="metric"><span>En yüksek MS puanı</span><b style="color:'+(msLeader[1]>50?'#34e981':'#ff7889')+'">'+(msClose?'⚠️ ':'')+msLeader[0]+' ('+msLeader[1]+' puan)</b></div></div>':'';
const homeAttackAvg=avg(a,'scored'),homeDefenseAvg=avg(a,'conceded');
const awayAttackAvg=avg(b,'scored'),awayDefenseAvg=avg(b,'conceded');
const goalDataReady=[homeAttackAvg,homeDefenseAvg,awayAttackAvg,awayDefenseAvg].every(Number.isFinite)&&a.count>=5&&b.count>=5;
const homeGoalEdge=goalDataReady?(homeAttackAvg+awayDefenseAvg-awayAttackAvg-homeDefenseAvg)/2:null;
const goalConflict=goalDataReady&&msLeader&&((msLeader[0]==='MS 1'&&homeGoalEdge<=-0.35)||(msLeader[0]==='MS 2'&&homeGoalEdge>=0.35)||(msLeader[0]==='MS 0'&&Math.abs(homeGoalEdge)>=0.75));
const goalConflictWarning=goalConflict?'<div class="inner" style="border:2px solid #ef4444;background:rgba(220,38,38,.12);padding:12px;border-radius:8px;margin-top:12px"><h4 style="color:#ff6b6b">⚠️ SİSTEM ÖNERİSİNDE GOL VERİSİ TUTARSIZLIĞI</h4><p>Önerilen '+msLeader[0]+' sonucu, takımların gol atma ve gol yeme ortalamalarıyla çelişiyor. Bu nedenle maç sonucu önerisi riskli olabilir; yalnızca MS puanına dayanarak karar vermeyin.</p><p><small>Ev sahibi: maç başına '+homeAttackAvg.toFixed(2)+' gol atıyor, '+homeDefenseAvg.toFixed(2)+' gol yiyor. Deplasman: maç başına '+awayAttackAvg.toFixed(2)+' gol atıyor, '+awayDefenseAvg.toFixed(2)+' gol yiyor.</small></p><small>Gol verilerinin işaret ettiği taraf: '+(homeGoalEdge>0?'Ev sahibi': 'Deplasman')+'. Bu karşılaştırma kesin maç sonucu değildir.</small></div>':'';

const over25Score=poissonOver(fullLambda,2);
const limitedMsData=(h?.venue_last5?.count??0)<3;
const requiredScores=[msResult.ms1,msResult.ms0,msResult.ms2,over25Score,scores.half05];
if(championsRule)requiredScores.push(scores.over15,scores.homeHalf);
const insufficientSystemData=requiredScores.some(score=>!Number.isFinite(score));
const showMissingDataRibbon=insufficientSystemData||limitedMatchData||limitedMsData;
const msReady=fullCounts.every(count=>count>=5)&&!limitedMsData;
const marketReady={
 over15:Number.isFinite(scores.over15),
 homeHalf:Number.isFinite(scores.homeHalf),
 awayHalf:Number.isFinite(scores.awayHalf),
 half05:Number.isFinite(scores.half05),
 half15:Number.isFinite(scores.half15),
 ms1:msReady&&Number.isFinite(scores.ms1),
 ms0:msReady&&Number.isFinite(scores.ms0),
 ms2:msReady&&Number.isFinite(scores.ms2)
};
const marketRisk={
 half05:championsRule?championsHalfRisk:riskFlag,
 homeHalf:championsRule?championsHomeHalfRisk:homeDefenseRisk,
 awayHalf:awayDefenseRisk,
 ms1:msLeader?.[0]==='MS 1'&&Boolean(msClose||goalConflict),
 ms0:msLeader?.[0]==='MS 0'&&Boolean(msClose||goalConflict),
 ms2:msLeader?.[0]==='MS 2'&&Boolean(msClose||goalConflict)
};
const optionRow=(market,label,score,extraRisk=false,archiveOption=true)=>{
 const points=Number.isFinite(score)?Math.round(score):null;
 if(points===null)return '';
 const green=points>=80&&!extraRisk;
 if(archiveOption&&archive&&market&&green&&points>80&&!showMissingDataRibbon)archive[market]=points;
 const background=green?'#75e8a6':'#ff858e';
 const status=points+' puan'+(extraRisk?' · Riskli':'');
 return '<div style="margin:3px 0;padding:3px 7px;border-radius:5px;background:'+background+';color:#101826"><div style="display:flex;justify-content:space-between;align-items:center;gap:6px"><span>'+label+'</span><b style="text-align:right">'+status+'</b></div></div>';
};
if(msLeader&&!limitedMsData)optionRow(msLeader[0],msLeader[0],msLeader[1],Boolean(msClose||goalConflict));
const recommendedStatus=safest?optionRow(safest[0],'⚽ '+safest[0],safest[1],Boolean(riskFlag&&safest[0]==='İY 0,5 Üst')):'';
const extraFullStatus=!championsRule&&safest?.[0]!=='1,5 Üst'
 ?optionRow(null,'⚽ 90 dk 1,5 Üst',scores.over15,false,false):'';
const over25Status=optionRow('2,5 Üst','⚽ 2,5 Üst',over25Score);
const championsOption=(market,label,key,risk=false)=>optionRow(market,label,scores[key],risk);
const half05Status=championsRule
 ?championsOption('İY 0,5 Üst','⏱️ İlk Yarı 0,5 Üst','half05',championsHalfRisk)
 :optionRow('İY 0,5 Üst','⏱️ İlk Yarı 0,5 Üst',adjustedHalfScore,Boolean(riskFlag));
const championsStatus=championsRule
 ?championsOption('1,5 Üst','⚽ 90 dk 1,5 Üst','over15')+
  championsOption(null,'Ev ilk yarı gol atar','homeHalf',championsHomeHalfRisk)
 :'';
const systemTeams=esc(r.home)+' - '+esc(r.away);
const systemMsCards=[['MS 1',msResult.ms1],['MS 0',msResult.ms0],['MS 2',msResult.ms2]]
 .filter(([,score])=>msReady&&Number.isFinite(score)).map(([label,score])=>{
 const risky=msLeader?.[0]===label&&Boolean(msClose||goalConflict);
 const background=score>=80&&!risky?'#75e8a6':'#ff858e';
 return '<div style="padding:4px;text-align:center;border-radius:5px;background:'+background+';color:#101826"><div>'+label+'</div><strong>'+score+'</strong>'+(risky?'<small style="display:block;color:inherit">Riskli</small>':'')+'</div>';
}).join('');
const missingDataRibbon=showMissingDataRibbon?'<div class="missing-data-ribbon" aria-hidden="true">EKSİK VERİ</div>':'';
const systemPanel=!(recommendedStatus||extraFullStatus||over25Status||half05Status||championsStatus||systemMsCards)?'':'<div class="panel full system-panel'+(showMissingDataRibbon?' has-missing-data':'')+'" style="border-width:1px;padding:7px"><h3 style="display:flex;justify-content:space-between;align-items:center;gap:8px"><span>🎯 Sistem Önerisi</span>' +'</h3><div class="inner"><h4>⚽ '+systemTeams+'</h4>'+recommendedStatus+extraFullStatus+over25Status+half05Status+championsStatus+'<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4px;margin-top:5px">'+systemMsCards+'</div></div><small>Yeşil: ilgili tahminin verisi yeterli, model puanı 80 veya üzeri ve risk kontrolü uygun. Eksik Veri uyarısı maçın diğer analizlerini de kapsar. Model puanı başarı garantisi değildir.</small>'+goalConflictWarning+missingDataRibbon+'</div>';

const trialVotes=[0,0,0];
let privateDefense='';
if(enabled===null){
 const home=msResult.breakdown?.homeVenueConceded,away=msResult.breakdown?.awayVenueConceded;
 const display=value=>value.toFixed(2).replace('.',',');
 const comparable=Boolean(msResult.breakdown?.venueGoalsReady);
 const leader=comparable&&display(home)!==display(away)?(home<away?r.home:r.away):null;
 if(leader!==null)trialVotes[home<away?0:2]++;
 privateDefense='<div class="inner"><h4>Savunma karşılaştırması</h4>'+
  (comparable?metric(esc(r.home)+' · İç sahada yediği gol/maç',display(home))+
   metric(esc(r.away)+' · Deplasmanda yediği gol/maç',display(away))+
   '<small>'+(leader?'Savunma avantajı: '+esc(leader):'Gol yeme ortalamaları eşit.')+'</small>'
   :'<small>Karşılaştırma için iki tarafta da en az üç doğrulanmış maç gerekli.</small>')+'</div>';
}
let privateForm='';
if(enabled===null){
 const formScores=[];
 const form=(name,section)=>{
  const games=(section?.games||[]).filter(game=>
   goalCountValid(game.scored)&&goalCountValid(game.conceded)&&
   (!r.date||!game.date||game.date.slice(0,10)<r.date.slice(0,10)))
   .sort((left,right)=>String(right.date||'').localeCompare(String(left.date||''))).slice(0,5);
  if(games.length<5){formScores.push(null);return '';}
  const wins=games.filter(game=>game.scored>game.conceded).length;
  const draws=games.filter(game=>game.scored===game.conceded).length;
  const losses=5-wins-draws;
  const points=3*wins+draws-losses;
  formScores.push(points);
  return metric(esc(name),wins+'G · '+draws+'B · '+losses+'M · '+points+' puan');
 };
 privateForm='<div class="inner"><h4>Son 5 maç · Form puanı</h4>'+form(r.home,a)+form(r.away,b)+
  '<small>Galibiyet +3 · Beraberlik +1 · Mağlubiyet −1</small></div>';
 if(formScores.every(Number.isFinite)&&formScores[0]!==formScores[1])trialVotes[formScores[0]>formScores[1]?0:2]++;
}
const rivalryPoints=(title,record,venue=false)=>{
 const header='<div class="inner"><h4>'+title+'</h4>';
 if(!record?.count||![record.home_wins,record.draws,record.away_wins].every(goalCountValid))
  return '';
 const results=[[r.home,record.home_wins],['Beraberlik',record.draws],[r.away,record.away_wins]];
 const most=Math.max(...results.map(([,count])=>count));
 const leaders=results.filter(([,count])=>count===most);
 if(leaders.length===1)trialVotes[results.indexOf(leaders[0])]++;
 const summary=leaders.length===1?'En çok çıkan sonuç: '+esc(leaders[0][0]):'En yüksek sayılar eşit.';
 const sample=venue?record.count+'/5 doğrulanmış maç':record.count+' doğrulanmış maç';
 return header+results.map(([name,count])=>metric(esc(name),count+' puan')).join('')+
  '<small>'+sample+' · '+summary+'</small></div>';
};
const privateRivalry=enabled===null
 ?rivalryPoints('Doğrulanmış ikili maçlar · Sonuç puanı',h)+
  rivalryPoints('Ev sahibinin sahasında · Son 5 ikili maç',h?.venue_last5,true)
 :'';
let privateTrial='';
if(enabled===null){
 const reported=fixture?.merged_scores??fixture?.verified_scores??{};
 const regular=fixture?.status==='FINISHED'&&fixture.score?.duration==='REGULAR'?fixture.score:null;
 const pair=score=>Array.isArray(score)&&score.length===2&&score.every(goalCountValid)?score:null;
 const full=pair(reported.full)??pair([regular?.fullTime?.home,regular?.fullTime?.away]);
 const halfCandidate=pair(reported.half)??pair([regular?.halfTime?.home,regular?.halfTime?.away]);
 const half=full&&halfCandidate?.every((goals,index)=>goals<=full[index])?halfCandidate:null;
 const labels=['MS 1','MS 0','MS 2'];
 const max=Math.max(...trialVotes);
 const leading=trialVotes.filter(vote=>vote===max).length===1?trialVotes.indexOf(max):-1;
 const actual=full?(full[0]===full[1]?1:full[0]>full[1]?0:2):-1;
 const comparison=leading<0?'Belirgin sonuç yok':labels[leading]+(actual<0?'':actual===leading?' · Tuttu':' · Yattı');
 const attack=leading===0?a:leading===2?b:null;
 const warning=valid(attack)&&goalCountValid(attack.scored)&&attack.scored<attack.count
  ?'<p class="data-warning red">⚠️ Hücum uyarısı · '+esc(leading===0?r.home:r.away)+' '
   +attack.count+' maçta '+attack.scored+' gol attı ('+(attack.scored/attack.count).toFixed(2).replace('.',',')+' gol/maç).</p>'
  :'';
 const existingScores=[msResult.ms1,msResult.ms0,msResult.ms2];
 const scoreCells=labels.map((label,index)=>{
  const existing=existingScores[index];
  return '<div class="ms-score-item"><b>'+label+'</b>'+
   (Number.isFinite(existing)?'<small>Mevcut: '+existing+'/100</small>':'')+'<strong>'+
   trialVotes[index]+'/4</strong><small>Deneme</small></div>';
 }).join('');
 const result=full?full.join('–')+' · '+labels[actual]:'Sonuç bekleniyor';
 privateTrial='<div class="inner"><h4>MS Puan Karşılaştırması</h4><div class="ms-score-grid">'+
  scoreCells+'</div>'+metric('Maç sonucu',result)+'<small>Deneme: '+comparison+
  (half?' · İlk yarı '+half.join('–'):'')+'</small>'+warning+
  '<details style="margin-top:8px"><summary>Dört kriterin dayanağı</summary>'+
  privateDefense+privateForm+privateRivalry+'</details></div>';
}
const panels={system:systemPanel,goals:valid(a)||valid(b)?goalsPanel:'',averages:counts.home||counts.away?avgPanel:'',h2h:h2hPanel,venue:venueH?.count?venueHPanel:"",halftime:halfMini,comparison:comparePanel,result:matchResultPanel(msResult,privateAwayForm,privateTrial)};
const hasAnalysisData=[scores.ms1, scores.over15, scores.half05, scores.half15].some(Number.isFinite);
const all=enabled===null;
if(!all){
 for(const key of Object.keys(scores)){
  const msKey=key.startsWith('ms');
  const visible=msKey?enabled.includes('result')||enabled.includes('system'):
    ['homeHalf','awayHalf'].includes(key)?enabled.includes('halftime')||
     (championsRule&&key==='homeHalf'&&enabled.includes('system')):enabled.includes('system');
  if(!visible)delete scores[key];
 }
}
return {
 html:Object.entries(panels).filter(([key])=>all||enabled.includes(key)).map(([,html])=>html).join(''),
 scores,
 marketReady:Object.fromEntries(Object.keys(scores).map(key=>[key,marketReady[key]&&!marketRisk[key]])),
 insufficient:Object.keys(scores).filter(key=>scores[key]===null),
 missingData:showMissingDataRibbon,
 hasAnalysisData,
 ...(all?{counts}:{})
};
}
