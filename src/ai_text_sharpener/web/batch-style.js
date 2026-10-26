/* Shared batch-style rules: only the explicitly edited property is changed. */
(function(root){
  'use strict';
  const defaults={font_id:'',font_size:48,letter_spacing:0,stroke_width:0,color:'#182029'};
  const limits={font_size:[4,1000],letter_spacing:[-300,300],stroke_width:[0,12]};
  function targets(regions,key){
    return regions.filter(r=>r.enabled&&!r.locked&&(!['font_id','letter_spacing'].includes(key)||r.kind!=='formula'));
  }
  function common(regions,key){
    const items=targets(regions,key),values=items.map(r=>key==='color'&&r.color_mode==='multi'?null:(r[key]??defaults[key]));
    return {count:items.length,mixed:values.some(v=>v===null||v!==values[0]),value:values[0]??null};
  }
  function plan(regions,key,value,font){
    if(!(key in defaults))throw new Error('不支持批量修改此属性。');
    if(key in limits){
      if(value===''||!Number.isFinite(Number(value)))throw new Error('请输入有效数值。');
      value=Number(value);const [min,max]=limits[key];
      if(value<min||value>max)throw new Error(`数值必须在 ${min}–${max} 之间。`);
      if(key!=='stroke_width')value=Math.sign(value)*Math.floor(Math.abs(value)+.5);
    }else if(key==='font_id'){
      if(!font||font.id!==value)throw new Error('请选择本机字体。');
    }else{
      if(!/^#[0-9a-f]{6}$/i.test(value))throw new Error('颜色格式应为 #RRGGBB。');
      value=value.toLowerCase();
    }
    const changes=[];
    for(const r of targets(regions,key)){
      if((r[key]??defaults[key])===value&&!(key==='color'&&r.color_mode==='multi'))continue;
      const patch={[key]:value,score:null,fit_status:'edited',alternatives:[],reviewed_signature:null};
      if(key==='font_id')patch.font_label=font.label;
      if(key==='color')Object.assign(patch,{color_mode:'single',color_source:'manual',color_runs:[],color_text:'',color_note:'已批量统一颜色。'});
      changes.push({id:r.id,patch});
    }
    return {changes,value};
  }
  function referenceable(r){
    return !!r&&r.enabled&&r.kind!=='formula'&&!!r.text?.trim()&&!!r.font_id&&
      Number.isFinite(r.font_size)&&r.font_size>=4&&r.font_size<=1000;
  }
  function similar(regions,reference){
    if(!referenceable(reference))return [];
    const tolerance=Math.max(1,Math.min(2,reference.font_size*.06));
    const angle=r=>((r.rotation||0)+360)%360;
    return [reference.id,...regions.filter(r=>{
      if(r.id===reference.id||!referenceable(r)||r.locked)return false;
      const delta=Math.abs(angle(r)-angle(reference));
      if(Math.min(delta,360-delta)>2||Math.abs(r.font_size-reference.font_size)>tolerance)return false;
      // Horizontal source boxes help separate small caps/captions from full
      // body text of a coincidentally similar fitted size. Selection is only a
      // suggestion; it never changes text or claims to infer semantic levels.
      if(Math.abs(r.source_rotation||0)<.5&&Math.abs(reference.source_rotation||0)<.5&&
          r.bbox?.[3]>0&&reference.bbox?.[3]>0&&
          Math.abs(r.bbox[3]-reference.bbox[3])>Math.max(4,reference.bbox[3]*.18))return false;
      return true;
    }).map(r=>r.id)];
  }
  function fromReference(regions,reference,font){
    if(!referenceable(reference))throw new Error('请选择一处已启用的普通文字作为参考。');
    const items=regions.filter(r=>r.id!==reference.id&&referenceable(r)),changes=new Map();
    for(const [key,value] of [['font_id',reference.font_id],['font_size',reference.font_size],['stroke_width',reference.stroke_width||0]]){
      for(const change of plan(items,key,value,font).changes){
        if(!changes.has(change.id))changes.set(change.id,{id:change.id,patch:{}});
        Object.assign(changes.get(change.id).patch,change.patch,{alignment_adjustment:null,size_normalization:null});
      }
    }
    return {changes:[...changes.values()]};
  }
  const api={targets,common,plan,referenceable,similar,fromReference};if(typeof module==='object'&&module.exports)module.exports=api;else root.BatchStyle=api;
})(typeof globalThis!=='undefined'?globalThis:this);
