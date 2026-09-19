'use strict';
const $ = id => document.getElementById(id);
let token = '', fonts = [], project = null, pageId = null, selectedId = null;
let mode = 'original', dirty = false, busy = false, mutation = 0, saving = null;
let saveTimer, toastTimer, newImport = false, drawing = false, pointer = null;
let undo = [], redo = [];
const pageHistories = new Map();
let historyProjectId = null, editGroup = null;
let previewTimer, previewRunning = false, previewVersion = 0, previewUrl = null, previewAutoShow = false;
let editingBox = false, peeking = false;
let exportNameProject=null, workspaceView='active', workspaceData={projects:[],trash:[]};
let folderState=null, folderRequest=0, exportPending=false;
const liveLayers = new Map();
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
  for (const id of ['analyzeBtn','analyzeAllBtn','exportBtn','previewBtn','peekBtn','drawBtn','importBtn','newBtn','manageWorkspacesBtn','projectSelect','demoBtn','fitBtn','fitFontBtn','recognizeFormulaBtn','fitFormulaBtn','confirmExport','jsonExport']) {
    $(id).disabled = value || (['analyzeBtn','analyzeAllBtn','exportBtn','previewBtn','peekBtn','drawBtn'].includes(id) && !page());
  }
  for(const button of $('workspaceList').querySelectorAll('button'))button.disabled=value;
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
function markDirty(geometryReady=false) {
  if(!geometryReady)liveLayers.clear();
  dirty = true; mutation++; $('saveState').textContent = '· 尚未保存';
  page().render_revision=-1;
  $('canvasHint').textContent = '预览待更新…';
  queuePreview();
  clearTimeout(saveTimer); saveTimer = setTimeout(() => flush().catch(e => toast(e.message, true)), 650);
}
function resetPreview() {
  clearTimeout(previewTimer); previewVersion++; previewAutoShow = false;
  if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl=null;
  editingBox=false;pointer=null;peeking=false;liveLayers.clear();$('liveResult').replaceChildren();$('liveResult').hidden=true;updateBoxButton();
}
function queuePreview() {
  previewVersion++; previewAutoShow=true; clearTimeout(previewTimer);
  previewTimer=setTimeout(()=>updatePreview().catch(e=>toast(e.message,true)),450);
}
async function updatePreview() {
  if(!page()||busy||pointer)return;
  if(previewRunning)return; // The active request will request the newest snapshot.
  clearTimeout(previewTimer);
  const version=previewVersion, pid=project.id, selectedPage=pageId;
  previewRunning=true;$('canvasHint').textContent='正在更新预览…';
  try {
    const result=await api('/api/preview',{project_id:pid,page_id:selectedPage,regions:clone(page().regions)});
    if(version!==previewVersion||project?.id!==pid||pageId!==selectedPage||busy||pointer)return;
    const old=previewUrl;previewUrl=URL.createObjectURL(new Blob([result.svg],{type:'image/svg+xml'}));
    $('resultImage').src=previewUrl;if(old)URL.revokeObjectURL(old);
    for(const geometry of result.regions){const r=page().regions.find(r=>r.id===geometry.id);if(r)Object.assign(r,geometry);}
    installLiveResult(result.svg);
    if(previewAutoShow&&mode==='original'&&!drawing)setMode('result');else setMode(mode);
    drawOverlay();updateCanvasHint();
  } catch(e) {
    if(version===previewVersion){$('canvasHint').textContent='预览未更新：'+e.message;throw e;}
  } finally {
    previewRunning=false;
    if(version!==previewVersion&&page()&&!busy&&!pointer) {
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
  if(!$('exportDirectory').value)$('exportDirectory').value=boot.export_directory||'';
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
  mode=page()?.render_revision>=0?'result':'original';previewAutoShow=!!page()?.regions.length;
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
  $('batchSummary').textContent=allPages.length?`${processed} / ${allPages.length} 页已处理`:'导入后可批量处理全部页面';
  $('pages').replaceChildren();
  for (const item of project?.pages || []) {
    const button = document.createElement('button'); button.className = `page-card ${item.id === pageId ? 'selected' : ''}`;
    const img = document.createElement('img'); img.src = asset(`${item.id}.png`); img.alt = item.name;
    const label = document.createElement('span'); label.textContent = `${item.name} · ${item.status==='error'?'处理失败':item.pending_rescan?'待重新识别':item.status==='review'||item.regions.length?'已处理':'未处理'}`;
    if(item.error)button.title=item.error;
    button.append(img, label); button.onclick = safeRun(async () => {
      if (busy) return; await flush(); resetPreview();pageId = item.id; selectedId = null; bindHistory();mode=page()?.render_revision>=0?'result':'original';previewAutoShow=!!page()?.regions.length;renderProject();
    }); $('pages').append(button);
  }
  if (p) {
    $('sourceImage').src = asset(`${p.id}.png`);
    const hasResult = p.render_revision >= 0;
    if (hasResult) $('resultImage').src = asset(`${p.id}-result.svg`);
    else { $('resultImage').removeAttribute('src'); mode = 'original'; }
    $('overlay').setAttribute('viewBox', `0 0 ${p.width} ${p.height}`);
    $('sheet').style.aspectRatio = `${p.width}/${p.height}`;
    $('canvasHint').textContent = p.regions.length ? '选中绿色框：拖动框内移动，拖动四角缩放；按住看原图可对照。' : '在「识别」栏选择「当前页」或「全部页面」，或手动画框添加文字。';
  }
  renderRegions(); renderInspector(); setMode(mode); setBusy(busy);
  requestAnimationFrame(()=>{resize();if(page()?.regions.length)updatePreview().catch(e=>toast(e.message,true));});
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
function select(id) { if(selectedId!==id)editGroup=null;selectedId=id;renderRegions();renderInspector();updateCanvasHint(); }
function fontOptions() {
  const filter=$('fontSearch').value.toLowerCase(), selected=region()?.font_id;
  $('fontField').replaceChildren();
  for(const f of fonts) if(f.id===selected||f.label.toLowerCase().includes(filter)) $('fontField').add(new Option(f.label,f.id));
  $('fontField').value=selected||'';
}
function renderGeometryFields(r) {
  const rounded=v=>Math.round(v*1000)/1000;
  for(const [id,key] of [['sizeField','font_size'],['spacingField','letter_spacing'],['strokeField','stroke_width'],['xField','x'],['yField','y']])
    $(id).value=rounded(r[key]||0);
}
function renderInspector() {
  const r=region(); $('noSelection').hidden=!!r; $('properties').hidden=!r;
  if(!r)return;
  const math=r.kind==='formula';$('kindField').value=math?'formula':'text';$('formulaPanel').hidden=!math;$('plainTextLabel').hidden=math;
  $('latexField').value=r.latex||'';
  for(const id of ['fontControls','fontMatchActions'])$(id).hidden=math;
  $('spacingField').closest('label').hidden=math;
  $('regionName').textContent=`区域 ${page().regions.indexOf(r)+1}`;
  renderFitStatus(r);
  $('textField').value=r.text; $('originalText').textContent=math?'完整公式区域 · LaTeX 可编辑':`原识别：${r.original_text||'手动添加'}`;
  $('enabledField').checked=r.enabled; $('lockedField').checked=!!r.locked;
  renderGeometryFields(r);$('colorField').value=r.color;
  renderBoxFields();
  $('colorValue').textContent=r.color.toUpperCase(); $('eraseField').value=r.erase_mode||'gradient';
  $('scoreText').textContent=r.score==null?'':`相似度 ${(r.score*100).toFixed(1)}`;
  $('fitNote').textContent=r.fit_note||'可尝试不同字体候选，再对照原图微调。';
  fontOptions(); $('alternatives').replaceChildren();
  $('alternativesPanel').hidden=math||!r.alternatives?.length;
  for(const c of r.alternatives||[]) {
    const btn=document.createElement('button');btn.className='alternative';
    const label=document.createElement('span'); label.textContent=c.font_label;
    const value=document.createElement('small');value.textContent=(c.score*100).toFixed(1);btn.append(label,value);
    btn.onclick=safeRun(async()=>{if(busy)return;history();Object.assign(r,c);markDirty();renderInspector();drawOverlay();});
    $('alternatives').append(btn);
  }
}
function renderFitStatus(r) {
  $('fitBadge').textContent=!r.enabled?'保留原图':r.locked?'已锁定':r.fit_status==='edited'?'已手动调整':r.kind==='formula'?'公式待复核':r.score==null?'待匹配':r.score<.65?'建议复核':'已匹配';
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
    if(['text','latex','font_id','font_size','letter_spacing','stroke_width','x','y'].includes(key)){r.score=null;r.fit_status='edited';r.alternatives=[];$('alternatives').replaceChildren();$('alternativesPanel').hidden=true;}
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
  if(r.kind==='formula'){r.latex=r.latex||'';r.enabled=false;r.fit_note='在高级选项中调整原字范围以包含完整公式，再点击「重新识别公式」。';}
  else {r.font_id=r.font_id||fonts[0]?.id;r.text=r.text||r.original_text||'';}
  r.fit_status='edited';markDirty();renderInspector();renderRegions();
};
$('recognizeFormulaBtn').onclick=safeRun(async()=>{if(region()?.locked)throw new Error('请先取消锁定。');await runJob('formula_recognize',{region_id:selectedId});});
$('fitFormulaBtn').onclick=safeRun(async()=>{if(region()?.locked)throw new Error('请先取消锁定。');await runJob('formula_fit',{region_id:selectedId});});

const boxFields=['boxXField','boxYField','boxWField','boxHField'];
function renderBoxFields(){const r=region();if(r)boxFields.forEach((id,i)=>$(id).value=Math.round(r.bbox[i]*100)/100);}
function updateBox(bbox){
  const r=region();r.bbox=bbox;r.score=null;r.fit_status='edited';r.alternatives=[];
  $('alternatives').replaceChildren();$('alternativesPanel').hidden=true;renderFitStatus(r);renderBoxFields();
}
boxFields.forEach((id,index)=>$(id).addEventListener('input',()=>{
  if(!region()||busy||$(id).value===''||!$(id).checkValidity())return;
  const box=region().bbox.slice();box[index]=Number($(id).value);
  if(box[0]<0||box[1]<0||box[2]<3||box[3]<3||box[0]+box[2]>page().width||box[1]+box[3]>page().height)return;
  history(id);updateBox(box);markDirty();drawOverlay();
}));
function updateBoxButton() {
  $('editBoxBtn').classList.toggle('primary',editingBox);
  $('editBoxBtn').setAttribute('aria-pressed',String(editingBox));
  $('editBoxBtn').textContent=editingBox?'完成擦除范围调整':'调整原字擦除范围';
}
$('sourceSection').addEventListener('toggle',()=>{
  if(!$('sourceSection').open&&editingBox){editingBox=false;updateBoxButton();drawOverlay();}
});
$('editBoxBtn').onclick=()=>{editingBox=!editingBox;drawing=false;$('drawBtn').classList.remove('primary');document.body.classList.remove('drawing-mode');updateBoxButton();$('boxesChk').checked=true;drawOverlay();updateCanvasHint();};

function updateCanvasHint() {
  $('canvasHint').textContent=peeking?'正在查看原图 · 松开按钮返回':editingBox?'橙色框只修改原字擦除范围；绿色框用于移动和缩放重绘文字。':
    mode==='original'?'正在查看原图 · 切换「重绘」后可拖动文字框编辑。':
    region()?.locked?'此区域已锁定 · 取消「锁定样式」后可拖动。':
    region()&&!region().enabled?'此区域保留原图 · 开启「重绘此区域」后可编辑。':
    '选中绿色框：拖动框内移动，拖动四角缩放；按住看原图可对照。';
}
function installLiveResult(svg) {
  const root=new DOMParser().parseFromString(svg,'image/svg+xml').documentElement;
  if(root.localName!=='svg')throw new Error('预览格式无效');
  const imported=document.importNode(root,true);
  $('liveResult').replaceChildren(imported);liveLayers.clear();
  for(const node of imported.querySelectorAll('[data-region-id]')){
    const r=page().regions.find(r=>r.id===node.dataset.regionId);
    if(r)liveLayers.set(r.id,{node,width:r.ink_width,height:r.ink_height});
  }
}
function transformLiveRegion(r) {
  const layer=liveLayers.get(r.id);if(!layer)return;
  layer.node.setAttribute('transform',`translate(${r.x} ${r.y}) scale(${r.ink_width/layer.width} ${r.ink_height/layer.height})`);
}
function showCanvasLayers() {
  const original=mode==='original'||peeking;
  $('sourceImage').hidden=false;
  $('liveResult').hidden=original||!$('liveResult').firstChild;
  $('resultImage').hidden=original||!!$('liveResult').firstChild;
  $('overlay').hidden=peeking;
  $('compareLine').hidden=peeking||mode!=='compare';
  $('compareControl').hidden=mode!=='compare';
  $('peekBtn').classList.toggle('active',peeking);
  $('peekBtn').textContent=peeking?'松开返回重绘':'按住看原图';
  compare();
}
function peekOriginal(value) {
  if(!page()||pointer)return;
  peeking=value;showCanvasLayers();updateCanvasHint();
}
$('peekBtn').addEventListener('pointerdown',evt=>{
  if(evt.button!==0)return;evt.preventDefault();$('peekBtn').setPointerCapture(evt.pointerId);peekOriginal(true);
});
for(const event of ['pointerup','pointercancel','lostpointercapture'])$('peekBtn').addEventListener(event,()=>peekOriginal(false));
$('peekBtn').addEventListener('keydown',evt=>{if([' ','Enter'].includes(evt.key)){evt.preventDefault();peekOriginal(true);}});
$('peekBtn').addEventListener('keyup',evt=>{if([' ','Enter'].includes(evt.key)){evt.preventDefault();peekOriginal(false);}});
$('peekBtn').addEventListener('blur',()=>peekOriginal(false));
window.addEventListener('blur',()=>peekOriginal(false));

function rect(x,y,w,h,classes) {
  const el=document.createElementNS('http://www.w3.org/2000/svg','rect');
  for(const [key,value]of Object.entries({x,y,width:w,height:h,class:classes}))el.setAttribute(key,value);
  return el;
}
function drawOverlay() {
  const overlay=$('overlay');overlay.replaceChildren();
  if(!$('boxesChk').checked&&!drawing)return;
  const size=10*(page()?.width||1)/Math.max(1,$('sheet').getBoundingClientRect().width);
  function handles(r,x,y,w,h,source=false){
    const points=source?[['nw',0,0],['n',.5,0],['ne',1,0],['e',1,.5],['se',1,1],['s',.5,1],['sw',0,1],['w',0,.5]]:
      [['nw',0,0],['ne',1,0],['se',1,1],['sw',0,1]];
    for(const [handle,fx,fy] of points){
      const dot=rect(x+w*fx-size/2,y+h*fy-size/2,size,size,source?'box-handle':'text-handle');
      dot.dataset.id=r.id;dot.dataset.handle=handle;dot.dataset.target=source?'source':'text';
      dot.style.cursor=handle+'-resize';overlay.append(dot);
    }
  }
  for(const r of page()?.regions||[]) {
    const [bx,by,bw,bh]=r.bbox,original=mode==='original'||!r.enabled;
    const box=rect(original?bx:r.x,original?by:r.y,original?bw:(r.ink_width||bw),original?bh:(r.ink_height||bh),
      `${r.id===selectedId?'selected':''} ${!r.enabled?'off':''} ${mode==='original'||r.locked?'read-only':''}`);
    box.dataset.id=r.id;overlay.append(box);
  }
  const r=region();
  if(editingBox&&r){
    const [x,y,w,h]=r.bbox,box=rect(x,y,w,h,'erase editable');box.dataset.id=r.id;box.dataset.handle='move';box.dataset.target='source';overlay.append(box);
    handles(r,x,y,w,h,true);
  }else if(r?.enabled&&!r.locked&&mode!=='original'&&liveLayers.has(r.id)&&r.ink_width>0&&r.ink_height>0){
    // Put the selected frame above overlapping regions, as in a slide editor.
    const box=rect(r.x,r.y,r.ink_width,r.ink_height,'selected');box.dataset.id=r.id;overlay.append(box);
    handles(r,r.x,r.y,r.ink_width,r.ink_height);
  }
  if(pointer?.type==='draw')overlay.append(rect(Math.min(pointer.sx,pointer.ex),Math.min(pointer.sy,pointer.ey),Math.abs(pointer.ex-pointer.sx),Math.abs(pointer.ey-pointer.sy),'drawing'));
}

function resize() {
  const p=page();if(!p)return;
  const viewport=$('viewport'), zoom=$('zoom').value;
  const scale=zoom==='fit'?Math.max(.05,Math.min((viewport.clientWidth-60)/p.width,(viewport.clientHeight-60)/p.height)):Number(zoom);
  $('sheet').style.width=`${p.width*scale}px`;$('sheet').style.height=`${p.height*scale}px`;drawOverlay();
}
function setMode(next) {
  const p=page();
  if(next!=='original'&&(!p||(p.render_revision<0&&!previewUrl))){next='original';}
  mode=next;
  for(const b of $('viewModes').children)b.classList.toggle('active',b.dataset.mode===mode);
  showCanvasLayers();drawOverlay();updateCanvasHint();
}
function compare() {
  const value=Number($('compareRange').value);
  for(const id of ['resultImage','liveResult'])$(id).style.clipPath=mode==='compare'?`inset(0 0 0 ${value}%)`:'';
  $('compareLine').style.left=`${value}%`;
}
function position(evt) {const b=$('sheet').getBoundingClientRect();const p=page();return{x:(evt.clientX-b.left)*p.width/b.width,y:(evt.clientY-b.top)*p.height/b.height};}
$('overlay').addEventListener('pointerdown',evt=>{
  if(busy||!page()||evt.button!==0||peeking)return;const pos=position(evt);
  if(drawing)pointer={type:'draw',sx:pos.x,sy:pos.y,ex:pos.x,ey:pos.y};
  else if(evt.target.dataset.id){
    const {handle,target}=evt.target.dataset;select(evt.target.dataset.id);const r=region();
    if(target==='source')pointer={type:'box',handle,sx:pos.x,sy:pos.y,bbox:r.bbox.slice(),moved:false};
    else if(r.enabled&&!r.locked&&mode!=='original'){
      if(!liveLayers.has(r.id)){
        updatePreview().catch(e=>toast(e.message,true));toast('正在准备文字预览，请稍后拖动。');return;
      }
      pointer={type:handle?'text-resize':'move',handle,sx:pos.x,sy:pos.y,x:r.x,y:r.y,start:clone(r),moved:false};
    }
  }
  if(pointer){clearTimeout(previewTimer);previewVersion++;$('overlay').setPointerCapture(evt.pointerId);evt.preventDefault();}
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
    }else{
      const r=region();
      if(pointer.type==='text-resize')Object.assign(r,CanvasGeometry.resizeText(pointer.start,pointer.handle,dx,dy));
      else{r.x=Math.round((pointer.x+dx)*2)/2;r.y=Math.round((pointer.y+dy)*2)/2;}
      r.x=Math.max(-page().width,Math.min(page().width*2,r.x));r.y=Math.max(-page().height,Math.min(page().height*2,r.y));
      r.fit_status='edited';r.score=null;r.alternatives=[];
      transformLiveRegion(r);renderGeometryFields(r);renderFitStatus(r);
      $('alternativesPanel').hidden=true;
    }
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
  }else if(pointer.moved)markDirty(pointer.type==='move'||pointer.type==='text-resize');
  pointer=null;drawOverlay();try{$('overlay').releasePointerCapture(evt.pointerId);}catch{}
  if(!dirty&&page()?.regions.length)updatePreview().catch(e=>toast(e.message,true));
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
      if(job.status==='error')throw new Error(job.message);
      if(job.status==='cancelled'){toast(job.message);return;}
      $('saveState').textContent='· 已保存';
      if(job.download)download(job.download);
      if(job.saved_path){$('savedPath').value=job.saved_path;$('exportDirectory').value=job.saved_path.slice(0,job.saved_path.lastIndexOf('/'))||'/';$('savedDialog').showModal();}
      if(job.kind==='analyze_all')$('batchSummary').textContent=job.message;
      toast(['analyze_all','export'].includes(job.kind)?job.message:job.warnings?.length?job.warnings.slice(0,2).join('；'):'已完成，可切换滑动对比检查效果。');
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
    await refreshProjects();await loadProject(pid,firstNew);toast('导入完成。在「识别」栏选择「当前页」或「全部页面」开始。');
  }finally{setBusy(false);$('fileInput').value='';}
}
$('fileInput').onchange=safeRun(()=>upload([...$('fileInput').files]));
for(const id of ['importBtn','welcomeImport'])$(id).onclick=()=>{newImport=false;$('fileInput').click();};
$('newBtn').onclick=()=>{newImport=true;$('fileInput').click();};
$('demoBtn').onclick=safeRun(async()=>{if(busy)return;await flush();setBusy(true);try{project=await api('/api/demo',{});await refreshProjects();await loadProject(project.id);toast('已加载测试示例，在「识别」栏选择「当前页」或「全部页面」开始。');}finally{setBusy(false);}});
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
$('fitBtn').onclick=safeRun(async()=>{const r=region();if(r?.locked)throw new Error('请先取消「锁定样式」。');if(r&&!r.enabled)throw new Error('请先勾选「重绘此区域」。');await runJob('fit',{region_id:selectedId});});
$('fitFontBtn').onclick=safeRun(async()=>{const r=region();if(!r||r.locked||!r.enabled)throw new Error('请启用此区域并取消锁定。');await runJob('fit',{region_id:selectedId,font_ids:[r.font_id]});});
$('previewBtn').onclick=safeRun(()=>{previewAutoShow=true;return updatePreview();});
$('cancelBtn').onclick=safeRun(async()=>{await api('/api/cancel',{});$('jobMessage').textContent='正在取消，请等待当前步骤结束…';});
$('drawBtn').onclick=()=>{drawing=!drawing;editingBox=false;updateBoxButton();document.body.classList.toggle('drawing-mode',drawing);$('drawBtn').classList.toggle('primary',drawing);if(drawing){setMode('original');$('canvasHint').textContent='在原图上拖出一个单行文字框，然后输入正确文字。';}};
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
function exportOptions() {
  return {scope:document.querySelector('input[name="exportScope"]:checked').value,
          format:document.querySelector('input[name="exportFormat"]:checked').value};
}
function renderExportOptions() {
  if(!page())return;
  const {scope,format}=exportOptions(), count=scope==='all'?project.pages.length:1;
  const packed=scope==='all'&&format!=='pptx';
  const ext=packed?'zip':format;
  if(exportNameProject!==project.id){$('exportFilename').value=Array.from(project.name.replace(/[\/\\\r\n]/g,'_')).slice(0,45).join('')+'-重绘.'+ext;exportNameProject=project.id;}
  else $('exportFilename').value=$('exportFilename').value.replace(/\.(pptx|svg|png|zip|json)$/i,'')+'.'+ext;
  $('exportCurrentLabel').textContent=`第 ${project.pages.indexOf(page())+1} 页`;
  $('exportAllLabel').textContent=`共 ${project.pages.length} 页`;
  $('exportSummary').textContent=packed?`${count} 页 → ${count} 个 ${format.toUpperCase()} 文件，按页码打包为 ZIP。`:
    `${count} 页 → 1 个 ${format.toUpperCase()} 文件。`;
  $('confirmExport').textContent=`导出 ${packed?'ZIP':format.toUpperCase()}`;
}
$('exportBtn').onclick=()=>{if(busy||!page())return;renderExportOptions();$('exportError').hidden=true;$('exportDialog').showModal();};
for(const id of ['closeExport','cancelExport'])$(id).onclick=()=>$('exportDialog').close();
for(const input of document.querySelectorAll('#exportDialog input[type="radio"]'))input.onchange=renderExportOptions;
$('confirmExport').onclick=()=>submitExport();
function exportDestination(json=false) {
  const directory=$('exportDirectory').value.trim(),name=$('exportFilename').value.trim();
  if(!directory||!name)throw new Error('请填写保存文件夹和文件名。');
  const {scope,format}=exportOptions(),ext=json?'json':scope==='all'&&['svg','png'].includes(format)?'zip':format;
  const filename=name.replace(/\.(pptx|svg|png|zip|json)$/i,'')+'.'+ext;
  if(!json)$('exportFilename').value=filename;
  return {directory,filename};
}
async function submitExport(json=false) {
  if(busy||!project||exportPending)return;exportPending=true;$('exportError').hidden=true;
  $('confirmExport').disabled=true;$('jsonExport').disabled=true;
  try{
    const options=json?{format:'json',scope:'all'}:exportOptions();options.destination=exportDestination(json);
    await flush();$('exportDialog').close();await runJob('export',options);
  }catch(e){
    if(!$('exportDialog').open)$('exportDialog').showModal();
    $('exportError').textContent=e.message;$('exportError').hidden=false;
  }finally{exportPending=false;$('confirmExport').disabled=busy;$('jsonExport').disabled=busy;}
}
$('jsonExport').onclick=()=>submitExport(true);
for(const id of ['doneSaved','closeSaved'])$(id).onclick=()=>$('savedDialog').close();
$('savedPath').onclick=()=>$('savedPath').select();

async function loadFolders(path) {
  const request=++folderRequest;
  for(const id of ['folderHome','folderUp','folderGo','chooseFolder'])$(id).disabled=true;
  $('folderList').replaceChildren();$('folderError').hidden=true;
  try{
    const result=await api('/api/folders',{path});if(request!==folderRequest)return false;
    folderState=result;$('folderPath').value=result.path;
    for(const name of result.folders){
      const button=document.createElement('button');button.textContent=name;
      button.onclick=()=>loadFolders(result.path.replace(/\/$/,'')+'/'+name);$('folderList').append(button);
    }
    if(!result.folders.length){const empty=document.createElement('p');empty.className='workspace-empty';empty.textContent='此处没有子文件夹，可直接选择当前文件夹。';$('folderList').append(empty);}
    $('chooseFolder').disabled=false;return true;
  }catch(e){if(request===folderRequest){$('folderError').textContent=e.message;$('folderError').hidden=false;}return false;}
  finally{if(request===folderRequest)for(const id of ['folderHome','folderUp','folderGo'])$(id).disabled=false;}
}
$('browseExportDir').onclick=()=>{$('folderDialog').showModal();loadFolders($('exportDirectory').value);};
for(const id of ['closeFolder','cancelFolder'])$(id).onclick=()=>$('folderDialog').close();
$('folderGo').onclick=()=>loadFolders($('folderPath').value);
$('folderPath').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();loadFolders($('folderPath').value);}};
$('folderHome').onclick=()=>loadFolders(folderState?.home||'~');
$('folderUp').onclick=()=>loadFolders(folderState?.parent||'~');
$('chooseFolder').onclick=async()=>{if(await loadFolders($('folderPath').value)){$('exportDirectory').value=folderState.path;$('folderDialog').close();}};

function clearProject() {
  clearTimeout(saveTimer);resetPreview();dirty=false;project=null;pageId=null;selectedId=null;
  pageHistories.clear();undo=[];redo=[];historyProjectId=null;localStorage.removeItem('sharpener-project');
  $('saveState').textContent='· 准备就绪';renderProject();
}
function renderWorkspaceList() {
  $('workspaceList').replaceChildren();
  for(const tab of $('workspaceTabs').children)tab.classList.toggle('active',tab.dataset.list===workspaceView);
  const items=workspaceView==='trash'?workspaceData.trash:workspaceData.projects;
  if(!items.length){const empty=document.createElement('p');empty.className='workspace-empty';empty.textContent=workspaceView==='trash'?'回收站为空':'没有工作区';$('workspaceList').append(empty);}
  for(const item of items){
    const row=document.createElement('div');row.className='workspace-item';
    const info=document.createElement('div'),name=document.createElement('strong'),meta=document.createElement('small');
    name.textContent=item.name;meta.textContent=`${item.pages} 页${item.id===project?.id?' · 当前打开':''}`;info.append(name,meta);
    const button=document.createElement('button');button.textContent=workspaceView==='trash'?'恢复':'删除';button.className=workspaceView==='trash'?'':'danger';button.disabled=busy;
    button.onclick=safeRun(async()=>{
      if(busy)return;const restoring=workspaceView==='trash';
      if(!restoring&&!confirm(`将工作区「${item.name}」（${item.pages} 页）移入回收站？之后可以恢复。`))return;
      await flush();setBusy(true);previewVersion++;$('workspaceError').hidden=true;
      try{
        await api(restoring?'/api/workspace/restore':'/api/workspace/trash',{id:item.id,revision:item.id===project?.id?project.revision:item.revision});
        if(!restoring&&project?.id===item.id)clearProject();
        const boot=await refreshProjects();
        if(!project&&boot.projects.length)await loadProject(restoring?item.id:boot.projects[0].id);
        workspaceData=await api('/api/workspaces',{});renderWorkspaceList();toast(restoring?'工作区已恢复':'工作区已移入回收站');
      }catch(e){$('workspaceError').textContent=e.message;$('workspaceError').hidden=false;}finally{setBusy(false);if(page()?.regions.length)updatePreview().catch(e=>toast(e.message,true));}
    });
    row.append(info,button);$('workspaceList').append(row);
  }
}
$('manageWorkspacesBtn').onclick=safeRun(async()=>{
  if(busy)return;await flush();$('workspaceError').hidden=true;workspaceData=await api('/api/workspaces',{});renderWorkspaceList();$('workspaceDialog').showModal();
});
$('closeWorkspaces').onclick=()=>$('workspaceDialog').close();
for(const tab of $('workspaceTabs').children)tab.onclick=()=>{workspaceView=tab.dataset.list;renderWorkspaceList();};
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
  if(e.key==='Escape'){peekOriginal(false);if(pointer?.moved)markDirty();drawing=false;editingBox=false;pointer=null;document.body.classList.remove('drawing-mode');$('drawBtn').classList.remove('primary');updateBoxButton();drawOverlay();}
  const directions={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};
  if(directions[e.key]&&region()?.enabled&&!busy&&!region().locked&&mode!=='original'&&!peeking){e.preventDefault();history();const d=directions[e.key],step=e.shiftKey?10:1;region().fit_status='edited';region().score=null;region().x+=d[0]*step;region().y+=d[1]*step;markDirty();renderInspector();drawOverlay();}
}));
window.addEventListener('beforeunload',e=>{if(dirty||saving){e.preventDefault();e.returnValue='';}});
document.addEventListener('dragover',e=>{e.preventDefault();});
document.addEventListener('drop',safeRun(async e=>{e.preventDefault();if(e.dataTransfer.files.length)await upload([...e.dataTransfer.files]);}));
safeRun(async()=>{
  const boot=await refreshProjects();const last=localStorage.getItem('sharpener-project');
  if(last&&boot.projects.some(p=>p.id===last))await loadProject(last);
  const job=await api('/api/job');if(job.active){await loadProject(job.project_id,job.page_id);await watchJob(job.id);}
})();
