/* Evidence-based review hints, never an OCR correctness probability. */
(function(root){
  'use strict';
  const geometry=typeof CanvasGeometry!=='undefined'?CanvasGeometry:require('./canvas-geometry.js');
  const rect=r=>{const b=geometry.bounds(r);return [b.x,b.y,b.ink_width,b.ink_height];};
  function overlaps(first,second){
    const a=rect(first),b=rect(second);
    const w=Math.min(a[0]+a[2],b[0]+b[2])-Math.max(a[0],b[0]);
    const h=Math.min(a[1]+a[3],b[1]+b[3])-Math.max(a[1],b[1]);
    return w>2&&h>2&&w*h>Math.min(a[2]*a[3],b[2]*b[3])*.025&&geometry.intersects(first,second);
  }
  function reasons(page,r){
    if(r.type_review&&r.fit_status!=='edited'&&!r.type_review_dismissed)return [r.type_review];
    if(!r.enabled||!(r.text?.trim()||r.latex?.trim()))return [];
    const hints=[];
    if(r.kind==='formula'&&r.fit_status!=='edited')hints.push('公式结构需核对');
    if(Number.isFinite(r.score)&&r.score<.65)hints.push('与原图拟合较弱');
    if(Number.isFinite(r.confidence)&&r.confidence<.92&&r.text===r.original_text)hints.push('识别内容不够确定');
    if(r.kind!=='formula'&&Array.from(r.text||'').length>2&&r.font_size>0){
      const ratio=(r.letter_spacing||0)/r.font_size;
      if(ratio>.28||ratio<-.08)hints.push(ratio>0?'字距可能过大':'文字可能过挤');
    }
    if(r.fit_status!=='edited'&&/narrow|condensed|italic|oblique|斜体/i.test(r.font_label||''))hints.push('窄体或斜体需核对');
    const box=rect(r);
    if(box[2]&&box[3]&&(box[0]<0||box[1]<0||box[0]+box[2]>page.width||box[1]+box[3]>page.height))hints.push('文字超出页面');
    if((page.regions||[]).some(other=>other.id!==r.id&&other.enabled&&(other.text?.trim()||other.latex?.trim())&&overlaps(r,other)))hints.push('与其他文字区域相碰');
    return hints;
  }
  function signature(page,r){
    const keys=['text','latex','kind','font_id','font_label','font_size','letter_spacing','stroke_width','color','color_runs','color_text','color_mode','x','y','bbox','enabled','erase_mode','score','confidence'];
    if(r.rotation||r.source_rotation||r.source_quad)keys.push('rotation','source_rotation','source_quad');
    // Derived ink sizes are omitted: preview refreshes must not undo acceptance.
    const others=(page.regions||[]).filter(o=>o.id!==r.id&&o.enabled&&(o.text?.trim()||o.latex?.trim())&&overlaps(r,o))
      .map(o=>[o.id,o.x,o.y,o.font_size,o.text,o.latex,...(o.rotation?[o.rotation]:[])]);
    return JSON.stringify([keys.map(k=>r[k]??null),reasons(page,r),others]);
  }
  function pending(page,r){return reasons(page,r).length>0&&r.reviewed_signature!==signature(page,r);}
  function collect(project){
    return (project?.pages||[]).flatMap((page,pageIndex)=>page.regions.filter(r=>pending(page,r)).map(region=>({page,pageIndex,region,reasons:reasons(page,region)})));
  }
  function preserve(r){r.enabled=false;r.preserve_original=true;r.type_review_dismissed=true;delete r.reviewed_signature;}
  const api={reasons,signature,pending,collect,preserve};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.RegionReview=api;
})(typeof globalThis!=='undefined'?globalThis:this);
