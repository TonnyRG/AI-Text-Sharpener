const {test}=require('node:test');
const assert=require('node:assert/strict');
const CanvasGeometry=require('../src/ai_text_sharpener/web/canvas-geometry.js');
const {resizeText,snapMove}=require('../src/ai_text_sharpener/web/canvas-geometry.js');
const start={x:80,y:50,ink_width:200,ink_height:40,font_size:40,letter_spacing:2,stroke_width:1};
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-8,`${a} != ${b}`);
const alignItems=()=>[
  {id:'a',enabled:true,text:'a',x:30,y:20,ink_width:60,ink_height:20},
  {id:'b',enabled:true,text:'b',x:170,y:90,ink_width:40,ink_height:30},
  {id:'c',enabled:true,kind:'formula',latex:'x^2',x:310,y:200,ink_width:90,ink_height:40},
];
for(const [mode,axis,factor] of [['left','x',0],['centerX','x',.5],['right','x',1],['top','y',0],['centerY','y',.5],['bottom','y',1]])test(`multi-selection ${mode} uses visible rotated bounds`,()=>{
  const rs=alignItems();rs[1].rotation=30;const before=structuredClone(rs);
  const patches=CanvasGeometry.alignSelection(rs,mode);assert.deepEqual(rs,before);
  const result=rs.map(r=>({...r,...patches.find(p=>p.id===r.id)}));
  const coords=result.map(r=>{const b=CanvasGeometry.bounds(r);return b[axis]+b[axis==='x'?'ink_width':'ink_height']*factor;});
  coords.forEach(v=>close(v,coords[0]));
  patches.forEach(p=>assert.deepEqual(Object.keys(p).sort(),['id','x','y']));
});
for(const [mode,axis] of [['distributeX','x'],['distributeY','y']])test(`${mode} makes equal edge gaps while keeping end objects fixed`,()=>{
  const rs=alignItems(),before=structuredClone(rs),patches=CanvasGeometry.alignSelection(rs,mode);
  const result=rs.map(r=>({...r,...patches.find(p=>p.id===r.id)}));
  const length=axis==='x'?'ink_width':'ink_height';
  close(result[1][axis]-result[0][axis]-result[0][length],result[2][axis]-result[1][axis]-result[1][length]);
  assert.deepEqual(result[0],before[0]);assert.deepEqual(result[2],before[2]);
});
test('alignment excludes locked, preserved and missing geometry and is a no-op when already aligned',()=>{
  const rs=alignItems();rs.push({...rs[0],id:'locked',locked:true,x:-500},{...rs[0],id:'off',enabled:false,x:-500},{...rs[0],id:'invalid',ink_width:NaN});
  const patches=CanvasGeometry.alignSelection(rs,'left');assert.deepEqual(patches.map(p=>p.id),['b','c']);
  patches.forEach(p=>Object.assign(rs.find(r=>r.id===p.id),p));assert.deepEqual(CanvasGeometry.alignSelection(rs,'left'),[]);
  assert.deepEqual(CanvasGeometry.alignSelection(rs.slice(0,2),'distributeY'),[]);
});
test('distribution does not introduce overlap when outer objects have insufficient space',()=>{
  const rs=alignItems();rs[1].x=40;rs[2].x=50;assert.throws(()=>CanvasGeometry.alignSelection(rs,'distributeX'),/空间不足/);
});
for(const corner of ['nw','ne','se','sw'])test(`${corner}: scale glyphs and keep opposite corner fixed`,()=>{
  const west=corner.includes('w'),north=corner.includes('n');
  const resized=resizeText(start,corner,west?-100:100,north?-20:20);
  close(resized.ink_width,300);close(resized.ink_height,60);
  close(resized.x+(west?300:0),start.x+(west?200:0));
  close(resized.y+(north?60:0),start.y+(north?40:0));
  close(resized.font_size,60);close(resized.letter_spacing,3);close(resized.stroke_width,1.5);
  assert.equal(start.font_size,40); // Do not accumulate changes into the drag snapshot.
});
test('crossing the fixed corner cannot flip or collapse text',()=>{
  const resized=resizeText(start,'nw',2000,2000);
  close(resized.font_size,4);close(resized.ink_width/resized.ink_height,5);
  close(resized.x+resized.ink_width,280);close(resized.y+resized.ink_height,90);
});
test('extreme drags respect font, stroke and spacing constraints',()=>{
  for(const overrides of [{stroke_width:0,letter_spacing:0},{stroke_width:11},{letter_spacing:-299}]){
    const r=resizeText({...start,...overrides},'se',1e8,1e8);
    assert.ok(r.font_size>=4&&r.font_size<=1000);
    assert.ok(r.stroke_width>=0&&r.stroke_width<=12);
    assert.ok(Math.abs(r.letter_spacing)<=300);
    close(r.ink_width/r.ink_height,5);
  }
});
test('a sideways drag still scales both axes, including formulas',()=>{
  const r=resizeText({...start,letter_spacing:0,stroke_width:0},'se',50,0);
  close(r.ink_width/start.ink_width,r.ink_height/start.ink_height);
  close(r.font_size/start.font_size,r.ink_height/start.ink_height);
});

const slide={width:960,height:540};
const moving={...start,id:'moving',text:'Title',enabled:true,bbox:[80,50,200,40]};
const target={...moving,id:'target',x:610,y:340,ink_width:100,ink_height:30};
test('page center snaps both axes exactly and draws full-page guides',()=>{
  const before=structuredClone(moving),r=snapMove(moving,384,253,slide);
  assert.deepEqual(r,{x:380,y:250,guides:[
    {axis:'x',position:480,from:0,to:540},{axis:'y',position:270,from:0,to:960}]});
  assert.deepEqual(moving,before);
});
test('page edges snap without changing dimensions or source erase bounds',()=>{
  const r=snapMove(moving,4,497,slide);
  assert.equal(r.x,0);assert.equal(r.y,500);
  assert.deepEqual(Object.keys(r).sort(),['guides','x','y']);
});
test('other text edges and centers align, with guides spanning both frames',()=>{
  const options={regions:[target]};
  const edge=snapMove(moving,414,342,slide,options);
  assert.equal(edge.x,410);assert.equal(edge.y,340);
  assert.deepEqual(edge.guides,[{axis:'x',position:610,from:340,to:380},{axis:'y',position:340,from:410,to:710}]);
  const center=snapMove(moving,562,337,slide,options);
  assert.equal(center.x,560);assert.equal(center.y,335);
});
test('six screen pixels remain the threshold at fit, 100% and 200% zoom',()=>{
  for(const scale of [.2,1,2]){
    assert.equal(snapMove(moving,380+5.9/scale,100,slide,{scale}).x,380);
    assert.equal(snapMove(moving,380+6.1/scale,100,slide,{scale}).guides.length,0);
  }
});
test('free movement and modifier bypass have no guides',()=>{
  assert.deepEqual(snapMove(moving,213,117,slide),{x:213,y:117,guides:[]});
  assert.deepEqual(snapMove(moving,384,253,slide,{enabled:false}),{x:384,y:253,guides:[]});
});
test('self, disabled, empty and invalid text are not snap targets; locked text is',()=>{
  const options={regions:[{...target,id:moving.id},{...target,enabled:false},{...target,text:' '},{...target,ink_width:NaN}]};
  assert.deepEqual(snapMove(moving,414,342,slide,options),{x:414,y:342,guides:[]});
  assert.equal(snapMove(moving,414,342,slide,{regions:[{...target,locked:true}]}).x,410);
});
test('nearest target wins; page center wins an exact tie',()=>{
  const competing={...target,x:588};
  assert.equal(snapMove(moving,384,100,slide,{regions:[competing]}).x,380);
  assert.equal(snapMove(moving,385,100,slide,{regions:[competing]}).x,388);
});
test('page center guides align centers rather than snapping a text edge to the midpoint',()=>{
  assert.equal(snapMove(moving,479,100,slide).guides.length,0);
});

test('rotated resize keeps the opposite corner fixed in page coordinates',()=>{
  for(const rotation of [27,-40,90])for(const corner of ['nw','ne','se','sw']){
    const r={...start,rotation},a=rotation*Math.PI/180,c=Math.cos(a),s=Math.sin(a);
    const west=corner.includes('w'),north=corner.includes('n');
    const anchor=v=>({x:v.x+v.ink_width/2+c*(west?1:-1)*v.ink_width/2-s*(north?1:-1)*v.ink_height/2,
      y:v.y+v.ink_height/2+s*(west?1:-1)*v.ink_width/2+c*(north?1:-1)*v.ink_height/2});
    const old=anchor(r),resized=resizeText(r,corner,51,23),next=anchor(resized);
    close(old.x,next.x);close(old.y,next.y);
    assert.equal(resized.font_size,Math.round(resized.font_size));
    assert.equal(resized.letter_spacing,Math.round(resized.letter_spacing));
  }
});
test('rotation gesture uses the center and supports 15-degree steps across the seam',()=>{
  const {rotationAt}=require('../src/ai_text_sharpener/web/canvas-geometry.js');
  const r={x:0,y:0,ink_width:200,ink_height:40,rotation:0};
  assert.equal(rotationAt(r,{x:100,y:-20},{x:140,y:20}),90);
  const a=-70*Math.PI/180;
  assert.equal(rotationAt(r,{x:100,y:-20},{x:100+40*Math.cos(a),y:20+40*Math.sin(a)},true),15);
  assert.equal(rotationAt({...r,rotation:170},{x:100,y:-20},{x:140,y:20}),-100);
});
const turn=(angle,options={},region=moving)=>{
  const cx=region.x+region.ink_width/2,cy=region.y+region.ink_height/2;
  const a=(angle-(region.rotation||0))*Math.PI/180;
  return CanvasGeometry.snapRotation(region,{x:cx+100,y:cy},{x:cx+100*Math.cos(a),y:cy+100*Math.sin(a)},options);
};
test('rotation magnet catches standard angles from both sides and releases outside tolerance',()=>{
  for(const angle of [-135,-90,-45,0,45,90,135])for(const offset of [-2.9,2.9]){
    assert.deepEqual(turn(angle+offset),{rotation:angle,snapped:true});
    assert.equal(turn(angle+Math.sign(offset)*3.1).snapped,false);
  }
  assert.deepEqual(turn(178),{rotation:-180,snapped:true});
  assert.deepEqual(turn(-178),{rotation:-180,snapped:true});
});
test('rotation magnet matches the nearest text or formula angle including locked targets',()=>{
  assert.deepEqual(turn(27,{regions:[{...target,rotation:26,locked:true},{...target,id:'second',rotation:29}]}),{rotation:26,snapped:true});
  assert.deepEqual(turn(27,{regions:[{...target,text:'',latex:'x^2',rotation:28}]}),{rotation:28,snapped:true});
  assert.deepEqual(turn(179,{regions:[{...target,rotation:179.5}]}),{rotation:179.5,snapped:true});
});
test('self, preserved and empty regions do not attract rotation',()=>{
  assert.deepEqual(turn(27,{regions:[{...moving,rotation:27},{...target,rotation:27,enabled:false},{...target,rotation:27,text:''}]}),{rotation:27,snapped:false});
});
test('rotation bypass is free, Shift constrains to 15 degrees even with magnets disabled',()=>{
  assert.deepEqual(turn(2,{enabled:false}),{rotation:2,snapped:false});
  assert.deepEqual(turn(23,{enabled:false,step:true}),{rotation:30,snapped:true});
  assert.deepEqual(turn(-23,{step:true}),{rotation:-30,snapped:true});
  assert.deepEqual(turn(23,{regions:[{...target,rotation:23}],step:true}),{rotation:30,snapped:true});
});
test('rotation magnet uses the drag snapshot without changing position, size or erase bounds',()=>{
  const before=structuredClone(moving),r={...moving,rotation:170};
  assert.deepEqual(turn(-89,{},r),{rotation:-90,snapped:true});
  assert.deepEqual(moving,before);
  assert.deepEqual(Object.keys(turn(45)).sort(),['rotation','snapped']);
});
test('a rotated text frame snaps by visible bounds and preserves its center',()=>{
  const r={...moving,rotation:90};
  const result=snapMove(r,384,253,slide);
  close(result.x,380);close(result.y,250);
  assert.equal(result.guides.length,2);
});
test('style rounding uses half away from zero, including negative letter spacing',()=>{
  const {roundStyle}=require('../src/ai_text_sharpener/web/canvas-geometry.js');
  assert.deepEqual([12.49,12.5,-1.5,-1.49].map(roundStyle),[12,13,-2,-1]);
});
test('parallel slanted text is not reported as overlapping merely because envelopes overlap',()=>{
  const {intersects}=require('../src/ai_text_sharpener/web/canvas-geometry.js');
  const a={x:100,y:100,ink_width:300,ink_height:20,rotation:45};
  assert.equal(intersects(a,{...a,x:70,y:130}),false);
  assert.equal(intersects(a,{...a,x:102,y:102}),true);
});

test('marquee contains whole frames in either drag direction and original mode uses OCR boxes',()=>{
  const regions=[{id:'a',x:10,y:10,ink_width:30,ink_height:10,bbox:[200,200,30,10],enabled:true},
    {id:'b',x:80,y:10,ink_width:30,ink_height:10,bbox:[80,10,30,10],enabled:true},
    {id:'off',x:400,y:400,ink_width:30,ink_height:10,bbox:[15,15,10,10],enabled:false}];
  assert.deepEqual(CanvasGeometry.marqueeIds(regions,{x:0,y:0},{x:50,y:40}),['a','off']);
  assert.deepEqual(CanvasGeometry.marqueeIds(regions,{x:50,y:40},{x:0,y:0}),['a','off']);
  assert.deepEqual(CanvasGeometry.marqueeIds(regions,{x:0,y:0},{x:50,y:40},true),['off']);
  assert.deepEqual(CanvasGeometry.marqueeIds(regions,{x:0,y:0},{x:90,y:40}),['a','off']);
});

test('marquee uses the visible rotated corners',()=>{
  const r={id:'r',x:40,y:40,ink_width:80,ink_height:10,rotation:90,bbox:[0,0,10,10],enabled:true};
  assert.deepEqual(CanvasGeometry.marqueeIds([r],{x:70,y:0},{x:90,y:90}),['r']);
  assert.deepEqual(CanvasGeometry.marqueeIds([r],{x:35,y:35},{x:125,y:55}),[]);
});
