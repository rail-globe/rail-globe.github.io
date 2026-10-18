import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
const ctx=vm.createContext({});
vm.runInContext(readFileSync(new URL('../src/continuous-offset.js',import.meta.url),'utf8')+'\nthis.C=ContinuousOffset;',ctx);
const C=ctx.C;
const input=co=>({type:'Feature',properties:{n:'curve',jc:1,jk:'urban',off:2},geometry:{type:'LineString',coordinates:co}});
const distance=(p,co)=>Math.min(...co.slice(1).map((b,i)=>{
 const a=co[i],x=b[0]-a[0],y=b[1]-a[1],t=Math.max(0,Math.min(1,((p[0]-a[0])*x+(p[1]-a[1])*y)/(x*x+y*y)));
 return Math.hypot(p[0]-a[0]-t*x,p[1]-a[1]-t*y);
}));
test('round corners preserve endpoints and stay within eight pixels',()=>{
 const co=[[9,48],[9.001,48],[9.001,48.001]];
 for(const z of [12,14,16,18]){
  const out=C.roundDisplay(co,z),world=512*2**z;
  assert.ok(Math.hypot(...out[0].map((v,i)=>v-co[0][i]))<1e-12);
  assert.ok(Math.hypot(...out.at(-1).map((v,i)=>v-co.at(-1)[i]))<1e-12);
  for(const p of out)assert.ok(distance(C.mercator(p),co.map(C.mercator))*world<=8.001);
 }
});
test('geometry reversal gives the same rounded path',()=>{
 const co=[[9,48],[9.001,48],[9.0015,48.001]];
 const a=C.roundDisplay(co,16),b=C.roundDisplay([...co].reverse(),16).reverse();
 assert.equal(a.length,b.length);
 a.forEach((p,i)=>assert.ok(Math.hypot(p[0]-b[i][0],p[1]-b[i][1])<1e-12));
});
test('real turnback is retained',()=>{
 const co=[[9,48],[9.001,48],[9.0001,48.00001]];
 assert.equal(C.roundDisplay(co,16).length,co.length);
});
test('partial highlight follows the full rounded display curve',()=>{
 const f=input([[9,48],[9.001,48],[9.001,48.001]]),chain=C.prepare([f])[0],member=chain.members[0];
 const props={...f.properties,kind:'metro'};
 delete props.jc; delete props.cl;
 const stroke={...f,properties:props};
 C.bindStroke(props,chain,member,member.len*.3,member.len*.7);
 for(const z of [12,14,16,18]){
  const full=C.render([chain],z,'metro').features[0].geometry.coordinates.map(C.mercator);
  const partial=C.renderStrokes([stroke],z,'metro').features[0].geometry.coordinates;
  for(const p of partial)assert.ok(distance(C.mercator(p),full)*512*2**z<.041);
 }
});

test('centre-line evidence protects a real return and permits a small offset spur',()=>{
 const co=[[9,48],[9.001,48],[9.0009,48.00002],[9.0012,48.0003]],at=[0,1,2,3];
 const real=C.roundDisplay(co,16,at,[true,true,true,true]).co;
 const offset=C.roundDisplay(co,16,at,[false,false,false,false]).co;
 const isTip=p=>Math.hypot(p[0]-co[1][0],p[1]-co[1][1])<1e-12;
 assert.ok(real.some(isTip));
 assert.ok(!offset.some(isTip));
});

test('closed offset loop requires simple-source evidence',()=>{
 const co=[[9,48],[9.00003,48.00003],[9,48.00003],[9.00003,48],[9.00006,48]],at=[0,1,2,3,4];
 const proven=C.roundDisplay(co,16,at,[false,false,false,false,false],true);
 const unproven=C.roundDisplay(co,16,at,[false,false,false,false,false],false);
 const collapsed=p=>p.co.some((v,i)=>i && Math.hypot(v[0]-p.co[i-1][0],v[1]-p.co[i-1][1])<1e-12 && p.at[i]>p.at[i-1]);
 assert.ok(collapsed(proven));
 assert.ok(!collapsed(unproven));
});

test('final fillet of the actual Stuttgart U12 endpoint has no small recrossing',()=>{
 const source=JSON.parse(readFileSync(new URL('./fixtures/stuttgart-u12-endpoint.json',import.meta.url),'utf8'));
 const chains=C.prepare(source);
 const result=C.render(chains,12,'metro');
 const cross=(a,b)=>a[0]*b[1]-a[1]*b[0];
 for(const f of result.features){
  const co=f.geometry.coordinates.map(p=>C.mercator(p).map(v=>v*512*2**12));
  for(let i=0;i<co.length-2;i++)for(let j=i+2;j<co.length-1;j++){
   const a=co[i],b=co[i+1],c=co[j],d=co[j+1];
   const r=[b[0]-a[0],b[1]-a[1]],s=[d[0]-c[0],d[1]-c[1]],v=[c[0]-a[0],c[1]-a[1]],den=cross(r,s);
   if(Math.abs(den)<1e-14)continue;
   const t=cross(v,s)/den,u=cross(v,r)/den;
   assert.ok(!(t>1e-7 && t<1-1e-7 && u>1e-7 && u<1-1e-7),`new loop at ${i}/${j}`);
  }
 }
});

test('explicit shared zero-port profile is not multiplied by a separate branch ramp',()=>{
 const profile={v:1,base:0,ramps:[[0,.0003,0,1]],origin:0,direction:1,period:null};
 const source=[[[0,0],[.001,0]],[[0,0],[0,.001]],[[0,0],[-.001,0]]].map(co=>({
  type:'Feature',properties:{n:'branched',network:'N',rid:'1',jc:1,jk:'urban',off:1,op:JSON.stringify(profile)},
  geometry:{type:'LineString',coordinates:co}}));
 assert.ok(C.prepare(source).every(chain=>chain.anchors.length===0));
 const legacy=source.map(f=>({...f,properties:{...f.properties,jc:0}}));
 assert.ok(C.prepare(legacy).every(chain=>chain.anchors.length===1));
});
