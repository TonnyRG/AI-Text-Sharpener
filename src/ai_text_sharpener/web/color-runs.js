(function(root){
  'use strict';
  function apply(region,start,end,color){
    const chars=Array.from(region.text);
    if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||end>chars.length||start>=end||!/^#[0-9a-f]{6}$/i.test(color))throw new Error('请先在文字内容中选中要着色的字。');
    const colors=chars.map(()=>region.color);
    if(region.color_mode==='multi'&&region.color_text===region.text){
      for(const run of region.color_runs||[])for(let i=run.start;i<run.end;i++)colors[i]=run.color;
    }
    colors.fill(color,start,end);
    const runs=[];
    colors.forEach((c,i)=>{if(runs.length&&runs.at(-1).color===c)runs.at(-1).end=i+1;else runs.push({start:i,end:i+1,color:c});});
    return {color_mode:'multi',color_text:region.text,color_runs:runs,color_source:'manual',color_note:'已手动设置片段颜色。'};
  }
  const api={apply};if(typeof module==='object'&&module.exports)module.exports=api;else root.ColorRuns=api;
})(typeof globalThis!=='undefined'?globalThis:this);
