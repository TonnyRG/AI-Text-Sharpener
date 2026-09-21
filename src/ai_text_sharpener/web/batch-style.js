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
  const api={targets,common,plan};if(typeof module==='object'&&module.exports)module.exports=api;else root.BatchStyle=api;
})(typeof globalThis!=='undefined'?globalThis:this);
