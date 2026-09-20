'use strict';
// Pure geometry shared by canvas manipulation and regression tests.
const CanvasGeometry = {
  // Coordinates are image pixels; tolerance stays constant in screen pixels at any zoom.
  // Return only position and transient guides: moving must not alter glyphs or erase bounds.
  snapMove(start, x, y, page, {scale=1, threshold=6, enabled=true, regions=[]}={}) {
    const result={x,y,guides:[]};
    const valid=r=>[r.x,r.y,r.ink_width,r.ink_height].every(Number.isFinite)&&r.ink_width>0&&r.ink_height>0;
    if(!enabled||!valid(start)||!Number.isFinite(scale)||scale<=0)return result;
    const tolerance=Math.max(0,threshold)/scale;
    const others=regions.filter(r=>r.id!==start.id&&r.enabled&&r.text?.trim()&&valid(r));
    for(const axis of ['x','y']){
      const horizontal=axis==='x',length=horizontal?'ink_width':'ink_height';
      const extent=horizontal?page.width:page.height;
      const at=axis==='x'?x:y,size=start[length];
      let best=null;
      const consider=(position,offset,target)=>{
        const delta=position-at-offset,distance=Math.abs(delta);
        // Keep the first equal-distance target: page center takes precedence over text guides.
        if(distance<=tolerance&&(!best||distance<best.distance-1e-8))best={position,delta,distance,target};
      };
      consider(extent/2,size/2,null);
      consider(0,0,null);consider(extent,size,null);
      for(const other of others){
        consider(other[axis]+other[length]/2,size/2,other);
        for(const edge of [0,other[length]])for(const offset of [0,size])consider(other[axis]+edge,offset,other);
      }
      if(best){result[axis]=at+best.delta;result.guides.push({axis,position:best.position,target:best.target});}
    }
    // Calculate guide lengths after both axes have snapped.
    result.guides=result.guides.map(({axis,position,target})=>{
      const cross=axis==='x'?'y':'x',length=axis==='x'?'ink_height':'ink_width';
      return {axis,position,from:target?Math.min(result[cross],target[cross]):0,
        to:target?Math.max(result[cross]+start[length],target[cross]+target[length]):(axis==='x'?page.height:page.width)};
    });
    return result;
  },
  // Resize from the pointer-down snapshot with the opposite corner fixed.
  // Font size, spacing and stroke scale together so preview and export agree.
  resizeText(start, corner, dx, dy) {
    const w=start.ink_width, h=start.ink_height;
    const west=corner.includes('w'), north=corner.includes('n');
    const desired=((w+(west?-dx:dx))*w+(h+(north?-dy:dy))*h)/(w*w+h*h);
    const limit=Math.min(1000/start.font_size,
      start.stroke_width>0?12/start.stroke_width:Infinity,
      start.letter_spacing?300/Math.abs(start.letter_spacing):Infinity);
    const scale=Math.max(4/start.font_size,Math.min(limit,desired));
    return {x:west?start.x+w-w*scale:start.x, y:north?start.y+h-h*scale:start.y,
      ink_width:w*scale, ink_height:h*scale, font_size:Math.max(4,Math.min(1000,start.font_size*scale)),
      letter_spacing:Math.max(-300,Math.min(300,(start.letter_spacing||0)*scale)),
      stroke_width:Math.min(12,(start.stroke_width||0)*scale)};
  }
};
if(typeof module!=='undefined')module.exports=CanvasGeometry;
