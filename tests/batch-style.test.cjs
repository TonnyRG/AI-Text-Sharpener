const {test}=require('node:test');
const assert=require('node:assert/strict');
const B=require('../src/ai_text_sharpener/web/batch-style.js');
const base={text:'中文 English',font_id:'sans',font_label:'Sans',font_size:42,letter_spacing:1,stroke_width:0,color:'#182029',enabled:true,x:10,y:20,bbox:[5,15,180,50],rotation:20,source_rotation:20,score:.95,alternatives:[{font_id:'old'}],reviewed_signature:'accepted'};
const sample=()=>[{...structuredClone(base),id:'a'},{...structuredClone(base),id:'b',font_size:36},
  {...structuredClone(base),id:'locked',locked:true},{...structuredClone(base),id:'original',enabled:false},
  {...structuredClone(base),id:'math',kind:'formula',latex:'x^2',font_size:48}];
test('mixed values and editable counts exclude locked and preserved regions',()=>{
  const rs=sample();assert.deepEqual(B.common(rs,'font_size'),{count:3,mixed:true,value:42});
  assert.deepEqual(B.common(rs,'letter_spacing'),{count:2,mixed:false,value:1});
});
test('batch size is integer, includes enabled formulas and preserves unrelated properties',()=>{
  const rs=sample(),before=structuredClone(rs),result=B.plan(rs,'font_size',40.5);
  assert.deepEqual(result.changes.map(c=>c.id),['a','b','math']);assert.equal(result.value,41);
  for(const c of result.changes){const r=rs.find(r=>r.id===c.id);Object.assign(r,c.patch);assert.equal(r.font_size,41);assert.equal(r.score,null);assert.deepEqual(r.alternatives,[]);assert.equal(r.reviewed_signature,null);}
  for(let i=0;i<rs.length;i++)for(const key of ['text','font_id','color','x','y','bbox','rotation','source_rotation'])assert.deepEqual(rs[i][key],before[i][key]);
  assert.deepEqual(rs[2],before[2]);assert.deepEqual(rs[3],before[3]);
});
test('font changes update label together and skip mathematical fonts',()=>{
  const result=B.plan(sample(),'font_id','bold',{id:'bold',label:'Sans Bold'});
  assert.deepEqual(result.changes.map(c=>c.id),['a','b']);
  assert.ok(result.changes.every(c=>c.patch.font_label==='Sans Bold'&&c.patch.font_id==='bold'));
});
test('negative spacing rounds away from zero, formula spacing is unchanged',()=>{
  const result=B.plan(sample(),'letter_spacing',-1.5);assert.equal(result.value,-2);assert.equal(result.changes.length,2);
});
test('stroke retains fractional control without scaling size or spacing',()=>{
  const patch=B.plan(sample(),'stroke_width',.35).changes[0].patch;
  assert.equal(patch.stroke_width,.35);assert.equal(patch.font_size,undefined);assert.equal(patch.letter_spacing,undefined);
});
test('mixed per-character colors remain unchanged until color is explicitly edited',()=>{
  const r={...base,id:'a',color_mode:'multi',color_text:base.text,color_runs:[{start:0,end:2,color:'#ff0000'}]};
  assert.equal(B.common([r],'color').mixed,true);
  const resized={...r,...B.plan([r],'font_size',32).changes[0].patch};assert.deepEqual(resized.color_runs,r.color_runs);
  const recolored={...r,...B.plan([r],'color','#182029').changes[0].patch};assert.equal(recolored.color_mode,'single');assert.deepEqual(recolored.color_runs,[]);assert.equal(recolored.color_source,'manual');
});
test('unchanged style does not create an undo operation',()=>{
  assert.deepEqual(B.plan(sample(),'stroke_width',0).changes,[]);
});
test('invalid values and unknown fonts cannot create partial patches',()=>{
  const rs=sample(),before=structuredClone(rs);
  for(const [key,value] of [['font_size',1001],['font_size',''],['letter_spacing',-301],['stroke_width',-1],['stroke_width',NaN],['color','red'],['font_id','unknown'],['text','overwrite']])assert.throws(()=>B.plan(rs,key,value));
  assert.deepEqual(rs,before);
});
test('planning itself never mutates the selection, allowing preflight and atomic undo',()=>{
  const rs=sample(),before=structuredClone(rs);B.plan(rs,'font_size',36);assert.deepEqual(rs,before);
});
