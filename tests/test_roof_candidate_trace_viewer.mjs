// Saved trace UI only: no roof inference or browser process.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const source=fs.readFileSync(path.join(root,'scripts/roof_v2_viewer.js'),'utf8');
new vm.Script(source);
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.textContent='';this.style={};}
  append(...items){this.children.push(...items);}replaceChildren(...items){this.children=[...items];}
  set innerHTML(_){throw Error('Unsafe HTML insertion');}
}
const elements=new Map(),document={getElementById(id){if(!elements.has(id))elements.set(id,new Element('div'));return elements.get(id);},createElement(tag){return new Element(tag);}};
document.getElementById('roof-data').textContent=JSON.stringify({buildings:[]});
const context=vm.createContext({document,window:{addEventListener(){}},THREE:{Vector3:class{}},console});
vm.runInContext(source.slice(0,source.indexOf('function updateCamera()')),context);
const call=(...args)=>{context.arguments_=args;return vm.runInContext('appendCandidateTrace(...arguments_)',context);};
const allText=node=>[node.textContent,...node.children.flatMap(allText)].join(' ');
const host=new Element('div');
call(host,{result:{diagnostics:{candidate_telemetry:{detailed:true,families:[{family:'straight_skeleton',considered:4,fitting_seconds:.25,geometry_seconds:.4,overhead_seconds:.1}],attempts:[{family:'straight_skeleton',label:'<img onerror=bad>',status:'skipped',reason:'<script>bad</script>',stage:'eligibility',count:0}]}}}});
const text=allText(host);
for(const expected of ['4 kandidátních pokusů','Straight skeleton','0,25','Přeskočen','<script>bad</script>','<img onerror=bad>'])assert(text.includes(expected),expected);
const old=new Element('div');call(old,{result:{}});assert(allText(old).includes('Chybějící údaj neznamená nulový čas'));
const failed=new Element('div');call(failed,{candidate_telemetry:{families:[],detailed:false}});assert(allText(failed).includes('pouze souhrnný log'));
console.log('Candidate telemetry viewer passed: saved data, safe text, missing legacy data and compact mode.');
