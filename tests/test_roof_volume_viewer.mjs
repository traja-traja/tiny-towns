// Pure DOM/data checks: no browser, WebGL rendering, model fitting or screenshots.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const source=fs.readFileSync(path.join(root,'scripts/roof_v2_viewer.js'),'utf8');
new vm.Script(source); // Full file syntax, without initialize().
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.style={};this.textContent='';}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=[...items];}
  setAttribute(key,value){this.attributes[key]=value;}
  set innerHTML(_){throw Error('Unsafe HTML insertion');}
}
const elements=new Map();
const document={
  getElementById(id){if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);},
  createElement(tag){return new Element(tag);},
  createElementNS(_,tag){return new Element(tag);},
};
document.getElementById('roof-data').textContent=JSON.stringify({buildings:[],report:{batch:true}});
const context=vm.createContext({document,window:{addEventListener(){}},THREE:{Vector3:class{}},console});
vm.runInContext(source.slice(0,source.indexOf('function updateCamera()')),context);
const call=(name,arg)=>{context.argument=arg;return vm.runInContext(name+'(argument)',context);};
const polygon=(x0,y0,x1,y1)=>({type:'Polygon',coordinates:[[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]]});
const courtyard=polygon(0,0,10,10);courtyard.coordinates.push(polygon(3,3,7,7).coordinates[0]);
const part=(origin,displayOffset)=>({origin_xy:origin,display_offset_m:displayOffset,footprint:courtyard,
  result:{model:{type:'compound',metadata:{volume_count:2,bodies:[
    {index:0,footprint:courtyard,area_m2:84,roof_type:'butterfly',metadata:{valley_height_m:8,high_edge_height_m:10}},
    {index:1,footprint:polygon(10,0,20,10),area_m2:100,roof_type:'skillion',metadata:{}}
  ]}},timing:{total_seconds:1}}});
const current=part([1000,2000],[800,0,0]);current.display_label='<img src=x onerror=alert(1)>';
const previous=part([1000,2000],[-800,0,0]);previous.display_label='Předchozí';
const parts=[{part:previous,index:0},{part:current,index:1}];
const plan=call('volumePlanData',parts);
assert.deepEqual(Array.from(plan.bounds),[0,0,20,10]);
assert.equal(plan.plans[0].bodies.length,2);
assert.equal(plan.plans[0].bodies[0].polygons[0].length,2); // Courtyard retained.
assert.equal(plan.plans[1].count,2);
const at=call('planLabelPoint',plan.plans[0].bodies[0].polygons);
assert(!(at[0]>3&&at[0]<7&&at[1]>3&&at[1]<7),'Label must not occupy the courtyard');
const pathData=call('footprintPath',plan.plans[0].bodies[0].polygons);
assert.equal((pathData.match(/Z/g)||[]).length,2);
call('renderVolumePlans',parts);
const cards=document.getElementById('volume-plans').children;
assert.equal(cards.length,2);
const svgs=cards.map(c=>c.children.find(x=>x.tag==='svg'));
assert.equal(svgs[0].attributes.viewBox,svgs[1].attributes.viewBox);
assert(!svgs[0].attributes.viewBox.includes('NaN'));
assert.equal(cards[1].children[0].textContent,current.display_label);
const paths=svgs[0].children.filter(x=>x.tag==='path');
assert.equal(paths.length,3); // Two bodies and the source outline.
assert.equal(paths[0].attributes['fill-rule'],'evenodd');
assert.notEqual(paths[0].attributes.fill,paths[1].attributes.fill);
assert.equal(paths[2].attributes['stroke-dasharray'],'4 3');
assert(call('metricRows',current).some(row=>row[0]==='Počet hlavních objemů'&&row[1]==='2'));
const texts=node=>[node.textContent,...node.children.flatMap(texts)].join(' ');
assert(texts(cards[1]).includes('Úžlabí: 8 m'));
assert(texts(cards[1]).includes('Horní hrany: 10 m'));
assert(texts(cards[1]).includes('Korytová (motýlková)'));

// Part origins are registered together; display offsets belong to the 3D view only.
const shifted=part([1005,2002],[0,0,0]);
const shiftedPlans=call('volumePlanData',[{part:previous,index:0},{part:shifted,index:1}]);
assert.deepEqual(Array.from(shiftedPlans.bounds),[0,0,25,12]);
const unavailable=call('volumePlanData',[{part:{result:{model:{}}},index:0}]);
assert.equal(unavailable.bounds,null);
call('renderVolumePlans',[{part:{result:{model:{}}},index:0}]);
assert(texts(document.getElementById('volume-plans')).includes('nejsou'));

// The reference comparison preserves the old whole footprint beside two new bodies.
const fixture=path.join(root,'cities/ceske-budejovice/experiments/roof-v493-footprints-volumes-5/comparison.json');
if(fs.existsSync(fixture)){
  const building=JSON.parse(fs.readFileSync(fixture,'utf8')).buildings.find(b=>b.id==='7eb5f339-5311-4573-ac1c-4f6a0fb9d5cb');
  const plans=call('volumePlanData',building.parts.map((part,index)=>({part,index})));
  assert.equal(plans.plans.length,2);
  assert.deepEqual(Array.from(plans.plans,p=>p.bodies.length),[1,2]);
  assert.deepEqual(Array.from(plans.plans,p=>p.count),[1,2]);
  assert(plans.bounds.every(Number.isFinite));
  call('renderVolumePlans',building.parts.map((part,index)=>({part,index})));
}
console.log('Volume viewer checks passed: split footprints, holes, origins, comparison scale, metadata, safe DOM and reference data.');
