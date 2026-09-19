const {test}=require('node:test');
const assert=require('node:assert/strict');
const {resizeText}=require('../src/ai_text_sharpener/web/canvas-geometry.js');
const start={x:80,y:50,ink_width:200,ink_height:40,font_size:40,letter_spacing:2,stroke_width:1};
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-8,`${a} != ${b}`);
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
