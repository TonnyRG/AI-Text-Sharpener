'use strict';
// Resize from an immutable pointer-down snapshot, keeping the opposite corner fixed.
// Font size, spacing and stroke scale together so the preview and export agree.
const CanvasGeometry = {
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
