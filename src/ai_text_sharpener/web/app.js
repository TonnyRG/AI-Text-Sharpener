'use strict';
const $ = id => document.getElementById(id);
let token = '', fonts = [], project = null, pageId = null, selectedId = null;
let mode = 'original', dirty = false, busy = false, mutation = 0, saving = null;
let saveTimer, toastTimer, newImport = false, drawing = false, pointer = null;
let undo = [], redo = [], pendingDownload = null;
const pageHistories = new Map();
let historyProjectId = null, editGroup = null;
let previewTimer, previewRunning = false, previewVersion = 0, previewUrl = null, previewAutoShow = false;
let editingBox = false;
const page = () => project?.pages.find(p => p.id === pageId);
const region = () => page()?.regions.find(r => r.id === selectedId);
const clone = value => JSON.parse(JSON.stringify(value));
const asset = (file, download = false) => `/asset?project=${project.id}&file=${file}${download ? '&download=1' : ''}&v=${project.revision}`;

function toast(message, error = false) {
  clearTimeout(toastTimer); $('toast').textContent = message; $('toast').classList.toggle('error', error);
  $('toast').hidden = false; toastTimer = setTimeout(() => $('toast').hidden = true, error ? 9000 : 5000);
}
async function api(path, body) {
  const options = body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-Studio-Token':token},body:JSON.stringify(body)};
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '操作失败');
  return result;
}
function safeRun(fn) { return (...args) => Promise.resolve().then(() => fn(...args)).catch(e => toast(e.message, true)); }
function setBusy(value) {
  busy = value; document.body.classList.toggle('busy', value);
  for (const id of ['analyzeBtn','analyzeAllBtn','exportAllBtn','exportBtn','previewBtn','drawBtn','importBtn','newBtn','projectSelect','demoBtn','fitBtn','fitFontBtn','recognizeFormulaBtn','fitFormulaBtn','svgExport','pngExport','pptExport','jsonExport']) {
    $(id).disabled = value || (['analyzeBtn','analyzeAllBtn','exportAllBtn','exportBtn','previewBtn','drawBtn'].includes(id) && !page());
  }
  $('undoBtn').disabled = value || !undo.length; $('redoBtn').disabled = value || !redo.length;
}
function bindHistory() {
  if(historyProjectId!==project?.id){pageHistories.clear();historyProjectId=project?.id;}
  if(!pageHistories.has(pageId))pageHistories.set(pageId,{undo:[],redo:[]});
  ({undo,redo}=pageHistories.get(pageId));editGroup=null;
}
function historySnapshot() { return {regions:clone(page().regions),selectedId}; }
function pushHistory(stack,snapshot) {stack.push(snapshot);if(stack.length>80)stack.shift();}
function history(group=null) {
  if (!page()) return;
  const key=group?`${pageId}:${selectedId}:${group}`:null, now=Date.now();
  // Consecutive typing in one field is one edit; discrete actions remain separate.
  if(!key||editGroup?.key!==key||now-editGroup.time>1000)pushHistory(undo,historySnapshot());
  editGroup=key?{key,time:now}:null;redo.length=0;
  setBusy(busy);
}
function rememberJobChanges(before) {
  for(const p of project.pages){
    const previous=before.find(item=>item.id===p.id);
    if(!previous)continue;
    // Preview/export may refresh derived geometry without editing the region.
    const content=regions=>JSON.stringify(regions.map(({ink_width,ink_height,...r})=>r));
    if(content(previous.regions)===content(p.regions))continue;
    if(!pageHistories.has(p.id))pageHistories.set(p.id,{undo:[],redo:[]});
    const history=pageHistories.get(p.id);
    pushHistory(history.undo,{regions:previous.regions,selectedId:previous.selectedId});history.redo.length=0;
  }
  bindHistory();setBusy(busy);
}
function markDirty() {
  dirty = true; mutation++; $('saveState').textContent = '· 尚未保存';
  page().render_revision=-1;
  $('canvasHint').textContent = '预览待更新…';
  queuePreview();
  clearTimeout(saveTimer); saveTimer = setTimeout(() => flush().catch(e => toast(e.message, true)), 650);
}
function resetPreview() {
  clearTimeout(previewTimer); previewVersion++; previewAutoShow = false;
  if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl=null;
  editingBox=false;pointer=null;$('editBoxBtn').classList.remove('primary');
}
function queuePreview() {
  previewVersion++; previewAutoShow=true; clearTimeout(previewTimer);
  previewTimer=setTimeout(()=>updatePreview().catch(e=>toast(e.message,true)),450);
}
async function updatePreview() {
  if(!page()||busy)return;
  if(previewRunning)return; // The active request will request the newest snapshot.
  clearTimeout(previewTimer);
  const version=previewVersion, pid=project.id, selectedPage=pageId;
  previewRunning=true;$('canvasHint').textContent='正在更新预览…';
  try {
    const result=await api('/api/preview',{project_id:pid,page_id:selectedPage,regions:clone(page().regions)});
    if(version!==previewVersion||project?.id!==pid||pageId!==selectedPage||busy)return;
    const old=previewUrl;previewUrl=URL.createObjectURL(new Blob([result.svg],{type:'image/svg+xml'}));
    $('resultImage').src=previewUrl;if(old)URL.revokeObjectURL(old);
    for(const geometry of result.regions){const r=page().regions.find(r=>r.id===geometry.id);if(r)Object.assign(r,geometry);}
    if(previewAutoShow&&mode==='original'&&!drawing)setMode('result');else setMode(mode);
    drawOverlay();$('canvasHint').textContent='预览已更新 · 拖动绿色框移动文字；橙色框用于识别和擦除原字。';
  } catch(e) {
    if(version===previewVersion){$('canvasHint').textContent='预览未更新：'+e.message;throw e;}
  } finally {
    previewRunning=false;
    if(version!==previewVersion&&page()&&!busy) {
      clearTimeout(previewTimer);previewTimer=setTimeout(()=>updatePreview().catch(e=>toast(e.message,true)),100);
    }
  }
}
async function flush() {
  clearTimeout(saveTimer);
  if (saving) { await saving; if (dirty) return flush(); return; }
  if (!dirty || !project) return;
  const stamp = mutation;
  $('saveState').textContent = '· 保存中';
  saving = api('/api/save', clone(project));
  try {
    const saved = await saving;
    project.revision = saved.revision;
    if (stamp === mutation) dirty = false;
    $('saveState').textContent = dirty ? '· 尚未保存' : '· 已保存';
  } finally { saving = null; }
  if (dirty) return flush();
}
async function refreshProjects() {
  const boot = await api('/api/boot'); token = boot.token;
  fonts = boot.fonts;
  $('dataPath').textContent = `项目保存位置：${boot.data_dir}`;
  $('projectSelect').replaceChildren(new Option('选择项目', ''));
  for (const p of boot.projects) $('projectSelect').add(new Option(`${p.name} · ${p.pages} 页`, p.id));
  if (project) $('projectSelect').value = project.id;
  return boot;
}
async function loadProject(id, preferredPage) {
  resetPreview();
  project = await api(`/api/project?id=${encodeURIComponent(id)}`);
  pageId = project.pages.some(p => p.id === preferredPage) ? preferredPage : project.pages[0]?.id;
  selectedId = null; dirty = false; bindHistory();
  localStorage.setItem('sharpener-project', id);
  $('projectSelect').value = id; renderProject();
}
function renderProject() {
  const p = page();
  $('welcome').hidden = !!p; $('editor').hidden = !p;
  $('pageTitle').textContent = p ? p.name : '未打开项目';
  $('pageMeta').textContent = p ? `${p.width} × ${p.height} px · ${project.name}` : '导入文件或选择已有项目';
  $('pageCount').textContent = project?.pages.length || 0;
  const allPages=project?.pages||[], processed=allPages.filter(p=>!p.pending_rescan&&(p.status==='review'||p.regions.length)).length;
  $('batchSummary').textContent=allPages.length?`${processed} / ${allPages.length} 页已完成 · 可重新识别全部或继续未完成页面`:'导入后可批量处理全部页面';
  $('pages').replaceChildren();
  for (const item of project?.pages || []) {
    const button = document.createElement('button'); button.className = `page-card ${item.id === pageId ? 'selected' : ''}`;
    const img = document.createElement('img'); img.src = asset(`${item.id}.png`); img.alt = item.name;
    const label = document.createElement('span'); label.textContent = `${item.name} · ${item.status==='error'?'处理失败':item.pending_rescan?'待重新识别':item.status==='review'||item.regions.length?'已处理':'未处理'}`;
    if(item.error)button.title=item.error;
    button.append(img, label); button.onclick = safeRun(async () => {
      if (busy) return; await flush(); resetPreview();pageId = item.id; selectedId = null; bindHistory(); mode='original'; renderProject();
    }); $('pages').append(button);
  }
  if (p) {
    $('sourceImage').src = asset(`${p.id}.png`);
    const hasResult = p.render_revision >= 0;
    if (hasResult) $('resultImage').src = asset(`${p.id}-result.svg`);
    else { $('resultImage').removeAttribute('src'); mode = 'original'; }
    $('overlay').setAttribute('viewBox', `0 0 ${p.width} ${p.height}`);
    $('sheet').style.aspectRatio = `${p.width}/${p.height}`;
    $('canvasHint').textContent = p.regions.length ? '编辑后自动更新预览；拖动绿色框移动文字，点击「调整 OCR 框」修改原字范围。' : '点击「识别当前页」或「识别整个 PPT」，或手动画框添加文字。';
  }
  renderRegions(); renderInspector(); setMode(mode); setBusy(busy);
  requestAnimationFrame(resize);
}
function renderRegions() {
  $('regions').replaceChildren(); $('regionCount').textContent = page()?.regions.length || 0;
  for (const [idx, r] of (page()?.regions || []).entries()) {
    const button = document.createElement('button'); button.className=`region-row ${r.id===selectedId?'selected':''}`;
    const dot=document.createElement('i'); dot.className=`dot ${!r.enabled?'off':r.score!=null&&r.score<.65?'warning':''}`;
    const label=document.createElement('span'); label.className='label'; label.textContent=`${String(idx+1).padStart(2,'0')}  ${r.kind==='formula'?'ƒ '+(r.latex||'公式（保留原图）'):(r.text || '空文字')}`;
    button.append(dot,label); button.title=r.kind==='formula'?(r.latex||'公式（保留原图）'):r.text; button.onclick=()=>{if(!busy)select(r.id);}; $('regions').append(button);
  }
  drawOverlay();
}
function select(id) { if(selectedId!==id)editGroup=null;selectedId=id; renderRegions(); renderInspector(); }
function fontOptions() {
  const filter=$('fontSearch').value.toLowerCase(), selected=region()?.font_id;
  $('fontField').replaceChildren();
  for(const f of fonts) if(f.id===selected||f.label.toLowerCase().includes(filter)) $('fontField').add(new Option(f.label,f.id));
  $('fontField').value=selected||'';
}
function renderInspector() {
  const r=region(); $('noSelection').hidden=!!r; $('properties').hidden=!r;
  if(!r)return;
  const math=r.kind==='formula';$('kindField').value=math?'formula':'text';$('formulaPanel').hidden=!math;$('plainTextLabel').hidden=math;
  $('latexField').value=r.latex||'';
  for(const id of ['fontSearch','fontField','fitBtn','fitFontBtn'])$(id).hidden=math;
  $('spacingField').closest('label').hidden=math;
  $('regionName').textContent=`区域 ${page().regions.indexOf(r)+1}`;
  renderFitStatus(r);
  $('textField').value=r.text; $('originalText').textContent=math?'完整公式区域 · LaTeX 可编辑':`原识别：${r.original_text||'手动添加'}`;
  $('enabledField').checked=r.enabled; $('lockedField').checked=!!r.locked;
  $('sizeField').value=r.font_size; $('spacingField').value=r.letter_spacing||0;
  $('strokeField').value=r.stroke_width||0;
  $('xField').value=r.x; $('yField').value=r.y; $('colorField').value=r.color;
  renderBoxFields();
  $('colorValue').textContent=r.color.toUpperCase(); $('eraseField').value=r.erase_mode||'gradient';
  $('scoreText').textContent=r.score==null?'':`相似度 ${(r.score*100).toFixed(1)}`;
  $('fitNote').textContent=r.fit_note||'可尝试不同字体候选，再对照原图微调。';
  fontOptions(); $('alternatives').replaceChildren();
  for(const c of r.alternatives||[]) {
    const btn=document.createElement('button');btn.className='alternative';
    const label=document.createElement('span'); label.textContent=c.font_label;
    const value=document.createElement('small');value.textContent=(c.score*100).toFixed(1);btn.append(label,value);
    btn.onclick=safeRun(async()=>{if(busy)return;history();Object.assign(r,c);markDirty();renderInspector();drawOverlay();});
    $('alternatives').append(btn);
  }
}
function renderFitStatus(r) {
  $('fitBadge').textContent=!r.enabled?'保留原图':r.locked?'已锁定':r.kind==='formula'?'公式待复核':r.score==null?'待匹配':r.score<.65?'建议复核':'已匹配';
  $('fitBadge').classList.toggle('warning',r.enabled&&r.score!=null&&r.score<.65);
  $('scoreText').textContent=r.score==null?'':`相似度 ${(r.score*100).toFixed(1)}`;
}
function changeField(id,key,convert=v=>v) {
  $(id).addEventListener('input',()=>{
    const r=region();if(!r||busy)return; const raw=$(id).type==='checkbox'?$(id).checked:$(id).value;
    if($(id).type==='number'&&(raw===''||!$(id).checkValidity()))return;
    const value=convert(raw); if(typeof value==='number'&&!Number.isFinite(value))return;
    if(r[key]===value)return;
    history(['text','latex','font_size','letter_spacing','stroke_width','x','y'].includes(key)?id:null);r[key]=value;
    if(['text','latex','font_id','font_size','letter_spacing','stroke_width','x','y'].includes(key)){r.score=null;r.fit_status='edited';r.alternatives=[];$('alternatives').replaceChildren();}
    if(key==='enabled'&&r.kind!=='formula'){r.score=null;r.fit_status='edited';}
    if(key==='text')r.text=r.text.replace(/[\r\n]+/g,' ');
    if(key==='color')$('colorValue').textContent=value.toUpperCase();
    markDirty();renderRegions();renderFitStatus(r);
  });
}
changeField('latexField','latex');changeField('textField','text');changeField('fontField','font_id');changeField('sizeField','font_size',Number);
changeField('spacingField','letter_spacing',Number);changeField('xField','x',Number);changeField('yField','y',Number);
changeField('strokeField','stroke_width',Number);
changeField('colorField','color');changeField('enabledField','enabled');changeField('lockedField','locked');changeField('eraseField','erase_mode');
$('fontSearch').oninput=fontOptions;
$('kindField').onchange=()=>{
  const r=region();if(!r||busy)return;history();r.kind=$('kindField').value;r.score=null;r.alternatives=[];
  if(r.kind==='formula'){r.latex=r.latex||'';r.enabled=false;r.fit_note='调整 OCR 框以包含完整公式，再点击「识别公式」。';}
  else {r.font_id=r.font_id||fonts[0]?.id;r.text=r.text||r.original_text||'';}
  r.fit_status='edited';markDirty();renderInspector();renderRegions();
};
$('recognizeFormulaBtn').onclick=safeRun(async()=>{if(region()?.locked)throw new Error('请先取消锁定。');await runJob('formula_recognize',{region_id:selectedId});});
$('fitFormulaBtn').onclick=safeRun(async()=>{if(region()?.locked)throw new Error('请先取消锁定。');await runJob('formula_fit',{region_id:selectedId});});

const boxFields=['boxXField','boxYField','boxWField','boxHField'];
function renderBoxFields(){const r=region();if(r)boxFields.forEach((id,i)=>$(id).value=Math.round(r.bbox[i]*100)/100);}
function updateBox(bbox){
  const r=region();r.bbox=bbox;r.score=null;r.fit_status='edited';r.alternatives=[];
  $('alternatives').replaceChildren();renderFitStatus(r);renderBoxFields();
}
boxFields.forEach((id,index)=>$(id).addEventListener('input',()=>{
  if(!region()||busy||$(id).value===''||!$(id).checkValidity())return;
  const box=region().bbox.slice();box[index]=Number($(id).value);
  if(box[0]<0||box[1]<0||box[2]<3||box[3]<3||box[0]+box[2]>page().width||box[1]+box[3]>page().height)return;
  history(id);updateBox(box);markDirty();drawOverlay();
}));
$('editBoxBtn').onclick=()=>{editingBox=!editingBox;drawing=false;$('drawBtn').classList.remove('primary');document.body.classList.remove('drawing-mode');$('editBoxBtn').classList.toggle('primary',editingBox);$('boxesChk').checked=true;drawOverlay();};

function rect(x,y,w,h,classes) {
  const el=document.createElementNS('http://www.w3.org/2000/svg','rect');
  for(const [key,value]of Object.entries({x,y,width:w,height:h,class:classes}))el.setAttribute(key,value);
  return el;
}
function drawOverlay() {
  const overlay=$('overlay');overlay.replaceChildren();
  if(!$('boxesChk').checked&&!drawing)return;
  for(const r of page()?.regions||[]) {
    const [bx,by,bw,bh]=r.bbox;
    if(r.id===selectedId){const erase=rect(bx,by,bw,bh,'erase');overlay.append(erase);}
    const box=rect(r.enabled?r.x:bx,r.enabled?r.y:by,r.enabled?(r.ink_width||bw):bw,r.enabled?(r.ink_height||bh):bh,
      `${r.id===selectedId?'selected':''} ${!r.enabled?'off':''}`);
    box.dataset.id=r.id;overlay.append(box);
  }
  const r=region();
  if(editingBox&&r){
    const [x,y,w,h]=r.bbox,box=rect(x,y,w,h,'erase editable');box.dataset.id=r.id;box.dataset.handle='move';overlay.append(box);
    const size=9*page().width/Math.max(1,$('sheet').getBoundingClientRect().width);
    for(const [handle,fx,fy]of [['nw',0,0],['n',.5,0],['ne',1,0],['e',1,.5],['se',1,1],['s',.5,1],['sw',0,1],['w',0,.5]]){
      const dot=rect(x+w*fx-size/2,y+h*fy-size/2,size,size,'box-handle');dot.dataset.id=r.id;dot.dataset.handle=handle;dot.style.cursor=handle+'-resize';overlay.append(dot);
    }
  }
  if(pointer?.type==='draw')overlay.append(rect(Math.min(pointer.sx,pointer.ex),Math.min(pointer.sy,pointer.ey),Math.abs(pointer.ex-pointer.sx),Math.abs(pointer.ey-pointer.sy),'drawing'));
}
function resize() {
  const p=page();if(!p)return;
  const viewport=$('viewport'), zoom=$('zoom').value;
  const scale=zoom==='fit'?Math.max(.05,Math.min((viewport.clientWidth-60)/p.width,(viewport.clientHeight-60)/p.height)):Number(zoom);
  $('sheet').style.width=`${p.width*scale}px`;$('sheet').style.height=`${p.height*scale}px`;
}
function setMode(next) {
  const p=page();
  if(next!=='original'&&(!p||(p.render_revision<0&&!previewUrl))){next='original';}
  mode=next;
  for(const b of $('viewModes').children)b.classList.toggle('active',b.dataset.mode===mode);
  $('resultImage').hidden=mode==='original';$('compareLine').hidden=mode!=='compare';$('compareControl').hidden=mode!=='compare';
  compare();
}
function compare() {
  const value=Number($('compareRange').value);
  $('resultImage').style.clipPath=mode==='compare'?`inset(0 0 0 ${value}%)`:'';
  $('compareLine').style.left=`${value}%`;
}
function position(evt) {const b=$('sheet').getBoundingClientRect();const p=page();return{x:(evt.clientX-b.left)*p.width/b.width,y:(evt.clientY-b.top)*p.height/b.height};}
$('overlay').addEventListener('pointerdown',evt=>{
  if(busy||!page())return;const pos=position(evt);
  if(drawing)pointer={type:'draw',sx:pos.x,sy:pos.y,ex:pos.x,ey:pos.y};
  else if(evt.target.dataset.id){const handle=evt.target.dataset.handle;select(evt.target.dataset.id);const r=region();
    if(handle)pointer={type:'box',handle,sx:pos.x,sy:pos.y,bbox:r.bbox.slice(),moved:false};
    else if(r.enabled&&!r.locked){pointer={type:'move',sx:pos.x,sy:pos.y,x:r.x,y:r.y,moved:false};}}
  if(pointer){$('overlay').setPointerCapture(evt.pointerId);evt.preventDefault();}
});
$('overlay').addEventListener('pointermove',evt=>{
  if(!pointer)return;const pos=position(evt);
  if(pointer.type==='draw'){pointer.ex=pos.x;pointer.ey=pos.y;}
  else {
    const dx=pos.x-pointer.sx,dy=pos.y-pointer.sy;if(!pointer.moved&&Math.abs(dx)+Math.abs(dy)<.5)return;
    if(!pointer.moved){history();pointer.moved=true;}
    if(pointer.type==='box'){
      const [x,y,w,h]=pointer.bbox,k=pointer.handle;let left=x,top=y,right=x+w,bottom=y+h;
      if(k==='move'){left=Math.max(0,Math.min(page().width-w,x+dx));top=Math.max(0,Math.min(page().height-h,y+dy));right=left+w;bottom=top+h;}
      else{if(k.includes('w'))left=Math.max(0,Math.min(right-3,x+dx));if(k.includes('e'))right=Math.min(page().width,Math.max(left+3,x+w+dx));if(k.includes('n'))top=Math.max(0,Math.min(bottom-3,y+dy));if(k.includes('s'))bottom=Math.min(page().height,Math.max(top+3,y+h+dy));}
      updateBox([left,top,right-left,bottom-top]);
    }else{const r=region();r.fit_status='edited';r.score=null;r.x=Math.round((pointer.x+dx)*2)/2;r.y=Math.round((pointer.y+dy)*2)/2;$('xField').value=r.x;$('yField').value=r.y;}
  }
  drawOverlay();
});
$('overlay').addEventListener('pointerup',evt=>{
  if(!pointer)return;
  if(pointer.type==='draw') {
    const x=Math.max(0,Math.min(pointer.sx,pointer.ex)),y=Math.max(0,Math.min(pointer.sy,pointer.ey));
    const w=Math.min(page().width-x,Math.abs(pointer.ex-pointer.sx)),h=Math.min(page().height-y,Math.abs(pointer.ey-pointer.sy));
    if(w>=10&&h>=8){history();const r={id:crypto.randomUUID().replaceAll('-','').slice(0,12),text:'请输入文字',original_text:'',bbox:[x,y,w,h],x,y,font_id:fonts.find(f=>f.family==='Microsoft YaHei'&&f.style==='Regular')?.id||fonts[0].id,font_size:Math.max(4,Math.min(1000,h)),letter_spacing:0,color:'#182029',enabled:true,locked:false,erase_mode:'gradient',score:null};page().regions.push(r);selectedId=r.id;markDirty();renderRegions();renderInspector();$('textField').focus();$('textField').select();}
    drawing=false;document.body.classList.remove('drawing-mode');$('drawBtn').classList.remove('primary');
  }else if(pointer.moved)markDirty();
  pointer=null;drawOverlay();try{$('overlay').releasePointerCapture(evt.pointerId);}catch{}
});
$('overlay').addEventListener('pointercancel',()=>{if(pointer?.moved)markDirty();pointer=null;drawOverlay();});

async function runJob(kind, extra={}) {
  if(busy||!project)return;
  clearTimeout(previewTimer);previewVersion++;await flush();setBusy(true);
  try {
    const result=await api('/api/job',{kind,project_id:project.id,page_id:pageId,revision:project.revision,...extra});
    const before=project.pages.map(p=>({id:p.id,regions:clone(p.regions),selectedId:p.id===pageId?selectedId:null}));
    await watchJob(result.id,before);
  }catch(e){setBusy(false);$('jobBar').hidden=true;throw e;}
}
async function watchJob(id, before=null) {
  setBusy(true);$('jobBar').hidden=false;
  for(;;){
    const job=await api('/api/job');
    if(id&&job.id!==id)throw new Error('后台任务已变化，请刷新。');
    $('jobMessage').textContent=job.message;$('progress').value=job.progress||0;
    if(!job.active){
      $('jobBar').hidden=true;setBusy(false);
      const selected=selectedId, keepMode=mode;
      await loadProject(job.project_id,job.page_id||pageId);
      if(before)rememberJobChanges(before);
      selectedId=page()?.regions.some(r=>r.id===selected)?selected:page()?.regions[0]?.id;
      renderInspector();renderRegions();setMode(keepMode==='compare'?'compare':'result');
      if(job.status==='error'){pendingDownload=null;throw new Error(job.message);}
      if(job.status==='cancelled'){pendingDownload=null;toast(job.message);return;}
      $('saveState').textContent='· 已保存';
      if(job.download)download(job.download);
      if(pendingDownload){download(asset(`${pageId}-result.${pendingDownload}`,true));pendingDownload=null;}
      if(job.kind==='analyze_all')$('batchSummary').textContent=job.message;
      toast(job.kind==='analyze_all'?job.message:job.warnings?.length?job.warnings.slice(0,2).join('；'):'已完成，可切换滑动对比检查效果。');
      return;
    }
    await new Promise(resolve=>setTimeout(resolve,450));
  }
}
function download(url){const a=document.createElement('a');a.href=url;a.download='';document.body.append(a);a.click();a.remove();}
async function upload(files){
  if(!files.length||busy)return;await flush();setBusy(true);
  try{
    let pid=newImport?null:project?.id;newImport=false;let firstNew=null;
    for(const file of files){
      toast(`正在导入 ${file.name}…`);
      const response=await fetch('/api/import'+(pid?`?project=${pid}`:''),{method:'POST',headers:{'X-Studio-Token':token,'X-Filename':encodeURIComponent(file.name)},body:file});
      const data=await response.json();if(!response.ok)throw new Error(data.error);
      const oldCount=pid&&project?project.pages.length:0;project=data;pid=data.id;firstNew??=data.pages[oldCount]?.id;
    }
    await refreshProjects();await loadProject(pid,firstNew);toast('导入完成。点击「识别当前页」或「识别整个 PPT」开始。');
  }finally{setBusy(false);$('fileInput').value='';}
}
$('fileInput').onchange=safeRun(()=>upload([...$('fileInput').files]));
for(const id of ['importBtn','welcomeImport'])$(id).onclick=()=>{newImport=false;$('fileInput').click();};
$('newBtn').onclick=()=>{newImport=true;$('fileInput').click();};
$('demoBtn').onclick=safeRun(async()=>{if(busy)return;await flush();setBusy(true);try{project=await api('/api/demo',{});await refreshProjects();await loadProject(project.id);toast('已加载测试示例，点击「识别当前页」或「识别整个 PPT」开始。');}finally{setBusy(false);}});
$('projectSelect').onchange=safeRun(async()=>{const id=$('projectSelect').value;if(!id||busy)return;await flush();await loadProject(id);});
$('analyzeBtn').onclick=safeRun(async()=>{const reset=!!page()?.regions.length;if(reset&&!confirm('重新识别将替换本页现有文字区域和手动修改。是否继续？'))return;await runJob('analyze',{reset});});
$('analyzeAllBtn').onclick=()=>{
  if(busy||!project)return;
  const pages=project.pages, remaining=pages.filter(p=>p.pending_rescan||!(p.status==='review'||p.regions.length)).length;
  $('batchDialogSummary').textContent=`共 ${pages.length} 页，${remaining} 页未完成。请选择处理方式。`;
  $('resumeBatchBtn').disabled=remaining===0;
  $('batchDialog').showModal();
};
$('closeBatch').onclick=()=>$('batchDialog').close();
$('rescanAllBtn').onclick=safeRun(async()=>{$('batchDialog').close();await runJob('analyze_all',{reset:true});});
$('resumeBatchBtn').onclick=safeRun(async()=>{$('batchDialog').close();await runJob('analyze_all');});
$('exportAllBtn').onclick=safeRun(()=>runJob('export'));
$('fitBtn').onclick=safeRun(async()=>{const r=region();if(r?.locked)throw new Error('请先取消「锁定样式」。');if(r&&!r.enabled)throw new Error('请先勾选「重绘此区域」。');await runJob('fit',{region_id:selectedId});});
$('fitFontBtn').onclick=safeRun(async()=>{const r=region();if(!r||r.locked||!r.enabled)throw new Error('请启用此区域并取消锁定。');await runJob('fit',{region_id:selectedId,font_ids:[r.font_id]});});
$('previewBtn').onclick=safeRun(()=>{previewAutoShow=true;return updatePreview();});
$('cancelBtn').onclick=safeRun(async()=>{await api('/api/cancel',{});$('jobMessage').textContent='正在取消，请等待当前步骤结束…';});
$('drawBtn').onclick=()=>{drawing=!drawing;editingBox=false;$('editBoxBtn').classList.remove('primary');document.body.classList.toggle('drawing-mode',drawing);$('drawBtn').classList.toggle('primary',drawing);if(drawing){setMode('original');$('canvasHint').textContent='在原图上拖出一个单行文字框，然后输入正确文字。';}};
$('boxesChk').onchange=drawOverlay;$('zoom').onchange=resize;$('sourceImage').onload=resize;
new ResizeObserver(resize).observe($('viewport'));
for(const b of $('viewModes').children)b.onclick=safeRun(async()=>{previewAutoShow=false;if(b.dataset.mode!=='original'&&!previewUrl)await updatePreview();setMode(b.dataset.mode);});
$('compareRange').oninput=compare;
$('deleteRegion').onclick=()=>{if(!region()||busy)return;history();page().regions=page().regions.filter(r=>r.id!==selectedId);selectedId=null;markDirty();renderRegions();renderInspector();};
function undoRedo(reverse=false){
  if(!page()||busy||pointer)return;
  editGroup=null;
  const from=reverse?redo:undo,to=reverse?undo:redo;if(!from.length)return;
  pushHistory(to,historySnapshot());const snapshot=from.pop();
  page().regions=clone(snapshot.regions);
  selectedId=page().regions.some(r=>r.id===snapshot.selectedId)?snapshot.selectedId:null;
  markDirty();renderRegions();renderInspector();setBusy(false);
}
$('undoBtn').onclick=()=>undoRedo();$('redoBtn').onclick=()=>undoRedo(true);
$('exportBtn').onclick=()=>$('exportDialog').showModal();$('closeExport').onclick=()=>$('exportDialog').close();
for(const ext of ['svg','png'])$(ext+'Export').onclick=safeRun(async()=>{$('exportDialog').close();pendingDownload=ext;try{await runJob('render');}catch(e){pendingDownload=null;throw e;}});
$('pptExport').onclick=safeRun(async()=>{$('exportDialog').close();await runJob('export');});
$('jsonExport').onclick=safeRun(async()=>{await flush();download(asset('project.json',true));$('exportDialog').close();});
$('helpBtn').onclick=()=>$('helpDialog').showModal();$('closeHelp').onclick=()=>$('helpDialog').close();
// Handle history synchronously, before the browser's native input undo.
// Search boxes and dialogs retain their ordinary browser editing behavior.
document.addEventListener('focusin',()=>{editGroup=null;});
document.addEventListener('keydown',e=>{
  const command=e.ctrlKey||e.metaKey,key=e.key.toLowerCase();
  if(!command||e.altKey||e.isComposing||!['z','y'].includes(key))return;
  const target=e.target;
  if(target.closest?.('dialog')||(['INPUT','TEXTAREA','SELECT'].includes(target.tagName)&&
     (!target.closest('#properties')||target.id==='fontSearch')))return;
  if(!page())return;
  e.preventDefault();undoRedo(key==='y'||e.shiftKey);
});
document.addEventListener('keydown',safeRun(async e=>{
  if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();await flush();toast('已保存到本机');return;}
  if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();previewAutoShow=true;await updatePreview();return;}
  if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName))return;
  if(e.key==='Escape'){if(pointer?.moved)markDirty();drawing=false;editingBox=false;pointer=null;document.body.classList.remove('drawing-mode');$('drawBtn').classList.remove('primary');$('editBoxBtn').classList.remove('primary');drawOverlay();}
  const directions={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
  if(directions[e.key]&&region()&&!busy&&!region().locked){e.preventDefault();history();const d=directions[e.key],step=e.shiftKey?10:1;region().fit_status='edited';region().score=null;region().x+=d[0]*step;region().y+=d[1]*step;markDirty();renderInspector();drawOverlay();}
}));
window.addEventListener('beforeunload',e=>{if(dirty||saving){e.preventDefault();e.returnValue='';}});
document.addEventListener('dragover',e=>{e.preventDefault();});
document.addEventListener('drop',safeRun(async e=>{e.preventDefault();if(e.dataTransfer.files.length)await upload([...e.dataTransfer.files]);}));
safeRun(async()=>{
  const boot=await refreshProjects();const last=localStorage.getItem('sharpener-project');
  if(last&&boot.projects.some(p=>p.id===last))await loadProject(last);
  const job=await api('/api/job');if(job.active){await loadProject(job.project_id,job.page_id);await watchJob(job.id);}
})();
