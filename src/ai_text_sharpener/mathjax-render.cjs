// Local TeX -> path-only SVG. No browser, network, dynamic packages or HTML.
const fs = require('fs');
const root = process.argv[2];
const {mathjax} = require(root + '/js/mathjax.js');
const {TeX} = require(root + '/js/input/tex.js');
const {SVG} = require(root + '/js/output/svg.js');
const {liteAdaptor} = require(root + '/js/adaptors/liteAdaptor.js');
const {RegisterHTMLHandler} = require(root + '/js/handlers/html.js');
require(root + '/js/input/tex/ams/AmsConfiguration.js');
require(root + '/js/input/tex/newcommand/NewcommandConfiguration.js');
const adaptor = liteAdaptor(); RegisterHTMLHandler(adaptor);
const doc = mathjax.document('', {
  InputJax: new TeX({packages: ['base','ams','newcommand'], maxBuffer: 8192, maxMacros: 500}),
  OutputJax: new SVG({fontCache:'none'})
});
try {
  const tex = JSON.parse(fs.readFileSync(0, 'utf8')).latex;
  const output = adaptor.outerHTML(doc.convert(tex, {display:true}));
  if (output.includes('data-mml-node="merror"') || output.includes('<text')) throw Error('公式包含不支持的命令或字符，请校正 LaTeX。');
  process.stdout.write(output.slice(output.indexOf('<svg'), output.lastIndexOf('</svg>') + 6));
} catch (e) {process.stderr.write(e.message); process.exitCode=1;}
