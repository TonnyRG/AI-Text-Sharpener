const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const BatchStyle=require('../src/ai_text_sharpener/web/batch-style.js');

const web=path.join(__dirname,'../src/ai_text_sharpener/web');
const source=fs.readFileSync(path.join(web,'app.js'),'utf8');
const html=fs.readFileSync(path.join(web,'index.html'),'utf8');
function between(start,end){
  const a=source.indexOf(start),b=source.indexOf(end,a+start.length);
  assert.ok(a>=0&&b>a,`Missing UI source: ${start}`);
  return source.slice(a,b);
}
const implementation=[
  between('function historySnapshot()', 'function rememberJobChanges('),
  between('function setSelection(ids)', 'function fontOptions('),
  between('async function applyBatchStyle(', "$('selectSimilarStyleBtn').onclick="),
  between('function undoRedo(', "$('undoBtn').onclick="),
  between("const batchFields=", 'function batchFontOptions('),
  between("for(const [id,key] of batchFields)$(id).addEventListener(", "$('batchFontSearch').oninput="),
  between("$('applyBatchRotationBtn').onclick=", "for(const button of $('batchAlignment').querySelectorAll('button'))button.onclick="),
].join('\n');

function harness(){
  const fieldTag=html.match(/<input\b[^>]*\bid="batchRotationField"[^>]*>/)?.[0];
  assert.ok(fieldTag,'Angle input is present in the real page');
  const fieldDefault=fieldTag.match(/\bvalue="([^"]*)"/)?.[1];
  const element=(value='')=>({value,listeners:{},addEventListener(name,fn){this.listeners[name]=fn;}});
  const elements={batchRotationField:element(fieldDefault),applyBatchRotationBtn:element()};
  const pending=[],calls={dirty:0,toasts:[]};
  const region=(id,rotation,extra={})=>({id,rotation,kind:'text',text:id,enabled:true,
    font_id:'sans',font_size:36,letter_spacing:0,stroke_width:0,color:'#123456',
    x:25,y:40,bbox:[20,35,160,40],source_rotation:rotation,source_quad:[[20,35],[180,36],[179,75],[19,74]],...extra});
  const p={id:'page',regions:[region('a',1.3),region('b',-.7),
    region('math',2.5,{kind:'formula',latex:'x^2'}),region('locked',4.2,{locked:true}),
    region('original',-2.8,{enabled:false,preserve_original:true}),region('unselected',15)]};
  const context={
    project:{id:'project',pages:[p]},pageId:p.id,selectedId:'a',selectedIds:p.regions.slice(0,5).map(r=>r.id),
    styleReferenceId:null,editingBox:false,editGroup:null,pointer:null,busy:false,mutation:0,
    undo:[],redo:[],fonts:[],BatchStyle,
    $:id=>elements[id]||(elements[id]=element()),clone:value=>structuredClone(value),
    page:()=>context.project.pages.find(p=>p.id===context.pageId),
    selection:()=>context.selectedIds,
    selectedRegions:()=>context.page().regions.filter(r=>context.selectedIds.includes(r.id)),
    safeRun:fn=>(...args)=>{
      const action=Promise.resolve().then(()=>fn(...args)).catch(error=>calls.toasts.push(error.message));
      pending.push(action);return action;
    },
    setBusy:value=>{context.busy=value;},
    markDirty:()=>{context.mutation++;calls.dirty++;},
    renderRegions:()=>{},renderInspector:()=>{},renderBatchStyles:()=>{},
    updateBoxButton:()=>{},updateCanvasHint:()=>{},toast:message=>calls.toasts.push(message),
  };
  elements.applyBatchRotationBtn.click=()=>elements.applyBatchRotationBtn.onclick();
  vm.createContext(context);vm.runInContext(implementation,context);
  return {context,field:elements.batchRotationField,button:elements.applyBatchRotationBtn,calls,
    settle:()=>Promise.all(pending),
    key:extra=>{
      const event={key:'Enter',prevented:false,preventDefault(){this.prevented=true;},...extra};
      elements.batchRotationField.onkeydown(event);return event;
    }};
}

test('default zero applies to selected text and formulas once; one undo restores all original angles',async()=>{
  const h=harness(),before=structuredClone(h.context.page().regions);
  assert.equal(h.field.value,'0');
  await h.button.onclick();
  const after=structuredClone(h.context.page().regions);
  assert.deepEqual(after.map(r=>r.rotation),[0,0,0,4.2,-2.8,15]);
  assert.equal(h.context.undo.length,1);assert.equal(h.calls.dirty,1);
  for(let i=0;i<after.length;i++)for(const key of ['x','y','bbox','source_rotation','source_quad','font_size','letter_spacing'])
    assert.deepEqual(after[i][key],before[i][key],`${key} must stay unchanged`);
  h.context.undoRedo();assert.deepEqual(h.context.page().regions,before);
  assert.equal(h.context.undo.length,0);assert.equal(h.context.redo.length,1);
  h.context.undoRedo(true);assert.deepEqual(h.context.page().regions,after);
});

test('typing a decimal angle does not mutate text; Enter applies the exact target',async()=>{
  const h=harness(),before=structuredClone(h.context.page().regions);
  h.field.value='-12.5';
  if(h.field.listeners.input)await h.field.listeners.input();
  if(h.field.oninput)await h.field.oninput();
  assert.deepEqual(h.context.page().regions,before);assert.equal(h.context.undo.length,0);
  const event=h.key({});await h.settle();
  assert.equal(event.prevented,true);
  assert.deepEqual(h.context.page().regions.slice(0,3).map(r=>r.rotation),[-12.5,-12.5,-12.5]);
  assert.equal(h.context.undo.length,1);
});

for(const modifiers of [{ctrlKey:true},{metaKey:true},{isComposing:true}])
test(`modified or composing Enter does not apply rotation: ${JSON.stringify(modifiers)}`,async()=>{
  const h=harness(),before=structuredClone(h.context.page().regions);
  h.key(modifiers);await h.settle();
  assert.deepEqual(h.context.page().regions,before);assert.equal(h.context.undo.length,0);
});

test('changing selection resets the requested angle to zero without editing any region',()=>{
  const h=harness(),before=structuredClone(h.context.page().regions);
  h.field.value='15';h.context.setSelection(['b','math']);
  assert.equal(h.field.value,'0');assert.deepEqual(Array.from(h.context.selectedIds),['b','math']);
  assert.deepEqual(h.context.page().regions,before);assert.equal(h.context.undo.length,0);
});

test('reapplying zero to horizontal text does not add another undo entry',async()=>{
  const h=harness();await h.button.onclick();await h.button.onclick();
  assert.equal(h.context.undo.length,1);assert.equal(h.calls.dirty,1);
});

test('invalid requested angle leaves the entire selection and undo stack unchanged',async()=>{
  for(const value of ['', '181', '-181', 'NaN']){
    const h=harness(),before=structuredClone(h.context.page().regions);h.field.value=value;
    await h.button.onclick();
    assert.deepEqual(h.context.page().regions,before);assert.equal(h.context.undo.length,0);
    assert.equal(h.calls.dirty,0);assert.ok(h.calls.toasts.length);
  }
});
