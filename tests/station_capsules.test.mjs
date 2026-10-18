import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const app=fs.readFileSync(new URL('../src/app.html',import.meta.url),'utf8');
const source=app.split('// CAPSULE_GEOMETRY_BEGIN')[1].split('// CAPSULE_GEOMETRY_END')[0];
const context=vm.createContext({});
vm.runInContext(fs.readFileSync(new URL('../src/continuous-offset.js',import.meta.url),'utf8')+'\nthis.offset=ContinuousOffset;',context);
vm.runInContext(source+'\nthis.geometry=stationCapsuleGeometry;',context);
const C=context.offset, geometry=context.geometry;
const project=p=>({x:p[0],y:p[1]}), unproject=p=>[p.x,p.y];
const member=(off,jk='subway',extra={})=>({a:[0,0],t:[10,0],off,jk,...extra});
const properties=members=>({cp:JSON.stringify({v:1,a:[0,0],t:[10,0],m:members})});
// the straight part of a capsule spans the lines; its round ends add a radius beyond each outermost line
const straight=shape=>Math.hypot(shape.coordinates[1][0]-shape.coordinates[0][0],shape.coordinates[1][1]-shape.coordinates[0][1]);
const size=shape=>straight(shape)+2*shape.radius;

test('span includes actual per-member offsets and line widths at every zoom',()=>{
  for (const zoom of [11,13,14.5,15.5,16,16.5,18]) {
    const members=[member(-1.5),member(1.5)], shape=geometry(properties(members),zoom,project,unproject,()=>4);
    const expected=C.pixels(members[1],zoom,'metro')-C.pixels(members[0],zoom,'metro')+6;
    assert.ok(Math.abs(straight(shape)-expected)<1e-9);
    assert.ok(Math.abs(size(shape)-expected-2*shape.radius)<1e-9);
    assert.equal(shape.coordinates[0][0],0);
  }
});

test('reversing every member geometry and signed seats preserves the screen capsule',()=>{
  const a=[member(-1.5),member(.5)],b=a.map(m=>({...m,t:[-10,0],off:-m.off}));
  const first=geometry(properties(a),16,project,unproject,()=>4),second=geometry(properties(b),16,project,unproject,()=>4);
  assert.deepEqual(JSON.parse(JSON.stringify(first.coordinates)),JSON.parse(JSON.stringify(second.coordinates)));
});

test('different metro and tram steps use the renderer contract, not one guessed bundle count',()=>{
  const members=[member(-1,'urban'),member(1,'subway')];
  const shape=geometry(properties(members),15.5,project,unproject,m=>m.jk==='urban'?3:4);
  const low=C.pixels(members[0],15.5,'metro')-1.5-1,high=C.pixels(members[1],15.5,'metro')+2+1;
  assert.ok(Math.abs(straight(shape)-(high-low))<1e-9);
});

test('independent tracks retain native anchors as offsets return between zoom 14.5 and 16.5',()=>{
  const members=[member(-1,'subway',{a:[0,-12],t:[10,-12],ap:1,sh:0}),member(1,'subway',{a:[0,12],t:[10,12],ap:1,sh:0})];
  const span=z=>straight(geometry(properties(members),z,project,unproject,()=>4));
  assert.ok(span(14.5)>span(15.5));
  assert.ok(span(15.5)>span(16.5));
  assert.equal(span(16.5),30);
  assert.equal(span(18),30);
});

test('malformed evidence and one service preserve the circle fallback',()=>{
  assert.equal(geometry({cp:'{'},16,project,unproject,()=>4),null);
  assert.equal(geometry(properties([member(0)]),16,project,unproject,()=>4),null);
});

test('hiding one class shrinks a proven capsule to the remaining service',()=>{
  const members=[member(-2,'urban'),member(2,'subway')];
  const shape=geometry(properties(members),16,project,unproject,()=>4,m=>m.jk==='subway');
  assert.ok(shape);
  assert.equal(shape.centre[1],C.pixels(members[1],16,'metro'));
  assert.equal(geometry(properties(members),16,project,unproject,()=>4,()=>false),null);
});

test('page keeps authoritative station coordinates and capsule picking precedes line picking',()=>{
  assert.match(app,/coordinates:JSON\.parse\(capsule\.properties\._station\)/);
  assert.match(app,/offerStation\(stationOf\(capsule\.properties\._rail \? stations\.features : metroStations\.features,point\)\)/);
  assert.ok(app.indexOf("const capsule=map.queryRenderedFeatures")<app.indexOf("      const f = pick(e.point);",app.indexOf("const capsule=map.queryRenderedFeatures")));
  assert.match(app,/whenStations/);
  assert.match(app,/capsulesReady \? \['all',theirLines,stopShown,\['!', \['has','cp'\]\]\] : \['all',theirLines,stopShown\]/);
});

test('tram stops and tram-only capsules show from TRAM_STOPS_FROM, metro stations from z11',()=>{
  assert.match(app,/const TRAM_STOPS_FROM = 14;/);
  assert.match(app,/const stopShown = \['any', \['!', \['has', 't'\]\], \['>=', \['zoom'\], TRAM_STOPS_FROM\]\];/);
  assert.match(app,/among\('metro-station-labels', withMetroStations, \['all', theirLines, stopShown\]\);/);
  assert.match(app,/if \(zoom<TRAM_STOPS_FROM && \(p\.t \|\| capsule\.m\.every\(m => m\.jk==='urban'\)\)\) continue;/);
});

test('zoomed in, a capsule gives way to a dot on each line that stops, on that line',()=>{
  assert.match(app,/const CAPSULE_UNTIL = 16;/);
  // (from z5 for the railway stations' capsules; the metro stations' still from z11)
  assert.equal((app.match(/minzoom:5,maxzoom:CAPSULE_UNTIL,filter:capsuleShape,/g)||[]).length,2);
  assert.match(app,/if \(zoom<11\) return \{type:'FeatureCollection',features\};\s+for \(const f of metroStations\.features\)/);
  assert.match(app,/id:'station-capsule-dots',type:'circle',source:'station-capsules',minzoom:CAPSULE_UNTIL,filter:\['==',\['geometry-type'\],'Point'\]/);
  assert.match(app,/layers:\['station-capsules','station-capsules-border','station-capsule-dots'\]/);
  const members=[member(-1,'urban'),member(1,'urban')];
  const shape=geometry(properties(members),16.5,project,unproject,()=>4.5);
  assert.equal(shape.dots.length,2);
  shape.dots.forEach((dot,i)=>{
    assert.ok(Math.abs(dot.at[1]-C.pixels(members[i],16.5,'metro'))<1e-9);    // on its own line, at its own seat
    assert.equal(dot.half,2.25);
  });
});

// Railway stations (2026-10-18, "铁路站也要胶囊"): members drawn in the rail and guest modes
test('railway members follow the rail layers: seated far out, back on their own tracks by z16.5',()=>{
  const rail=(off,y,extra={})=>({a:[0,y],t:[10,y],off,mode:'rail',wc:'main',...extra});
  const members=[rail(-.5,-5),rail(.5,5)];
  const span=z=>straight(geometry(properties(members),z,project,unproject,()=>3));
  for (const z of [11,14.5]) assert.ok(Math.abs(span(z)-(10+C.pixels(members[1],z,'rail')-C.pixels(members[0],z,'rail')+5))<1e-9);
  assert.ok(span(14.5)>span(15.5));
  assert.equal(span(16.5),15);                          // the tracks' own 10 px apart, plus the lines and the edges
  const dots=geometry(properties(members),16.5,project,unproject,()=>3).dots;
  assert.deepEqual(JSON.parse(JSON.stringify(dots.map(d=>d.at[1]).sort((a,b)=>a-b))),[-5,5]);
  // a metro-mode member at the same seat would not come back onto its track
  assert.ok(Math.abs(C.pixels({off:.5},16.5,'metro'))>0 && C.pixels({off:.5},16.5,'rail')===0);
});

test('a guest without a seat stands one step beside its host, as the suburb layer draws it',()=>{
  const host={a:[0,0],t:[10,0],off:0,mode:'rail',wc:'fast'}, guest={a:[0,0],t:[10,0],mode:'guest'};
  for (const z of [9,12,16.5]) {
    const shape=geometry(properties([host,guest]),z,project,unproject,()=>2);
    assert.ok(Math.abs(straight(shape)-(C.pixels(guest,z,'guest')+4))<1e-9);
    assert.ok(C.pixels(guest,z,'guest')>0);
  }
});

test('the page draws railway capsules over the stations layer and hides their dots',()=>{
  // below RAIL_CAPSULES_FROM a railway station keeps its dot; the constant is at the top level, where
  // applyVisibility() reads it (TRAM_STOPS_FROM once stopped the page from a function's scope)
  assert.match(app,/among\('stations', withStations, capsulesReady \? \['all', \['any', \['has', 'h'\], \['>=', \['zoom'\], 8\.5\]\],\s+\['any', \['!', \['has', 'cp'\]\], \['<', \['zoom'\], RAIL_CAPSULES_FROM\]\]\]/);
  assert.match(app,/\n  const TRAM_STOPS_FROM = 14;\n(?:  \/\/.*\n)*  const RAIL_CAPSULES_FROM = 11;\n/);
  assert.match(app,/for \(const f of stations\.features\) \{\s+const p=f\.properties, code=typeof p\.g==='string' \? p\.g : 'cn';\s+if \(!p\.cp \|\| zoom<RAIL_CAPSULE_FROM\(p\)/);
  assert.match(app,/ContinuousOffset\.pixels\(member,zoom,member\.mode==='rail' \? 'rail' : member\.mode==='guest' \? 'guest' : 'metro'\)/);
  assert.match(app,/const twinShown = \(member, zoom\) => \(member\.zf \? zoom<SWAP : member\.zn \? zoom>=SWAP : true\);/);
  assert.match(app,/'line-color':\['coalesce',\['get','_fill'\],'#ffffff'\]/);
  assert.match(app,/for \(const \[id\] of each\('station-labels'\)\) map\.moveLayer\(id, each\('metro-stations'\)\[0\]\[0\]\);/);
  // the route fields and the search keep reading the stations' own points
  assert.match(app,/const station=\{\.\.\.p,_station:JSON\.stringify\(f\.geometry\.coordinates\),_rail:1,_fill:fill\};/);
});
