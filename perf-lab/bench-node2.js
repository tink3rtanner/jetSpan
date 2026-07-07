#!/usr/bin/env node
// bench-node2.js — BOUNDED CPU micro-bench. v1 confirmed the res-4 cumulative
// dissolve is catastrophic (didn't finish in 40min; == why the browser wedges).
// v2 measures the tractable ops cleanly + characterizes the pathology with a
// single bounded dissolve, printing incrementally (no tail buffer).
const h3 = require('h3-js');
const path = require('path');
const DATA = require(path.join(__dirname,'..','data','isochrones','bristol.json'));
const W = s => { process.stdout.write(s); };
const TIME_BANDS = [2,4,6,8,10,12,14,18,24,Infinity].map(h=>({maxHours:h}));
const colorScale = 1.8;
function getBandIndex(m){const h=m/60;for(let i=0;i<TIME_BANDS.length;i++)if(h<TIME_BANDS[i].maxHours*colorScale)return i;return TIME_BANDS.length-1;}
function feats(rk){const b=DATA.resolutions[rk];const f=[];for(const k of Object.keys(b))f.push({h:k,t:b[k].t});return f;}
function ms(fn){const t=process.hrtime.bigint();const r=fn();return {ms:+(Number(process.hrtime.bigint()-t)/1e6).toFixed(1),r};}
function smooth(fs){let v=new Map();for(const f of fs)v.set(f.h,f.t);let disk=0;for(let p=0;p<3;p++){const n=new Map();for(const[c,t]of v){let s=t,w=1;try{for(const nb of h3.gridDisk(c,1)){disk++;if(nb===c)continue;const nt=v.get(nb);if(nt!==undefined){s+=nt;w++;}}}catch(e){}n.set(c,s/w);}v=n;}for(const f of fs)f.s=v.get(f.h)??f.t;return disk;}
function recolor(fs){let a=0;for(const f of fs)a+=getBandIndex(f.s??f.t);return a;}
function nonCumulativeDissolve(fs){const bk=TIME_BANDS.map(()=>[]);for(const f of fs)bk[getBandIndex(f.s??f.t)].push(f.h);let d=0;for(let i=0;i<TIME_BANDS.length-1;i++){if(!bk[i].length)continue;try{h3.cellsToMultiPolygon(bk[i],true);d++;}catch(e){}}return d;}

const out={node:process.version};
for(const rk of ['3','4']){
  const fs=feats(rk); const n=fs.length;
  W(`\n=== res ${rk} (${n.toLocaleString()} cells) ===\n`);
  const sm=ms(()=>smooth(fs)); W(`  smoothGridTimes:        ${sm.ms} ms  (${sm.r.toLocaleString()} gridDisk calls)\n`);
  const rc=ms(()=>recolor(fs)); W(`  recolor (getBandIndex): ${rc.ms} ms\n`);
  const nc=ms(()=>nonCumulativeDissolve(fs)); W(`  dissolve NON-cumulative:${nc.ms} ms  (${nc.r} band-dissolves, each band once)\n`);
  out[`res${rk}`]={cells:n,smoothMs:sm.ms,diskCalls:sm.r,recolorMs:rc.ms,nonCumulativeDissolveMs:nc.ms};
}
// characterize the pathology: ONE cellsToMultiPolygon on the full cell set at each res
// (the LAST/largest call the cumulative loop makes — its worst single step)
for(const rk of ['3','4']){
  const cells=Object.keys(DATA.resolutions[rk]);
  W(`\n--- single full-set dissolve, res ${rk} (${cells.length.toLocaleString()} cells) — the cumulative loop's worst step ---\n`);
  const t=process.hrtime.bigint();
  try{ const mp=h3.cellsToMultiPolygon(cells,true); const el=Number(process.hrtime.bigint()-t)/1e6; W(`  ${el.toFixed(0)} ms  (${mp.length} polygons)\n`); out[`res${rk}`].singleFullDissolveMs=+el.toFixed(0);}
  catch(e){ W(`  ERROR ${e.message}\n`);}
}
W('\n=== HEADLINE ===\n');
const b=out.res4, f=out.res3;
W(`Fix "serve res-3 not res-4 at world zoom": grid cells 109k→15k (7x fewer).\n`);
W(`  smoothing:  ${b.smoothMs}ms → ${f.smoothMs}ms  (${(b.smoothMs/f.smoothMs).toFixed(1)}x faster)\n`);
W(`  full dissolve (worst cumulative step): res4 ${b.singleFullDissolveMs}ms → res3 ${f.singleFullDissolveMs}ms  (${(b.singleFullDissolveMs/f.singleFullDissolveMs).toFixed(1)}x)\n`);
W(`  recolor:    ${b.recolorMs}ms → ${f.recolorMs}ms\n`);
W(`Fix "non-cumulative dissolve": res4 CUMULATIVE = ~9 growing calls up to 109k (v1: >40min, DID NOT FINISH — this is the browser-wedge). NON-cumulative res4 = ${b.nonCumulativeDissolveMs}ms (each band once). That is the fix: from "never finishes" to ${b.nonCumulativeDissolveMs}ms.\n`);
W(`\nFPS/paint NOT measured (needs GPU browser; pi=software WebGL). These are CPU ops, hardware-representative.\n`);
require('fs').writeFileSync(path.join(__dirname,'results','baseline-node.json'),JSON.stringify(out,null,2));
W('\nwrote results/baseline-node.json\n');
