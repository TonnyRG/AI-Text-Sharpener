const {test}=require('node:test');
const assert=require('node:assert/strict');
const B=require('../src/ai_text_sharpener/web/batch-style.js');
const base={id:'reference',text:'Reference',enabled:true,font_id:'regular',font_label:'Regular',font_size:40,stroke_width:.15,letter_spacing:1,color:'#123456',bbox:[20,20,180,45],x:23,y:23,rotation:0,source_rotation:0};
const make=(id,patch={})=>({...structuredClone(base),id,...patch});
const font={id:'regular',label:'Regular'};
test('similar-size selection is anchored to reference, not chained across a hierarchy',()=>{
  const rs=[make('body',{font_size:41}),make('small',{font_size:38}),make('step',{font_size:43}),make('heading',{font_size:56}),make('reference')];
  const before=structuredClone(rs);
  assert.deepEqual(B.similar(rs,rs[4]),['reference','body','small']);
  assert.deepEqual(rs,before);
});
test('similar selection skips disabled, locked, formulas and differing source heights or direction',()=>{
  const rs=[make('a'),make('b',{enabled:false}),make('c',{locked:true}),make('d',{kind:'formula'}),make('e',{rotation:90}),make('f',{bbox:[0,0,180,30]})];
  assert.deepEqual(B.similar(rs,base),['reference','a']);
});
test('a locked reference can guide selection and angle wrap remains close',()=>{
  const r=make('reference',{locked:true,rotation:179,source_rotation:179});
  assert.deepEqual(B.similar([make('peer',{rotation:-180,source_rotation:-180})],r),['reference','peer']);
});
test('invalid or preserved reference never expands selection',()=>{
  for(const r of [null,{...base,enabled:false},{...base,kind:'formula'},{...base,font_size:NaN},{...base,text:' '}])assert.deepEqual(B.similar([base],r),[]);
});
test('reference style copies face, integer size and stroke while preserving source, color and placement',()=>{
  const target=make('target',{font_id:'other',font_label:'Other',font_size:39,stroke_width:0,letter_spacing:3,color:'#ab1234',x:200,y:100,rotation:7,source_rotation:7,color_mode:'multi',color_runs:[{start:0,end:2,color:'#aa1111'}],score:.8,fit_status:'fitted'});
  const before=structuredClone(target),result=B.fromReference([base,target],base,font);
  assert.equal(result.changes.length,1);assert.equal(result.changes[0].id,'target');
  const next={...target,...result.changes[0].patch};
  for(const key of ['font_id','font_label','font_size','stroke_width'])assert.equal(next[key],base[key]);
  for(const key of ['text','x','y','bbox','color','color_mode','color_runs','letter_spacing','rotation','source_rotation'])assert.deepEqual(next[key],before[key]);
  assert.equal(next.fit_status,'edited');assert.equal(next.score,null);assert.deepEqual(target,before);
});
test('reference copy excludes formulas, preserved, locked, empty text and the reference itself',()=>{
  const r=make('reference',{locked:true}),different={font_size:38,font_id:'other'};
  const rs=[r,make('normal',different),make('locked',{...different,locked:true}),make('formula',{...different,kind:'formula'}),make('preserved',{...different,enabled:false}),make('empty',{...different,text:''})];
  assert.deepEqual(B.fromReference(rs,r,font).changes.map(c=>c.id),['normal']);
});
test('same reference style produces no change or undo action',()=>{
  assert.deepEqual(B.fromReference([base,make('other')],base,font).changes,[]);
});
test('unknown reference font fails before mutating any target',()=>{
  const rs=[base,make('other',{font_size:39})],before=structuredClone(rs);
  assert.throws(()=>B.fromReference(rs,base,undefined));assert.deepEqual(rs,before);
});
