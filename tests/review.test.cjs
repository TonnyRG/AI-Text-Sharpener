const {test}=require('node:test');const assert=require('node:assert/strict');
const R=require('../src/ai_text_sharpener/web/review.js');
const region=()=>({id:'a',text:'abc',original_text:'abc',enabled:true,x:10,y:10,ink_width:70,ink_height:20,font_size:20,letter_spacing:0,score:.9});
const page=r=>({width:500,height:300,regions:r});
test('queues low fit across pages, excluding preserved regions',()=>{const a=region();a.score=.5;const b={...a,id:'b',enabled:false};assert.equal(R.collect({pages:[page([a]),page([b])]}).length,1);});
test('acceptance survives derived preview sizes but expires on a real edit',()=>{const a=region();a.score=.5;const p=page([a]);a.reviewed_signature=R.signature(p,a);a.ink_width=71;assert.equal(R.pending(p,a),false);a.color='#ff0000';assert.equal(R.pending(p,a),true);});
test('overlap is flagged and removing the other region clears it',()=>{const a=region(),b={...region(),id:'b',x:60};const p=page([a,b]);assert.ok(R.pending(p,a));R.preserve(b);assert.equal(R.pending(p,a),false);assert.equal(b.preserve_original,true);});
test('large positive and negative spacing, italic and off-page are reviewed',()=>{const a=region();a.letter_spacing=6;assert.match(R.reasons(page([a]),a).join(),/字距/);a.letter_spacing=-2;assert.match(R.reasons(page([a]),a).join(),/过挤/);a.letter_spacing=0;a.font_label='Arial Italic';a.x=-1;assert.equal(R.reasons(page([a]),a).length,2);});
test('acceptance is invalidated by newly colliding text',()=>{const a=region();a.score=.5;const b={...region(),id:'b',x:150};const p=page([a,b]);a.reviewed_signature=R.signature(p,a);b.x=60;assert.ok(R.pending(p,a));});
test('ordinary text, blank erasure, and disabled formula do not become review noise',()=>{assert.equal(R.collect({pages:[page([region(),{...region(),text:'',id:'b'},{...region(),id:'c',kind:'formula',enabled:false}])]}).length,0);});

test('review acceptance and preservation survive project serialization',()=>{const a=region();a.score=.5;const p=page([a]);a.reviewed_signature=R.signature(p,a);const loaded=JSON.parse(JSON.stringify(p));assert.equal(R.pending(loaded,loaded.regions[0]),false);R.preserve(a);assert.equal(JSON.parse(JSON.stringify(a)).preserve_original,true);});

test('uncertain type is reviewed while preserving source, and can be accepted',()=>{const a={...region(),kind:'formula',enabled:false,preserve_original:true,type_review:'文字／公式待确认',fit_status:'preserved'};const p=page([a]);assert.equal(R.collect({pages:[p]}).length,1);a.reviewed_signature=R.signature(p,a);assert.equal(R.pending(p,a),false);delete a.reviewed_signature;R.preserve(a);assert.equal(R.pending(p,a),false);assert.equal(a.type_review_dismissed,true);});
test('manual type edits clear automatic type warnings',()=>{const a={...region(),type_review:'文字／公式待确认',fit_status:'edited'};assert.deepEqual(R.reasons(page([a]),a),[]);});

test('marquee preservation affects only selected unlocked regions, including good fits',()=>{
  const G=require('../src/ai_text_sharpener/web/canvas-geometry.js');
  const a={...region(),bbox:[10,10,70,20]},b={...a,id:'b',y:50,bbox:[10,50,70,20]},
    locked={...a,id:'locked',y:90,bbox:[10,90,70,20],locked:true},outside={...a,id:'outside',x:200,bbox:[200,10,70,20]};
  const p=page([a,b,locked,outside]),before=structuredClone(p);
  const ids=G.marqueeIds(p.regions,{x:0,y:0},{x:100,y:130});
  const targets=R.preservable(p,p.regions.filter(r=>ids.includes(r.id)));
  assert.deepEqual(targets.map(r=>r.id),['a','b']);targets.forEach(R.preserve);
  for(const r of [a,b]){assert.equal(r.enabled,false);assert.equal(r.preserve_original,true);}
  assert.deepEqual(locked,before.regions[2]);assert.deepEqual(outside,before.regions[3]);
  for(let i=0;i<2;i++)for(const key of ['text','x','y','bbox','font_size'])assert.deepEqual(p.regions[i][key],before.regions[i][key]);
  assert.deepEqual(R.preservable(p,[a,b,locked]),[]);
});
test('batch preservation protects disabled source boxes and dismisses uncertain formulas',()=>{
  const a={...region(),enabled:false},b={...region(),id:'math',kind:'formula',enabled:false,preserve_original:true,type_review:'文字／公式待确认'};
  const p=page([a,b]);assert.deepEqual(R.preservable(p,[a,b]),[a,b]);
  R.preservable(p,[a,b]).forEach(R.preserve);
  assert.equal(a.preserve_original,true);assert.equal(R.pending(p,b),false);
  assert.deepEqual(R.preservable(p,[a,b]),[]);
});
