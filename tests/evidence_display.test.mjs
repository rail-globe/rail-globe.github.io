import nodeTest from 'node:test';
// a check that reads the Seville evidence (actual, feature(), the Seville services) is skipped where it is absent
const test=(name,fn)=>nodeTest(name,!actual&&/actual|feature\(|seville/i.test(String(fn))?{skip:'the Seville evidence is not in the repository'}:{},fn);
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const app=fs.readFileSync(new URL('../src/app.html',import.meta.url),'utf8');
const source=app.slice(app.indexOf('    const slot = '),app.indexOf('    // Colours, widths and opacities of the rail layers'));
const constructor=app.slice(app.indexOf('    const casing = ('),app.indexOf("    // China's: every casing"));
const styler=app.slice(app.indexOf('    function styleMetro()'),app.indexOf("    addEventListener('rail:dim'"));
const picker=app.slice(app.indexOf('    const pick = pt => {'),app.indexOf('    const esc = s =>'));
const visibility=app.slice(app.indexOf('  function applyVisibility()'),app.lastIndexOf('\n})();'));
// the Seville evidence lies beside the working copy, not in the repository: without it these checks are skipped
const evidenceFile=new URL('../../reports/remaining-urban-cases/case-seville-overlay-input.json',import.meta.url);
const actual=fs.existsSync(evidenceFile)?JSON.parse(fs.readFileSync(evidenceFile)).generated_features:null;
const belgium=JSON.parse(fs.readFileSync(new URL('../data/be_metro.geojson',import.meta.url))).features;
const plain=x=>JSON.parse(JSON.stringify(x));
function evaluate(e,p,z){
 if(!Array.isArray(e))return e;
 const v=x=>evaluate(x,p,z),op=e[0];
 if(op==='get')return p[e[1]];
 if(op==='literal')return e[1];
 if(op==='zoom')return z;
 if(op==='within'){const co=p.__coordinates;if(!co)return false;const ring=e[1].coordinates[0],xs=ring.map(p=>p[0]),ys=ring.map(p=>p[1]);return co[0]>Math.min(...xs)&&co[0]<Math.max(...xs)&&co[1]>Math.min(...ys)&&co[1]<Math.max(...ys);}
 if(op==='has')return Object.hasOwn(p,e[1]);
 if(op==='coalesce')return e.slice(1).map(v).find(x=>x!==undefined&&x!==null);
 if(op==='all')return e.slice(1).every(v);
 if(op==='any')return e.slice(1).some(v);
 if(op==='!')return !v(e[1]);
 if(op==='==')return v(e[1])===v(e[2]);
 if(op==='!=')return v(e[1])!==v(e[2]);
 if(op==='in')return v(e[2]).includes(v(e[1]));
 if(op==='<')return v(e[1])<v(e[2]);
 if(op==='>=')return v(e[1])>=v(e[2]);
 if(op==='+')return e.slice(1).map(v).reduce((a,b)=>a+b,0);
 if(op==='*')return e.slice(1).map(v).reduce((a,b)=>a*b,1);
 if(op==='/')return v(e[1])/v(e[2]);
 if(op==='-')return v(e[1])-v(e[2]);
 if(op==='min')return Math.min(...e.slice(1).map(v));
 if(op==='case'){for(let i=1;i<e.length-1;i+=2)if(v(e[i]))return v(e[i+1]);return v(e.at(-1));}
 if(op==='interpolate'){
  const at=v(e[2]),stops=[];for(let i=3;i<e.length;i+=2)stops.push([e[i],v(e[i+1])]);
  if(at<=stops[0][0])return stops[0][1];if(at>=stops.at(-1)[0])return stops.at(-1)[1];
  const k=stops.findIndex(([x])=>x>at),[a,b]=stops[k-1],[c,d]=stops[k];
  const t=e[1][0]==='exponential'?(e[1][1]**(at-a)-1)/(e[1][1]**(c-a)-1):(at-a)/(c-a);return b+(d-b)*t;
 }
 throw Error('Unsupported expression '+op);
}
function harness(){
 const layers=new Map(),state={query:[]};
 const map={addLayer:l=>layers.set(l.id,plain(l)),setPaintProperty:(id,k,v)=>{if(!layers.has(id))layers.set(id,{id,paint:{},layout:{}});layers.get(id).paint[k]=plain(v);},setLayoutProperty:(id,k,v)=>{if(!layers.has(id))layers.set(id,{id,paint:{},layout:{}});layers.get(id).layout[k]=plain(v);},setFilter:()=>{},getLayer:id=>layers.get(id),getLayoutProperty:(id,k)=>layers.get(id)?.layout?.[k],queryRenderedFeatures:(bounds,{layers:shown})=>state.query.filter(f=>shown.includes(f.layer.id)),getZoom:()=>16,project:project};
 const metroLayers=[['es-subway','es','subway',1],['es-urban','es','urban',1],['be-urban','be','urban',1]];
 const context=vm.createContext({map,metroLayers,selected:null,selMetro:null,trainLit:false,routeLit:false,round:{'line-join':'round','line-cap':'round'},from:(name,g)=>({source:'tiles-'+g,'source-layer':name}),classOf:(g,jk)=>['all',['==',['get','g'],g],['==',['get','jk'],jk]],col:()=> '#5cc8ff',
  PICK:['es-subway','es-urban','be-urban','es-subway-casing','es-urban-casing','be-urban-casing'],FAST:[],visible:{yards:true,border:true,metro:true,urban:true,suburban:true},abroadVisible:{'es-subway':true,'es-urban':true,'be-urban':true},HOME:{metro:[['subway'],['urban'],['suburban']],beside:'suburban'},metroId:(g,k)=>g==='cn'?(k==='subway'?'metro':k):g+'-'+k,borderCountries:[],BORDER_LINES:[],everyCountry:['es','be'],FOREIGN:{es:{},be:{}},rowOn:()=>true,each:id=>[[id,null]],NOT_ABROAD:['==',['get','g'],'cn'],capsulesReady:true,refreshCapsules:()=>{},loadYards:()=>{},relabelLegend:()=>{},applyHighlight:()=>{},PLACE_RANKS:true});
 const topLevel=app.match(/  const TRAM_STOPS_FROM = \d+;\n/)[0]+app.match(/  const RAIL_CAPSULES_FROM = \d+;\n/)[0];
vm.runInContext(topLevel+source+constructor+styler+picker+visibility+`\nthis.api={evidencedServices,evidencedMatch,evidencedFilter,readableMetroWidth,readableCasingColour,readableCasingOpacity,widthAt,TRAM_STOPS,METRO_STOPS,styleMetro,pick,applyVisibility};`,context);
 vm.runInContext('metroLayers.forEach(m=>{casing(m);line(m);});',context);layers.set('hsr350',{id:'hsr350',paint:{},layout:{}});
 return {context,layers,state,api:context.api};
}
function project(co){const scale=512*2**16;return {x:(co[0]+180)/360*scale,y:(1-Math.log(Math.tan(Math.PI/4+co[1]*Math.PI/360))/Math.PI)/2*scale};}
const firstCoordinate=f=>f.geometry.type==='LineString'?f.geometry.coordinates[0]:f.geometry.coordinates[0][0];
const item=(id,feature)=>({...plain(feature),layer:{id}});
const width=(h,id,p,z)=>evaluate(h.layers.get(id).paint['line-width'],p,z);
function feature(service){return service.g==='be'?belgium.find(f=>f.properties.n===service.n&&f.properties.network===service.network):actual.find(f=>f.properties.n===service.n);}

test('all special paints require current country network name and complete native relation set',()=>{
 const h=harness();for(const service of Object.values(h.api.evidencedServices)){
  const f=feature(service);assert.ok(f);assert.equal(h.api.evidencedMatch(f.properties,service),true);assert.equal(evaluate(h.api.evidencedFilter(service),f.properties,16),true);
  for(const bad of [{g:'xx'},{network:service.network+' other'},{n:service.n+' other'},{rid:service.rid[0]+',99999999'},{rid:service.rid[0].split(',')[0]},{rid:''}]){
   const p={...f.properties,...bad};assert.equal(h.api.evidencedMatch(p,service),false);assert.equal(evaluate(h.api.evidencedFilter(service),p,16),false);
  }
  assert.equal(h.api.evidencedMatch({...f.properties,rid:service.rid[1]},service),true);
 }
});

test('normal and selected Sevilla widths leave both colours and a narrow separator visible',()=>{
 const h=harness(),m=feature(h.api.evidencedServices.sevilleMetro).properties,t=feature(h.api.evidencedServices.sevilleTram).properties;
 for(const selected of [null,{...t},{...m}]){
  h.context.selMetro=selected;h.api.styleMetro();
  for(const z of [9,11,12,14,16,18]){
   const tram=width(h,'es-urban',t,z),casing=width(h,'es-urban-casing',t,z),metro=width(h,'es-subway',m,z);
   assert.ok(casing>tram);assert.ok(metro-casing>.65,`${z}: ${metro} <= ${casing}`);
  }
 }
});

test('Antwerp official white core retains maroon casing at city zooms and selection fades it',()=>{
 const h=harness(),s=h.api.evidencedServices.antwerpWhite,p=feature(s).properties;
 assert.equal(evaluate(h.layers.get('be-urban').paint['line-color'],p,11).toLowerCase(),'#ffffff');
 assert.equal(evaluate(h.layers.get('be-urban-casing').paint['line-color'],p,11),'#842f46');
 h.api.styleMetro();assert.ok(evaluate(h.layers.get('be-urban-casing').paint['line-opacity'],p,11)>.8);
 h.context.selMetro={ct:'another',n:'another'};h.api.styleMetro();assert.ok(evaluate(h.layers.get('be-urban-casing').paint['line-opacity'],p,11)<.3);
 h.context.selMetro={...p};h.api.styleMetro();assert.equal(evaluate(h.layers.get('be-urban-casing').paint['line-opacity'],p,11),.9);
 assert.equal(evaluate(h.layers.get('be-urban-casing').paint['line-color'],{...p,g:'nl'},11),'#ffffff');
});

test('one hidden class and two hidden classes leave no special orphan layer or hit',()=>{
 const h=harness(),m=item('es-subway',feature(h.api.evidencedServices.sevilleMetro)),t=item('es-urban',feature(h.api.evidencedServices.sevilleTram));h.state.query=[m,t];
 const point=project(firstCoordinate(t));
 for(const [metro,tram] of [[true,true],[true,false],[false,true],[false,false]]){
  h.context.abroadVisible['es-subway']=metro;h.context.abroadVisible['es-urban']=tram;h.api.applyVisibility();
  for(const [id,on] of [['es-subway',metro],['es-urban',tram]])for(const suffix of ['', '-casing'])assert.equal(h.layers.get(id+suffix).layout.visibility,on?'visible':'none');
  const hit=h.api.pick(point);if(!metro&&!tram)assert.equal(hit,undefined);else if(!metro)assert.equal(hit.properties.n,t.properties.n);else if(!tram)assert.equal(hit.properties.n,m.properties.n);
 }
 assert.equal([...h.layers.keys()].some(k=>k.includes('evidenced')||k.includes('antwerp')||k.includes('seville')),false);
});

test('scoped picker preserves identity and chooses tram core / exposed metro edge',()=>{
 const h=harness(),m=item('es-subway',feature(h.api.evidencedServices.sevilleMetro)),t=item('es-urban',feature(h.api.evidencedServices.sevilleTram));
 const point=project(firstCoordinate(t));h.state.query=[m,t];assert.equal(h.api.pick(point).properties.n,t.properties.n);
 // Real line inputs and paint formulas above; use a controlled coincident crossing for hit zones.
 const geom={type:'LineString',coordinates:[[0,0],[100,0]]},f={...t,geometry:geom},g={...m,geometry:geom};const projectXY=p=>({x:p[0],y:p[1]});
 assert.equal(h.context.evidencedPick,undefined);
 vm.runInContext('this.hit=evidencedPick;',h.context);
 assert.equal(h.context.hit([g,f],{x:50,y:0},projectXY,16,null).properties.n,t.properties.n);
 assert.equal(h.context.hit([g,f],{x:50,y:2.9},projectXY,16,null).properties.n,m.properties.n);
 assert.equal(h.context.hit([g,f],{x:50,y:2.1},projectXY,16,t.properties).properties.n,t.properties.n);
 assert.equal(h.context.hit([{...g,properties:{...g.properties,g:'nl'}},f],{x:50,y:0},projectXY,16,null),null);
});

test('styles and hit testing never mutate real paths; other same-name identities keep base width',()=>{
 const h=harness(),before=JSON.stringify(actual),s=h.api.evidencedServices.sevilleTram,p=feature(s).properties;
 h.context.selMetro={...p};h.api.styleMetro();h.state.query=actual.map(f=>item(f.properties.jk==='subway'?'es-subway':'es-urban',f));h.api.pick(project(firstCoordinate(actual[0])));assert.equal(JSON.stringify(actual),before);
 const other={...p,network:'Other operator'};h.context.selMetro=null;h.api.styleMetro();assert.ok(width(h,'es-urban',other,16)>width(h,'es-urban',p,16));
 assert.match(app,/offsetPaint\(copy, property, value/);assert.match(app,/offsetLayout\(copy, property, value/);
 assert.match(app,/ContinuousOffset\.renderStrokes/);assert.match(app,/CAPSULE_GEOMETRY_BEGIN/);
});

test('white-line casing follows its own hidden class and train/partial-route dimming',()=>{
 const h=harness(),p=feature(h.api.evidencedServices.antwerpWhite).properties;
 h.context.abroadVisible['be-urban']=false;h.api.applyVisibility();
 assert.equal(h.layers.get('be-urban').layout.visibility,'none');assert.equal(h.layers.get('be-urban-casing').layout.visibility,'none');
 h.context.abroadVisible['be-urban']=true;h.api.applyVisibility();
 for(const flag of ['trainLit','routeLit']){
  h.context[flag]=true;h.api.styleMetro();assert.ok(evaluate(h.layers.get('be-urban-casing').paint['line-opacity'],p,14)<.3);h.context[flag]=false;
 }
 h.api.styleMetro();assert.ok(evaluate(h.layers.get('be-urban-casing').paint['line-opacity'],p,14)>.8);
 assert.equal(evaluate(h.layers.get('be-urban').paint['line-color'],p,14).toLowerCase(),'#ffffff');
});

test('same-name selection in another network or future relation set cannot boost special sources',()=>{
 const h=harness(),p=feature(h.api.evidencedServices.antwerpWhite).properties;
 for(const bad of [{g:'nl'},{network:'Other network'},{rid:p.rid+',9999999'}]){
  h.context.selMetro={...p,...bad};h.api.styleMetro();
  assert.ok(evaluate(h.layers.get('be-urban-casing').paint['line-opacity'],p,14)<.3);
  const normal=h.api.widthAt(h.api.TRAM_STOPS,16);assert.equal(width(h,'be-urban',p,16),normal);
 }
});


test('Paris depot labels use existing French city bounds, hide at 11, fade at 12 and restore at 12.5',()=>{
 const cities=JSON.parse(fs.readFileSync(new URL('../data/fr_metro_cities.json',import.meta.url))).map(c=>({...c,g:'fr'}));
 const block=app.split('// PARIS_DEPOT_LABELS_BEGIN')[1].split('// PARIS_DEPOT_LABELS_END')[0];
 const ctx=vm.createContext({metroCities:cities});vm.runInContext(block+'\nthis.api={parisDepotScope,parisDepotLabelScope,parisDepotLabelFilter,parisDepotLabelOpacity};',ctx);
 const api=ctx.api,scope=api.parisDepotScope,filter=api.parisDepotLabelFilter(scope),opacity=api.parisDepotLabelOpacity(scope);
 const paris={g:'fr',__coordinates:[2.35,48.86]},lyon={g:'fr',__coordinates:[4.84,45.76]},foreign={g:'be',__coordinates:[2.35,48.86]};
 assert.equal(evaluate(filter,paris,11),false);assert.equal(evaluate(opacity,paris,11),0);assert.equal(evaluate(filter,paris,12),true);assert.equal(evaluate(opacity,paris,12),0);assert.equal(evaluate(opacity,paris,12.25),.5);assert.equal(evaluate(opacity,paris,12.5),1);
 for(const other of [lyon,foreign])for(const z of [11,12,12.5]){assert.equal(evaluate(filter,other,z),true);assert.equal(evaluate(opacity,other,z),1);}
 const city=cities.find(c=>c.n==='巴黎');assert.deepEqual(plain(scope[2][1].coordinates[0][0]),city.bbox.slice(0,2));
 assert.equal(api.parisDepotLabelScope([]),false);assert.equal(evaluate(api.parisDepotLabelOpacity(false),paris,11),1);
 const h=harness();h.context.visible.yards=false;h.api.applyVisibility();assert.equal(h.layers.get('depot-labels').layout.visibility,'none');assert.equal(h.layers.get('depots').layout.visibility,'none');
 const original=JSON.parse(fs.readFileSync(new URL('../data/fr_depots.geojson',import.meta.url))),before=JSON.stringify(original);const affected=original.features.filter(f=>evaluate(scope,{...f.properties,__coordinates:f.geometry.coordinates},11));assert.ok(affected.length>0);assert.equal(JSON.stringify(original),before);
 assert.match(app,/filter: parisDepotLabelFilter\(parisDepotScope\)/);assert.match(app,/'text-opacity': parisDepotLabelOpacity\(parisDepotScope\)/);
});

test('Paris depot density binds country archives when MVT omits g and rejects other archives',()=>{
 const cities=JSON.parse(fs.readFileSync(new URL('../data/fr_metro_cities.json',import.meta.url))).map(c=>({...c,g:'fr'})),state={};
 const map={setFilter:(id,value)=>{(state[id]??={}).filter=plain(value);},setPaintProperty:(id,key,value)=>{(state[id]??={})[key]=plain(value);}};
 const block=app.split('// PARIS_DEPOT_LABELS_BEGIN')[1].split('// PARIS_DEPOT_LABELS_END')[0];
 const ctx=vm.createContext({metroCities:cities,map,each:()=>[['depot-labels@fr','fr'],['depot-labels@be','be']]});
 vm.runInContext(block+'\nbindParisDepotLabels(metroCities);',ctx);
 const missingCountry={__coordinates:[2.35,48.86]},wrongCountry={...missingCountry,g:'be'};
 assert.equal(evaluate(state['depot-labels@fr'].filter,missingCountry,11),false);assert.equal(evaluate(state['depot-labels@fr']['text-opacity'],missingCountry,12.5),1);
 assert.equal(evaluate(state['depot-labels@fr'].filter,wrongCountry,11),true);
 assert.equal(evaluate(state['depot-labels@be'].filter,{...missingCountry,g:'fr'},11),true);
 assert.match(app,/bindParisDepotLabels\(metroCities\);/);
});
