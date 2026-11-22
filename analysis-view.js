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
function matchResultPanel(p){
 const entries=[['MS 1',p.ms1],['MS 0',p.ms0],['MS 2',p.ms2]];
 const scoreCards=entries.map(([label,v])=>'<div class="ms-score-item"><b>'+label+'</b><strong style="color:'+(v===null?'#aebcd2':predictionColor(v))+'">'+(v===null?'—':v)+'</strong><small>'+(v===null?'Veri yok':'puan')+'</small></div>').join('');
 const drawRisk=p.ms1!==null&&p.ms0!==null&&Math.abs(p.ms1-p.ms0)<5;
 const drawWarning=drawRisk?'<p style="color:#ffcf56;font-weight:700">⚠️ Beraberlik riski yüksek — MS 1 ile MS 0 arasında 5 puandan az fark var.</p>':'';
 const info=p.breakdown||{};
 const fmt=x=>Number.isFinite(x)?x.toFixed(2):'Veri yok';
 const general='<div class="inner"><h4>📊 Genel Performans</h4><small>Ev sahibi: attığı '+fmt(info.homeScored)+' / yediği '+fmt(info.homeConceded)+' gol/maç</small><p><small>Deplasman: attığı '+fmt(info.awayScored)+' / yediği '+fmt(info.awayConceded)+' gol/maç</small></p></div>';
 const venue='<div class="inner"><h4>🏟️ İç Saha / Deplasman Performansı</h4><small>Ev sahibi iç saha ('+(info.homeVenueCount||0)+' maç): attığı '+fmt(info.homeVenueScored)+' / yediği '+fmt(info.homeVenueConceded)+' gol/maç</small><p><small>Deplasman dış saha ('+(info.awayVenueCount||0)+' maç): attığı '+fmt(info.awayVenueScored)+' / yediği '+fmt(info.awayVenueConceded)+' gol/maç</small></p><small>'+(info.venueGoalsReady?'Gol karşılaştırmasında iç/dış saha %65, genel %35 ağırlıklı.':'İç/dış saha verisi yetersiz: gol karşılaştırmasında genel ortalama kullanılıyor.')+'</small></div>';
 return '<div class="panel full"><h3>🏆 Maç Sonucu (90 Dakika)</h3><div class="ms-score-grid">'+scoreCards+'</div>'+drawWarning+general+venue+'<small>'+esc(p.note)+'</small></div>';
}

function predictionColor(p){return p>=80?'#34e981':'#ff7889';}
function analysisView(r, enabled) {
const a=r.sections?.home_last5,b=r.sections?.away_last5;
const h=r.sections?.head_to_head_last10;
const venueCount=(section,venue,half)=>{const rows=(section?.venue_games||section?.games||[]).filter(x=>x.venue===venue);return rows.filter(x=>half?(Number.isFinite(x.first_half_scored)&&Number.isFinite(x.first_half_conceded)):true).length;};
const color=p=>p>=75?'#34e981':p>=50?'#ffcf56':'#ff7889';
const scoreClass=p=>p>=75?'score-green':p>=50?'score-yellow':'score-red';
const metric=(label,value)=>'<div class="metric"><span>'+label+'</span><b>'+value+'</b></div>';
const bar=(label,p)=>{if(p===null)return metric(label,'Veri yok');const v=Math.max(0,Math.min(99,Math.round(p)));return '<div class="metric"><span>'+label+'</span><b class="'+scoreClass(v)+'">'+v+' puan</b></div><div class="bar-track"><div class="bar-fill" style="width:'+v+'%;background:'+color(v)+'"></div></div>';};
const valid=s=>s&&s.data_scope!=='season'&&Number.isFinite(s.count)&&s.count>0;
const pct=(s,venue,field)=>{const g=(s?.venue_games||s?.games||[]).filter(x=>x.venue===venue&&Number.isFinite(x[field]));return g.length?Math.round(100*g.filter(x=>x[field]>0).length/g.length):null;};
const halfCard=(s,venue,field,label)=>{const all=(s?.venue_games||s?.games||[]).filter(x=>x.venue===venue);const g=all.filter(x=>Number.isFinite(x.first_half_scored)&&Number.isFinite(x.first_half_conceded));const hits=g.filter(x=>x[field]>0).length,total=g.reduce((n,x)=>n+x[field],0),p=g.length?Math.round(100*hits/g.length):null;const rows=all.map(x=>'<div class="half-detail-row"><span>'+esc(x.date||'?')+' · '+esc(x.opponent||'?')+'</span><b>'+(Number.isFinite(x.first_half_scored)&&Number.isFinite(x.first_half_conceded)?x.first_half_scored+'-'+x.first_half_conceded:'Skor yok')+'</b></div>').join('');return '<div class="half-mini"><div>'+label+'</div><strong style="color:'+(p===null?'#9aadc4':p>=75?'#4bea8e':'#ffcf56')+'">'+(p===null?'Veri yok':'%'+p)+'</strong><small>'+(p===null?'İlk yarı skoru bulunamadı':hits+'/'+g.length+' maç · '+total+' gol')+'</small><details class="half-detail"><summary>Maçları gör</summary>'+(rows||'<small>Geçmiş maç bulunamadı</small>')+'<small>Skorlar takım açısından: attığı-yediği. Yalnız doğrulanmış ilk yarılar hesaplanır.</small></details></div>';};
const halfMini='<div class="panel half-mini-panel"><h3>⏱ İlk Yarı Gol Analizi</h3><div class="half-mini-grid">'+halfCard(a,'home','first_half_scored','Ev · Atma')+halfCard(b,'away','first_half_scored','Dep · Atma')+halfCard(a,'home','first_half_conceded','Ev · Yeme')+halfCard(b,'away','first_half_conceded','Dep · Yeme')+'</div><small>Ev: yalnız iç saha · Dep: yalnız dış saha · %75+ yeşil</small></div>';
const venueHalf=(s,venue)=>{const g=(s?.games||[]).filter(x=>x.venue===venue&&Number.isFinite(x.first_half_scored)&&Number.isFinite(x.first_half_conceded));return g;};
const homeHalf=venueHalf(a,'home'),awayHalf=venueHalf(b,'away');
const halfAll=[...homeHalf,...awayHalf];


let lambda=null,halfMethod='';
if(homeHalf.length>=2&&awayHalf.length>=2){lambda=(homeHalf.reduce((n,g)=>n+g.first_half_scored+g.first_half_conceded,0)/homeHalf.length+awayHalf.reduce((n,g)=>n+g.first_half_scored+g.first_half_conceded,0)/awayHalf.length)/2;halfMethod='Gerçek ilk yarı verisi';}
else if(halfAll.length>=3){lambda=halfAll.reduce((n,g)=>n+g.first_half_scored+g.first_half_conceded,0)/halfAll.length;halfMethod='Sınırlı ilk yarı verisi';}

const poissonOver=(l,k)=>l===null?null:100*(1-Math.exp(-l)*Array.from({length:k+1},(_,i)=>{let factorial=1;for(let j=2;j<=i;j++)factorial*=j;return Math.pow(l,i)/factorial;}).reduce((x,y)=>x+y,0));
const fullLambda=valid(a)&&valid(b)?((a.scored+a.conceded)/a.count+(b.scored+b.conceded)/b.count)/2:null;
const avg=(s,field)=>valid(s)?(s[field]/s.count):null;
const fmtAvg=v=>v===null?'Veri yok':v.toFixed(2).replace('.',',');
const goalValueColor=v=>v===null?'':v>1?'score-green':v<1?'score-red':'';
const formRow=(name,s,side)=>{const g=(s?.games||[]).slice(0,5);return '<div class="metric form-team-row"><b class="form-team-name team-name-'+side+'">'+esc(name)+'</b><span>'+ (g.length?g.map(x=>{const won=x.scored>x.conceded,draw=x.scored===x.conceded;return '<span class="form-chip '+(won?'form-win':draw?'form-draw':'form-loss')+'">'+(won?'G':draw?'B':'M')+'</span>';}).join(''):'<small>Son 5 sonuç yok</small>')+'</span></div>';};
const teamPanel='<div class="panel"><h3>📊 Son 5 Maç Performansı</h3>'+formRow(r.home,a,'home')+formRow(r.away,b,'away')+'<small>Yalnızca doğrulanmış maç sonuçları</small></div>';
const goalsPanel='<div class="panel"><h3>⚽ Gol İstatistikleri (Genel)</h3><table class="compact-table"><tr><th>Takım</th><th>Attı</th><th>Yedi</th><th>Ort. Attı</th><th>Ort. Yedi</th></tr>'+[[r.home,a],[r.away,b]].map(([n,x])=>'<tr><td><b class="team-name-'+(n===r.home?'home':'away')+'">'+esc(n)+'</b></td><td class="'+goalValueColor(avg(x,'scored'))+'">'+(valid(x)?x.scored:'—')+'</td><td class="'+goalValueColor(avg(x,'conceded'))+'">'+(valid(x)?x.conceded:'—')+'</td><td>'+fmtAvg(avg(x,'scored'))+'</td><td>'+fmtAvg(avg(x,'conceded'))+'</td></tr>').join('')+'</table><small>Veri kapsamı: '+(a?.count??0)+' / '+(b?.count??0)+' maç</small></div>';
const venueSummary=(s,venue)=>{const g=(s?.venue_games||s?.games||[]).filter(x=>x.venue===venue).slice(0,5);return g.length?g.filter(x=>x.scored>x.conceded).length+'G '+g.filter(x=>x.scored===x.conceded).length+'B '+g.filter(x=>x.scored<x.conceded).length+'M':'Veri yok';};
const venuePerformance=(s,venue)=>{const g=(s?.venue_games||s?.games||[]).filter(x=>x.venue===venue&&Number.isFinite(x.scored)&&Number.isFinite(x.conceded)).slice(0,5);if(g.length<5)return '<span class="muted">Yetersiz veri</span>';const wins=g.filter(x=>x.scored>x.conceded).length,losses=g.filter(x=>x.scored<x.conceded).length,draws=g.filter(x=>x.scored===x.conceded).length;if(draws>=3)return '<span class="muted">Performansı dengeli (beraberlik ağırlıklı)</span>';return wins>=3&&wins>losses?'<span class="score-green">Performansı yüksek</span>':losses>=3&&losses>wins?'<span class="score-red">Performansı düşük</span>':'<span class="muted">Performansı dengeli</span>';};
const avgPanel='<div class="panel"><h3>🏠 Kendi Sahası / Deplasman (Son 5)</h3>'+metric('<span class="team-name-home">'+esc(r.home)+'</span> (Ev)',venueSummary(a,'home')+' · '+venuePerformance(a,'home'))+metric('<span class="team-name-away">'+esc(r.away)+'</span> (Dep)',venueSummary(b,'away')+' · '+venuePerformance(b,'away'))+'</div>';
const drawRate=h?.count?Math.round(100*h.draws/h.count):null;
const drawAlert=h?.count>=5&&drawRate!==null&&drawRate>=50;
const h2hNotice=h?.count>=5?'':('<div class="data-warning '+(h?.count<5?'red':'amber')+'">⚠️ '+(h?.count<5?'DİKKAT! YETERSİZ İKİLİ REKABET VERİSİ':'SINIRLI İKİLİ REKABET VERİSİ')+' <span>Bulunan: '+(h?.count||0)+' maç · Eksik karşılaşmalar olabilir</span></div>');
const rivalryLabel=(x)=>{if(!x?.count)return 'Veri yok';const w=Number(x.home_wins)||0,d=Number(x.draws)||0,l=Number(x.away_wins)||0;if(d>=Math.ceil(x.count*.5)||Math.abs(w-l)<=1)return 'İkili rekabet dengeli';return w>l?'Ev sahibi galibiyet üstünlüğü':'Deplasman galibiyet üstünlüğü';};
const rivalryTag=(x)=>'<div class="metric"><span>📈 Galibiyet performansı</span><b>'+rivalryLabel(x)+'</b></div>';
const rivalryRecent=(games,venueOnly=false)=>{const sorted=(Array.isArray(games)?games:[]).filter(g=>g&&/^\\d{4}-\\d{2}-\\d{2}/.test(String(g.date||''))&&['home','away','draw'].includes(g.winner)&&(!venueOnly||g.at_home===true)).sort((a,b)=>String(b.date).localeCompare(String(a.date))).slice(0,5);if(!sorted.length)return '<div class="metric"><span>Son 5 ikili maç</span><b>Veri yok</b></div>';const hw=sorted.filter(g=>g.winner==='home').length,aw=sorted.filter(g=>g.winner==='away').length,d=sorted.length-hw-aw;const label=d>=3||hw===aw?'Dengeli':hw>aw?'Ev sahibi üstün':'Deplasman üstün';const first=sorted[0].winner;let streak=0;if(first!=='draw'){for(const g of sorted){if(g.winner!==first)break;streak++;}}return '<div class="metric"><span>Son '+sorted.length+' ikili maç</span><b>'+hw+'G Ev · '+d+'B · '+aw+'G Dep — '+label+'</b></div>'+(streak>=2?'<div class="metric"><span>🔥 Güncel galibiyet serisi</span><b>'+(first==='home'?'Ev sahibi':'Deplasman')+' üst üste '+streak+' galibiyet</b></div>':'<div class="metric"><span>Güncel galibiyet serisi</span><b>Yok</b></div>');};
const h2hPanel='<div class="panel"><h3>🤝 Kendi Aralarındaki Tüm Doğrulanmış Maçlar</h3>'+h2hNotice+(h?.count?'<div class="metric"><span class="team-name-home">'+esc(r.home)+': <b>'+h.home_wins+'</b></span><span>Beraberlik: <b>'+h.draws+'</b></span><span class="team-name-away">'+esc(r.away)+': <b>'+h.away_wins+'</b></span></div><div class="metric"><span>🤝 Beraberlik oranı</span><b>%'+drawRate+' ('+h.draws+'/'+h.count+')</b></div>'+(h.under25!==undefined?'<div class="metric"><span>⚽ 2,5 Alt</span><b>'+h.under25+'/'+h.count+' — %'+Math.round(100*h.under25/h.count)+'</b></div><div class="metric"><span>2,5 Üst</span><b>'+h.over25+'/'+h.count+'</b></div><div class="metric"><span>KG Var / Yok</span><b>'+h.kg_var+' / '+h.kg_yok+'</b></div>':'')+(drawAlert?'<div class="recommend">⚠️ Beraberlik eğilimi yüksek — dikkat!</div>':'')+(h.under25!==undefined&&h.count>=5&&h.under25/h.count>=0.8?'<div class="recommend">⚠️ 2,5 Alt eğilimi yüksek — geçmiş sonuçlara dayalı uyarı.</div>':'')+rivalryTag(h)+rivalryRecent(h.games)+'<small>'+h.count+' doğrulanmış geçmiş karşılaşma. Eksik maçlar tahmin edilmez. Geçmiş oranlar tahmin garantisi değildir.</small>':'<small>Doğrulanmış geçmiş eşleşme bulunamadı.</small>')+'</div>';
const venueH=h?.venue_last5;
const venueHPanel='<div class="panel"><h3>🏟 Kendi Aralarında Ev Sahibinin Sahasında (Son 5)</h3>'+(venueH?.count<5?'<div class="data-warning '+(venueH?.count<3?'red':'amber')+'">⚠️ SINIRLI İÇ SAHA REKABET VERİSİ <span>Bulunan: '+(venueH?.count||0)+' / 5 maç</span></div>':'')+(venueH?.count?
metric(esc(r.home)+' galibiyet',venueH.home_wins)+metric('Beraberlik',venueH.draws)+metric(esc(r.away)+' galibiyet',venueH.away_wins)+rivalryTag(venueH)+rivalryRecent(h?.games,true)+
metric('⚽ 2,5 Alt',venueH.under25+' / '+venueH.count+' — %'+Math.round(100*venueH.under25/venueH.count))+
metric('⚽ 2,5 Üst',venueH.over25+' / '+venueH.count+' — %'+Math.round(100*venueH.over25/venueH.count))+
metric('🤝 KG Var',venueH.kg_var+' / '+venueH.count+' — %'+Math.round(100*venueH.kg_var/venueH.count))+
metric('🚫 KG Yok',venueH.kg_yok+' / '+venueH.count+' — %'+Math.round(100*venueH.kg_yok/venueH.count))+
'<small>'+venueH.count+'/5 doğrulanmış karşılaşma. Alt/Üst ve KG oranları yalnızca bu sahadaki ikili maçlara dayanır; tahmin garantisi değildir.</small>':
'<small>Bu sahada doğrulanmış karşılaşma bulunamadı.</small>')+'</div>';
const homeAttack=avg(a,'scored'),awayConcede=avg(b,'conceded'),awayAttack=avg(b,'scored'),homeConcede=avg(a,'conceded');
const comparePanel='<div class="panel"><h3>📊 Karşılaştırmalı Analiz (90 Dakika)</h3>'+[['🏠 Ev sahibi gol atma (Ort.)',homeAttack],['🏠 Ev sahibi gol yeme (Ort.)',homeConcede],['✈️ Deplasman gol atma (Ort.)',awayAttack],['✈️ Deplasman gol yeme (Ort.)',awayConcede]].map(([n,v])=>'<div class="metric"><span>'+n+'</span><b class="'+goalValueColor(v)+'">'+fmtAvg(v)+'</b></div><div class="bar-track"><div class="bar-fill" style="width:'+(v===null?0:Math.min(100,v/2*100))+'%;background:'+(v===null?'#68798e':v<0.85?'#ff7c99':v>=1.25?'#43e982':'#ffe05a')+'"></div></div>').join('')+'<small>Genel maç ortalaması; ilk yarı ortalaması değildir.</small></div>';
const homeHalfAttack=pct(a,'home','first_half_scored'),awayHalfDefense=pct(b,'away','first_half_conceded');
const awayHalfAttack=pct(b,'away','first_half_scored'),homeHalfDefense=pct(a,'home','first_half_conceded');
const homeDefenseRisk=homeHalfAttack!==null&&awayHalfDefense!==null&&homeHalfAttack>75&&awayHalfDefense<40;
const awayDefenseRisk=awayHalfAttack!==null&&homeHalfDefense!==null&&awayHalfAttack>75&&homeHalfDefense<40;
const defenseRiskCount=Number(homeDefenseRisk)+Number(awayDefenseRisk);
const halfScore=poissonOver(lambda,0),adjustedHalfScore=halfScore===null?null:Math.max(0,halfScore-15*defenseRiskCount),generalScore=poissonOver(fullLambda,1);
const scores={over15:generalScore,homeHalf:pct(a,'home','first_half_scored'),awayHalf:pct(b,'away','first_half_scored'),half05:adjustedHalfScore,half15:poissonOver(lambda,1)};
const msResult=matchResultScores(a,b,h);
scores.ms1=msResult.ms1;scores.ms0=msResult.ms0;scores.ms2=msResult.ms2;
const riskFlag=(homeAttack!==null&&homeAttack<1)||(awayConcede!==null&&awayConcede<1)||lambda===null||defenseRiskCount>0;
const recommended=[['1,5 Üst',generalScore],['2,5 Alt',fullLambda===null?null:100-poissonOver(fullLambda,2)],['İY 0,5 Üst',adjustedHalfScore],['İY 1,5 Üst',poissonOver(lambda,1)]].filter(x=>x[1]!==null).sort((x,y)=>y[1]-x[1]);
const safest=recommended.find(x=>!riskFlag||x[0]!=='İY 0,5 Üst')||recommended[0];
const msOptions=[['MS 1',msResult.ms1],['MS 0',msResult.ms0],['MS 2',msResult.ms2]].filter(x=>Number.isFinite(x[1])).sort((a,b)=>b[1]-a[1]);
const msLeader=msOptions[0],msRisk=msOptions[1];
const msClose=msLeader&&msRisk&&(msLeader[1]-msRisk[1]<5);
const msSummary=msLeader?'<div class="inner"><h4>🏆 Maç Sonucu Önerisi</h4><div class="metric"><span>En yüksek MS puanı</span><b style="color:'+(msLeader[1]>50?'#34e981':'#ff7889')+'">'+(msClose?'⚠️ ':'')+msLeader[0]+' ('+msLeader[1]+' puan)</b></div></div>':'<p>MS önerisi için yeterli veri yok.</p>';
const homeAttackAvg=avg(a,'scored'),homeDefenseAvg=avg(a,'conceded');
const awayAttackAvg=avg(b,'scored'),awayDefenseAvg=avg(b,'conceded');
const goalDataReady=[homeAttackAvg,homeDefenseAvg,awayAttackAvg,awayDefenseAvg].every(Number.isFinite)&&a.count>=5&&b.count>=5;
const homeGoalEdge=goalDataReady?(homeAttackAvg+awayDefenseAvg-awayAttackAvg-homeDefenseAvg)/2:null;
const goalConflict=goalDataReady&&msLeader&&((msLeader[0]==='MS 1'&&homeGoalEdge<=-0.35)||(msLeader[0]==='MS 2'&&homeGoalEdge>=0.35)||(msLeader[0]==='MS 0'&&Math.abs(homeGoalEdge)>=0.75));
const goalConflictWarning=goalConflict?'<div class="inner" style="border:2px solid #ef4444;background:rgba(220,38,38,.12);padding:12px;border-radius:8px;margin-top:12px"><h4 style="color:#ff6b6b">⚠️ SİSTEM ÖNERİSİNDE GOL VERİSİ TUTARSIZLIĞI</h4><p>Önerilen '+msLeader[0]+' sonucu, takımların gol atma ve gol yeme ortalamalarıyla çelişiyor. Bu nedenle maç sonucu önerisi riskli olabilir; yalnızca MS puanına dayanarak karar vermeyin.</p><p><small>Ev sahibi: maç başına '+homeAttackAvg.toFixed(2)+' gol atıyor, '+homeDefenseAvg.toFixed(2)+' gol yiyor. Deplasman: maç başına '+awayAttackAvg.toFixed(2)+' gol atıyor, '+awayDefenseAvg.toFixed(2)+' gol yiyor.</small></p><small>Gol verilerinin işaret ettiği taraf: '+(homeGoalEdge>0?'Ev sahibi': 'Deplasman')+'. Bu karşılaştırma kesin maç sonucu değildir.</small></div>':'';

const over25Score=poissonOver(fullLambda,2);
const optionRow=(label,score,extraRisk=false)=>{
 const points=Number.isFinite(score)?Math.round(score):null;
 const playable=points!==null&&points>80&&!extraRisk;
 const color=playable?'#75e8a6':'#ff858e';
 const status=playable?'🟢 OYNANABİLİR':'🔴 RİSKLİ';
 return '<div class="metric"><span>'+label+'</span><b style="color:'+color+'">'+(points===null?'Veri yetersiz':points+' puan')+' · '+status+'</b></div>';
};
const msStatus=msLeader?optionRow('🏆 '+msLeader[0],msLeader[1],Boolean(msClose||goalConflict)):'';
const recommendedStatus=safest?optionRow('⚽ '+safest[0],safest[1],Boolean(riskFlag&&safest[0]==='İY 0,5 Üst')):'';
const over25Status=optionRow('⚽ 2,5 Üst',over25Score);
const half05Status=optionRow('⏱️ İlk Yarı 0,5 Üst',adjustedHalfScore,Boolean(riskFlag));
const systemTeams=esc(r.home)+' - '+esc(r.away);
const systemPanel='<div class="panel full system-panel"><h3>🎯 Sistem Önerisi</h3><div class="inner"><h4>⚽ '+systemTeams+'</h4><h4>Seçeneklerin ayrı değerlendirmesi</h4>'+msStatus+recommendedStatus+over25Status+half05Status+'</div><small>Yeşil: model puanı 80’in üzerinde ve ilgili risk kontrolü uygun. Kırmızı: düşük puan, yetersiz veri veya risk. Model puanları garanti değildir.</small>'+goalConflictWarning+'</div>';

const panels={system:systemPanel,teams:teamPanel,goals:goalsPanel,averages:avgPanel,h2h:h2hPanel,venue:venueHPanel,halftime:halfMini,comparison:comparePanel,result:matchResultPanel(msResult)};
const all=enabled===null;
if(!all){
 for(const key of Object.keys(scores)){
  const msKey=key.startsWith('ms');
  const visible=msKey?enabled.includes('result')||enabled.includes('system'):
    ['homeHalf','awayHalf'].includes(key)?enabled.includes('halftime'):enabled.includes('system');
  if(!visible)delete scores[key];
 }
}
return {
 html:Object.entries(panels).filter(([key])=>all||enabled.includes(key)).map(([,html])=>html).join(''),
 scores,
 ...(all?{counts:{home:venueCount(a,'home',false),away:venueCount(b,'away',false),homeHalf:venueCount(a,'home',true),awayHalf:venueCount(b,'away',true)}}:{})
};
}
