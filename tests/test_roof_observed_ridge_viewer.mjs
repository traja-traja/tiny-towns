// Saved evidence only: DOM and geometry buffer checks, no browser or model inference.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const source=fs.readFileSync(path.join(root,'scripts/roof_v2_viewer.js'),'utf8');
new vm.Script(source);
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.style={};this.textContent='';}
  append(...items){this.children.push(...items);} replaceChildren(...items){this.children=[...items];}
  setAttribute(key,value){this.attributes[key]=value;}
  set innerHTML(_){throw Error('Unsafe HTML insertion');}
}
const elements=new Map(),document={getElementById(id){if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);},createElement(tag){return new Element(tag);},createElementNS(_,tag){return new Element(tag);}};
document.getElementById('roof-data').textContent=JSON.stringify({buildings:[],report:{batch:true}});
const drawn=[];
const THREE={Vector3:class{},BufferGeometry:class{setAttribute(name,value){this[name]=value;}},Float32BufferAttribute:class{constructor(values){this.array=values;}},LineBasicMaterial:class{constructor(options){Object.assign(this,options);}},LineSegments:class{constructor(geometry,material){this.geometry=geometry;this.material=material;this.userData={};}}};
const context=vm.createContext({document,window:{addEventListener(){}},THREE,console,drawn});
vm.runInContext(source.slice(0,source.indexOf('function updateCamera()')),context);
vm.runInContext('group={add(o){drawn.push(o);}};geometryStats={invalid_lines:0};',context);
const call=(name,...args)=>{context.arguments_=args;return vm.runInContext(name+'(...arguments_)',context);};
const line={points:[[1,2,9],[5,3,9]],role:'main',source:'point_profiles',length_m:4.12,height_m:9,confidence:.87,section_count:8,model_comparison:{observed_minus_model_roof_m:.43,nearest_parallel_model_ridge_distance_m:1.23}};
const evidence={version:'test',method:'longitudinal_profiles',seconds:.123,volumes:[
 {volume_id:1,status:'detected',lines:[line]},
 {volume_id:2,status:'uncertain',reason:'<b>low support</b>',lines:[{...line,points:[[1,8,12],[8,8,12]],height_m:12}]},
 {volume_id:3,status:'not_detected',reason:'insufficient points',lines:[]}
]};
const part={result:{diagnostics:{observed_ridges:evidence,candidate_end_edges:[{id:'end_1',edge_xy:[[0,0],[0,8]],edge_length_m:8}]},model:{metadata:{eave_height_m:7,volume_count:3},ridge_lines:[[[1,1,99],[5,5,99]]],observed_ridges:{volumes:[]}}}};
assert.equal(call('observedRidgeData',part).volumes.length,3,'Diagnostics have priority');
assert.equal(call('observedRidgeLines',part).length,2);
assert.equal(call('observedRidgeLines',part,'detected').length,1);
assert.equal(call('observedRidgeLines',part,'uncertain').length,1);
assert.equal(call('observedRidgeLines',part,'not_detected').length,0);
assert.equal(vm.runInContext('state.layers.observedRidge',context),true);
call('lineLayer',call('observedRidgeLines',part,'detected'),[10,20,30],0x00b85a,'observedRidge',0);
assert.equal(drawn.length,1);
assert.deepEqual(Array.from(drawn[0].geometry.position.array),[11,39,-22,15,39,-23]); // Exact saved z + part origin, no display lift.
assert.equal(drawn[0].material.depthTest,false);
assert.equal(drawn[0].visible,true);
assert.equal(drawn[0].userData.layer,'observedRidge');
const host=new Element('div');call('appendObservedRidges',host,part);
const allText=node=>[node.textContent,...node.children.flatMap(allText)].join(' ');
const content=allText(host);
for(const expected of ['Objem 1','Objem 2','Objem 3','Nejistý odhad','Spolehlivý hřeben nenalezen','4,12 m','9 m','Řezy mračnem bodů','<b>low support</b>','Podpůrné řezy','+0,43 m','1,23 m','Porovnání dvou odhadů'])assert(content.includes(expected),expected);
assert(!content.includes('Objem 4'));assert(!content.includes('pracovní linka ze zdrojových bodů chybí'));
const old={result:{model:{metadata:{volume_count:2},ridge_lines:[line.points]}}};
assert.equal(call('observedRidgeData',old).volumes.length,2);assert.equal(call('observedRidgeData',old).volumes[0].volume_id,1);assert.equal(call('observedRidgeData',old).volumes[1].volume_id,2);
assert.equal(call('observedRidgeLines',old).length,0,'Mesh lines must never masquerade as detected evidence');
const oldHost=new Element('div');call('appendObservedRidges',oldHost,old);assert(allText(oldHost).includes('není v tomto výstupu uložen'));
const fallback={result:{model:{observed_ridges:evidence}}};assert.equal(call('observedRidgeLines',fallback).length,2);
assert.equal(call('candidateEndData',part)[0].height,7);
const malformed={result:{diagnostics:{observed_ridges:{volumes:[{status:'detected',lines:[{points:[[NaN,0,2],[1,2,3]]}]}]},candidate_end_edges:[{edge_xy:[[NaN,0],[1,2]]}]}}};
assert.equal(call('observedRidgeLines',malformed).length,0);assert.equal(call('candidateEndData',malformed).length,0);
const template=fs.readFileSync(path.join(root,'scripts/roof_v2_report.py'),'utf8');
assert(template.includes('data-layer="observedRidge" checked'));
assert(template.includes('Hřebeny modelu'));
assert(template.includes('data-layer="candidateEnds"'));

// Every footprint side remains visible, including excluded ones; audit supersedes candidate-only lists.
const auditPart=structuredClone(part);
auditPart.result.diagnostics.end_edge_audit=[
 {id:'edge_1',edge_xy:[[0,0],[0,8]],edge_length_m:8,eligible:true,reason:'eligible',face_index:0,candidate_id:'end_1'},
 {id:'edge_2',edge_xy:[[0,8],[5,8]],edge_length_m:5,eligible:false,reason:'non_triangular_terminal_face',face_index:1},
 {id:'edge_3',edge_xy:[[5,8],[5,7.9]],edge_length_m:.1,eligible:false,reason:'edge_too_short',face_index:2}
];
assert.equal(call('candidateEndData',auditPart).length,3);
assert.equal(call('candidateEndData',auditPart)[1].eligible,false);
const auditHost=new Element('div');call('appendCandidateEnds',auditHost,auditPart);
const auditText=allText(auditHost);
for(const expected of ['edge_1 / end_1','edge_2','edge_3','není trojúhelník','příliš krátká','Vyřazení není důkazem'])assert(auditText.includes(expected),expected);
const stringConfidence=structuredClone(part);stringConfidence.result.diagnostics.observed_ridges.volumes[0].lines[0].confidence='supported';stringConfidence.result.diagnostics.observed_ridges.volumes[1].lines[0].confidence='tentative';
const confidenceHost=new Element('div');call('appendObservedRidges',confidenceHost,stringConfidence);assert(allText(confidenceHost).includes('Podpořený odhad'));assert(allText(confidenceHost).includes('Předběžný odhad'));


// Virtual construction footprint is diagnostic only; it must not replace the actual body.
const rectangle=(x0,y0,x1,y1)=>({type:'Polygon',coordinates:[[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]]});
const virtualPart={origin_xy:[100,200],footprint:rectangle(0,0,8,5),result:{model:{type:'compound',metadata:{reference_label:'bounded-test',generalization:{label:'fallback-label',reference_footprint:rectangle(0,0,10,5),original_edges:12,reference_edges:4,added_area_m2:10,max_boundary_shift_m:2}}}}};
const plan=call('volumePlanData',[{part:virtualPart,index:0}]);
assert.deepEqual(Array.from(plan.bounds),[0,0,10,5]);
assert.equal(plan.plans[0].virtualLabel,'bounded-test');
assert.equal(plan.plans[0].bodies[0].area,40,'Actual footprint must remain unchanged');
call('renderVolumePlans',[{part:virtualPart,index:0}]);
const card=document.getElementById('volume-plans').children[0],svg=card.children.find(child=>child.tag==='svg');
const virtualPath=svg.children.find(child=>child.tag==='path'&&child.attributes.stroke==='#9251b5');
assert(virtualPath);assert.equal(virtualPath.attributes['stroke-dasharray'],'7 4');
assert(svg.children.some(child=>child.tag==='path'&&child.attributes.stroke==='#68746d'));
assert(allText(card).includes('virtuální obrys'));assert(allText(card).includes('skutečný půdorys'));
const referenceRows=call('metricRows',virtualPart);
for(const expected of ['bounded-test','12 → 4','10 m²','2 m'])assert(referenceRows.some(row=>row[1]===expected),expected);
const auditMore=structuredClone(auditPart);auditMore.result.diagnostics.end_edge_audit=['neighbor_continuation_breaks_join','continuation_lowers_original_roof','no_interior_gable_peak'].map((reason,i)=>({id:'edge_'+i,edge_xy:[[i,0],[i,5]],edge_length_m:5,eligible:false,reason}));
const auditMoreHost=new Element('div');call('appendCandidateEnds',auditMoreHost,auditMore);
for(const expected of ['výškový schod','snížilo původní střechu','vnitřní vrchol se spádem na obě strany'])assert(allText(auditMoreHost).includes(expected));
assert(content.includes('neovlivňují výběr střechy'));

console.log('Observed ridge viewer passed: diagnostic priority, all volume states, exact 3D positions, toggles, safe DOM, missing legacy evidence and candidate edges.');
