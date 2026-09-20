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
