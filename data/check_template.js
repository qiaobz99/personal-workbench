const fs = require('fs');
const path = require('path');

const ROOT = 'E:/gitWorkspace/local-kb-workbench';
const vuePath = path.join(ROOT, 'frontend/vendor/vue.global.prod.js');
const html = fs.readFileSync(path.join(ROOT, 'frontend/index.html'), 'utf8');
const appjs = fs.readFileSync(path.join(ROOT, 'frontend/js/app.js'), 'utf8');

const Vue = require(vuePath);
console.log('typeof Vue =', typeof Vue, '| has compile =', !!(Vue && Vue.compile));
console.log('Vue keys (first 15):', Vue ? Object.keys(Vue).slice(0, 15).join(',') : 'NONE');

function extractAppInner(html) {
  const open = html.indexOf('<div id="app"');
  const gt = html.indexOf('>', open) + 1;
  let i = gt, depth = 1;
  while (i < html.length) {
    if (html.startsWith('<div', i)) { depth++; i += 4; }
    else if (html.startsWith('</div>', i)) { depth--; if (depth === 0) break; i += 6; }
    else i++;
  }
  return html.slice(gt, i);
}
function extractTreeNodeTpl(appjs) {
  const m = appjs.indexOf('template: `');
  const start = m + 'template: `'.length;
  const end = appjs.indexOf('`', start);
  return appjs.slice(start, end);
}

let ok = true;
// 1) sanity: trivial template
try { Vue.compile('<div>hi {{ x }}</div>'); console.log('OK: trivial template'); }
catch (e) { ok = false; console.error('FAIL trivial:', e.stack); }

// 2) #app
try {
  const inner = extractAppInner(html);
  console.log('app inner length =', inner.length);
  Vue.compile(inner);
  console.log('OK: #app template compiled');
} catch (e) { ok = false; console.error('FAIL #app:', e.stack); }

// 3) tree-node
try {
  const tpl = extractTreeNodeTpl(appjs);
  console.log('tree-node tpl length =', tpl.length);
  Vue.compile(tpl);
  console.log('OK: tree-node template compiled');
} catch (e) { ok = false; console.error('FAIL tree-node:', e.stack); }

process.exit(ok ? 0 : 1);
