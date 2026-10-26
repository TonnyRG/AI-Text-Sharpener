const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const BatchStyle=require('../src/ai_text_sharpener/web/batch-style.js');

// Execute the actual async UI handler; a deferred preview models navigation or
// an edit completing while validation is in flight, without a browser/model.
const source=fs.readFileSync(path.join(__dirname,'../src/ai_text_sharpener/web/app.js'),'utf8');
const start=source.indexOf("$('unifyStyleBtn').onclick=safeRun(async()=>{");
const end=source.indexOf('\n});',start);
assert.ok(start>=0&&end>start,'The unify-style handler must be present');
const handler=source.slice(start,end+4);

function harness(){
  const region=(id,extra={})=>({id,text:id,kind:'text',enabled:true,locked:false,
    font_id:'regular',font_size:40,stroke_width:.15,x:20,y:30,...extra});
  const original={id:'page-a',regions:[region('reference'),region('target',{font_id:'other',font_size:39,stroke_width:0})]};
  const next={id:'page-b',regions:[region('another',{font_size:50})]};
  const button={},calls={history:[],dirty:0,requests:[],toasts:[]};
  let resolve,reject;
  const pending=new Promise((yes,no)=>{resolve=yes;reject=no;});
  const context={
    busy:false,mutation:0,project:{id:'project-a',pages:[original,next]},pageId:original.id,
    styleReferenceId:'reference',fonts:[{id:'regular',label:'Regular'}],BatchStyle,
    $:()=>button,clone:value=>structuredClone(value),
    page:()=>context.project.pages.find(p=>p.id===context.pageId),
    selectedRegions:()=>context.page().regions,
    safeRun:fn=>(...args)=>Promise.resolve().then(()=>fn(...args)).catch(error=>calls.toasts.push(error.message)),
    setBusy:value=>{context.busy=value;},
    api:(url,body)=>{calls.requests.push({url,body});return pending;},
    history:()=>calls.history.push({page:context.pageId,regions:structuredClone(context.page().regions)}),
    markDirty:()=>{calls.dirty++;context.mutation++;},
    renderRegions:()=>{},renderInspector:()=>{},
    toast:message=>calls.toasts.push(message),
  };
  vm.createContext(context);vm.runInContext(handler,context);
  return {context,original,next,calls,resolve,reject,start:async()=>{
    const action=button.onclick();
    await Promise.resolve(); // safeRun starts the real handler in a microtask.
    assert.equal(calls.requests.length,1);
    assert.equal(context.busy,true);
    return {action};
  }};
}

test('successful style validation applies once and stores one pre-change undo snapshot',async()=>{
  const h=harness(),before=structuredClone(h.original.regions);
  const {action}=await h.start();
  assert.deepEqual(h.original.regions,before,'No speculative mutation before preview succeeds');
  assert.equal(h.calls.history.length,0);
  h.resolve({});await action;
  assert.equal(h.calls.history.length,1);
  assert.deepEqual(h.calls.history[0],{page:'page-a',regions:before});
  const target=h.original.regions[1];
  assert.equal(target.font_id,'regular');assert.equal(target.font_size,40);assert.equal(target.stroke_width,.15);
  assert.equal(h.calls.dirty,1);assert.equal(h.context.busy,false);
});

test('preview failure leaves styles and undo untouched',async()=>{
  const h=harness(),before=structuredClone(h.original.regions);
  const {action}=await h.start();h.reject(new Error('Missing target glyph'));await action;
  assert.deepEqual(h.original.regions,before);
  assert.equal(h.calls.history.length,0);assert.equal(h.calls.dirty,0);
  assert.equal(h.context.busy,false);assert.ok(h.calls.toasts.includes('Missing target glyph'));
});

for(const [name,change] of [
  ['page changes',h=>{h.context.pageId=h.next.id;}],
  ['project changes',h=>{h.context.project={id:'project-b',pages:[structuredClone(h.original)]};}],
  ['same-id project reloads',h=>{h.context.project=structuredClone(h.context.project);}],
  ['same-id page is replaced',h=>{h.context.project.pages[0]=structuredClone(h.original);}],
  ['another edit changes the page',h=>{h.original.regions[1].font_size=45;h.context.mutation++;}],
])test(`stale validation is discarded when ${name}`,async()=>{
  const h=harness();const {action}=await h.start();change(h);
  const expectedOriginal=structuredClone(h.original),expectedCurrent=structuredClone(h.context.project);
  h.resolve({});await action;
  assert.deepEqual(h.original,expectedOriginal,'The old page must not receive stale style patches');
  assert.deepEqual(h.context.project,expectedCurrent,'The current project must not receive stale style patches');
  assert.equal(h.calls.history.length,0,'A stale action must not add undo history to either page');
  assert.equal(h.calls.dirty,0);assert.equal(h.context.busy,false);
  assert.ok(h.calls.toasts.length,'Explain that the validation no longer matches current state');
});
