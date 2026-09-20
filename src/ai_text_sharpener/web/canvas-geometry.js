'use strict';
// Pure geometry shared by canvas manipulation and regression tests.
const CanvasGeometry = {
  roundStyle(value){return Math.sign(value)*Math.floor(Math.abs(value)+.5);},
  corners(r){
    const w=r.ink_width||0,h=r.ink_height||0,a=(r.rotation||0)*Math.PI/180,c=Math.cos(a),s=Math.sin(a);
    return [[-w/2,-h/2],[w/2,-h/2],[w/2,h/2],[-w/2,h/2]].map(([x,y])=>[r.x+w/2+c*x-s*y,r.y+h/2+s*x+c*y]);
  },
  intersects(a,b){
    const aa=CanvasGeometry.corners(a),bb=CanvasGeometry.corners(b);
    for(const box of [aa,bb])for(let i=0;i<2;i++){
      const p=box[i],q=box[i+1],dx=q[0]-p[0],dy=q[1]-p[1],length=Math.hypot(dx,dy);
      if(!length)return false;
      const project=points=>points.map(([x,y])=>(-dy*x+dx*y)/length),one=project(aa),two=project(bb);
      if(Math.min(...one)>=Math.max(...two)-2||Math.min(...two)>=Math.max(...one)-2)return false;
    }
    return true;
  },
  bounds(r){
    const w=r.ink_width||0,h=r.ink_height||0,a=(r.rotation||0)*Math.PI/180;
    const width=Math.abs(w*Math.cos(a))+Math.abs(h*Math.sin(a)),height=Math.abs(w*Math.sin(a))+Math.abs(h*Math.cos(a));
    return {...r,x:r.x+(w-width)/2,y:r.y+(h-height)/2,ink_width:width,ink_height:height,rotation:0};
  },
  rotationAt(start,from,to,snap=false){
    const cx=start.x+start.ink_width/2,cy=start.y+start.ink_height/2;
    const delta=(Math.atan2(to.y-cy,to.x-cx)-Math.atan2(from.y-cy,from.x-cx))*180/Math.PI;
    const angle=(start.rotation||0)+delta,step=snap?15:1;
    return ((CanvasGeometry.roundStyle(angle/step)*step+180)%360+360)%360-180;
  },
  // Coordinates are image pixels; tolerance stays constant in screen pixels at any zoom.
  // Return only position and transient guides: moving must not alter glyphs or erase bounds.
  snapMove(start, x, y, page, {scale=1, threshold=6, enabled=true, regions=[]}={}) {
    if(start.rotation||regions.some(r=>r.rotation)){
      const bounds=CanvasGeometry.bounds({...start,x,y});
      const snapped=CanvasGeometry.snapMove(bounds,bounds.x,bounds.y,page,
        {scale,threshold,enabled,regions:regions.map(r=>CanvasGeometry.bounds(r))});
      return {x:x+snapped.x-bounds.x,y:y+snapped.y-bounds.y,guides:snapped.guides};
    }
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
    const angle=(start.rotation||0)*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle);
    [dx,dy]=[c*dx+s*dy,-s*dx+c*dy];
    const west=corner.includes('w'), north=corner.includes('n');
    const desired=((w+(west?-dx:dx))*w+(h+(north?-dy:dy))*h)/(w*w+h*h);
    const limit=Math.min(1000/start.font_size,
      start.stroke_width>0?12/start.stroke_width:Infinity,
      start.letter_spacing?300/Math.abs(start.letter_spacing):Infinity);
    const font_size=Math.max(4,Math.min(Math.floor(limit*start.font_size),CanvasGeometry.roundStyle(start.font_size*desired)));
    const scale=font_size/start.font_size;
    const spacing=Math.max(-300,Math.min(300,CanvasGeometry.roundStyle((start.letter_spacing||0)*scale)));
    const width=Math.max(1,w*scale+(spacing-(start.letter_spacing||0)*scale)*Math.max(0,Array.from(start.text||'').length-1));
    const height=h*scale,ax=(west?1:-1)*(w-width)/2,ay=(north?1:-1)*(h-height)/2;
    return {x:start.x+(w-width)/2+c*ax-s*ay,y:start.y+(h-height)/2+s*ax+c*ay,
      ink_width:width, ink_height:height, font_size,
      letter_spacing:spacing,
      stroke_width:Math.min(12,(start.stroke_width||0)*scale)};
  }
};
if(typeof module!=='undefined')module.exports=CanvasGeometry;
