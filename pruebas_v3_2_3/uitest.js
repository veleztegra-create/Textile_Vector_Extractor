// Uso: node uitest.js <url_base> <archivo_doc_id> <reduced|normal> <bloque_js>
// Ejecuta las funciones REALES downloadPiece / exportZip / appendWarning (extraídas del bloque JS de la página)
// contra un servidor Flask en vivo, con un DOM mínimo simulado.
const fs = require('fs'), vm = require('vm');
const [base, docIdFile, modeArg, blockFile] = process.argv.slice(2);
if (!base || !docIdFile || !modeArg || !blockFile) { console.error('Uso: node uitest.js <url_base> <archivo_doc_id> <reduced|normal> <bloque_js>'); process.exit(2); }
const expectReduced = modeArg === 'reduced';
const src = fs.readFileSync(blockFile, 'utf8');
function extract(name) {
  const re = new RegExp('(async\\s+)?function\\s+' + name + '\\s*\\(');
  const m = re.exec(src); if (!m) throw new Error('no encontré ' + name);
  let i = src.indexOf('{', m.index), depth = 0, j = i;
  for (; j < src.length; j++) { if (src[j] === '{') depth++; else if (src[j] === '}') { depth--; if (!depth) break; } }
  return src.slice(m.index, j + 1);
}
const docId = fs.readFileSync(docIdFile, 'utf8').trim();
const log = { downloads: [], toasts: [] };
const warnBox = { children: [], appendChild(c) { this.children.push(c); }, classList: { remove() {} } };
let refDpi = '150';
const ctx = {
  state: { docId, dpi: 300, style: 'TEST-0001-ABC', pieces: [{ id: 'p01' }, { id: 'p02' }], skipped: new Set() },
  fileNames: () => ({ p01: 'Frente', p02: 'Espalda' }),
  exportQuery: () => new URLSearchParams({ dpi: '300', trim: '1', bg: 'transparent' }),
  refLayersParam: () => null,
  $: (id) => id === 'warningsBox' ? warnBox : { value: refDpi },
  showToast: (msg, type = 'ok') => log.toasts.push({ msg, type }),
  showLoader() {}, hideLoader() {},
  fetch: (u, o) => fetch(base + u, o),
  URL: { createObjectURL: () => 'blob:x', revokeObjectURL() {} },
  document: { createElement: (t) => ({ tag: t, textContent: '', click() { if (this.download) log.downloads.push(this.download); }, remove() {} }),
              body: { appendChild() {} } },
  setTimeout: () => 0, parseInt, decodeURIComponent, Array, Set, console,
};
vm.createContext(ctx);
for (const n of ['appendWarning', 'downloadPiece', 'exportZip']) vm.runInContext(extract(n), ctx);
let pass = 0, fail = 0;
const check = (n, c, d = '') => { (c ? pass++ : fail++); console.log((c ? 'PASS  ' : 'FAIL  ') + n + (d ? '   [' + d + ']' : '')); };
const reset = () => { log.downloads.length = 0; log.toasts.length = 0; };
const lastToast = () => (log.toasts[log.toasts.length - 1] || { msg: '' }).msg;
(async () => {
  await vm.runInContext('downloadPiece("p01")', ctx);
  await vm.runInContext('downloadPiece("p02")', ctx);
  const warnsAfterPieces = warnBox.children.length;
  let effPiece = 0;
  if (expectReduced) {
    const mm = /^Frente_(\d+)DPI\.png$/.exec(log.downloads[0] || ''); effPiece = mm ? +mm[1] : 0;
    check('descarga individual reducida: nombre con sufijo _<DPI>DPI (<300)', effPiece > 0 && effPiece < 300, log.downloads[0]);
    check('descarga individual NO reducida: nombre intacto', log.downloads[1] === 'Espalda.png', log.downloads[1]);
    check('aviso persistente solo para la pieza reducida, con DPI real y pedido',
      warnsAfterPieces === 1 && new RegExp(`${effPiece} DPI \\(pedido: 300 DPI\\)`).test(warnBox.children[0].textContent), warnBox.children[0] && warnBox.children[0].textContent);
    check('toast de advertencia (tipo error) mostrado', log.toasts.some(t => t.type === 'error' && new RegExp(`${effPiece} DPI`).test(t.msg)));
    await vm.runInContext('downloadPiece("p01")', ctx);
    check('el aviso no se duplica al repetir la descarga', warnBox.children.length === 1);
  } else {
    check('sin reducción: nombres intactos', log.downloads[0] === 'Frente.png' && log.downloads[1] === 'Espalda.png', log.downloads.join(' | '));
    check('sin reducción: ningún aviso ni toast de error', warnsAfterPieces === 0 && !log.toasts.some(t => t.type === 'error'));
  }

  // ---- ZIP modo art
  reset();
  await vm.runInContext('exportZip("art")', ctx);
  if (expectReduced) {
    const mm = /^TEST-0001-ABC_Piezas_PNG_(\d+)-300DPI\.zip$/.exec(log.downloads[0] || '');
    check('ZIP art: descarga con el nombre real (rango min-300)', !!mm && +mm[1] < 300, log.downloads[0]);
    check('ZIP art: toast con "1 de arte (mínimo X DPI, pedido 300 DPI)" y sin mención de referencias',
      log.toasts.some(t => t.type === 'error' && /1 archivo\(s\)/.test(t.msg) && /1 de arte \(mínimo \d+ DPI, pedido 300 DPI\)/.test(t.msg) && !/de referencias/.test(t.msg)), lastToast());
  } else {
    check('ZIP art sin reducción: nombre igual que antes', log.downloads[0] === 'TEST-0001-ABC_Piezas_PNG_300DPI.zip', log.downloads[0]);
    check('ZIP art sin reducción: toast normal y sin avisos', log.toasts.some(t => t.type === 'ok' && /^ZIP descargado/.test(t.msg)) && warnBox.children.length === 0);
  }

  // ---- ZIP modo both con refdpi=600 (dos DPI pedidos distintos)
  reset(); refDpi = '600';
  await vm.runInContext('exportZip("both")', ctx);
  if (expectReduced) {
    const t = lastToast();
    check('ZIP both: mensaje con total 2 y resúmenes separados (arte pedido 300 / referencias pedido 600)',
      /2 archivo\(s\)/.test(t) && /1 de arte \(mínimo \d+ DPI, pedido 300 DPI\)/.test(t) && /1 de referencias \(mínimo \d+ DPI, pedido 600 DPI\)/.test(t), t);
    check('ZIP both: nombre del ZIP sin cambios', log.downloads[0] === 'TEST-0001-ABC_Arte_y_Referencias.zip', log.downloads[0]);
    reset();
    await vm.runInContext('exportZip("ref")', ctx);
    const t2 = lastToast();
    check('ZIP ref: informa SOLO referencias con el DPI pedido de referencias (600), no el de arte',
      /1 archivo\(s\)/.test(t2) && /1 de referencias \(mínimo \d+ DPI, pedido 600 DPI\)/.test(t2) && !/de arte/.test(t2) && !/pedido 300/.test(t2), t2);
  } else {
    check('ZIP both sin reducción (refdpi=600 cabe en el límite): sin avisos nuevos', !log.toasts.some(t => t.type === 'error') && warnBox.children.length === 0, lastToast());
  }

  // ---- error del servidor
  reset(); ctx.state.docId = 'sesion-inexistente';
  await vm.runInContext('downloadPiece("p01")', ctx);
  check('error del servidor (404): toast de error y NO se descarga nada',
    log.downloads.length === 0 && log.toasts.some(t => t.type === 'error' && /expir/.test(t.msg)), lastToast());
  console.log(`\nRESUMEN UI [${expectReduced ? 'con reducción' : 'sin reducción'}]: ${pass}/${pass + fail} PASS, ${fail} FAIL`);
  process.exit(fail ? 1 : 0);
})();
