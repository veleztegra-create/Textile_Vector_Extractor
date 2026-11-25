// Uso: node uitest_envio.js <bloque_extractor.js> <analisis.json> <salida.json>
// Ejecuta el sendToCosts REAL del extractor (con sus helpers de nombres) sobre piezas ya analizadas por el servidor
// y guarda el payload que enviaría a Costos. analisis.json = { style, escenarios: [ { nombre, pieces:[...], pieceNames:{id: texto} } ] }.
const fs = require('fs'), vm = require('vm');
const [blockFile, inFile, outFile] = process.argv.slice(2);
if (!blockFile || !inFile || !outFile) { console.error('Uso: node uitest_envio.js <bloque.js> <analisis.json> <salida.json>'); process.exit(2); }
const src = fs.readFileSync(blockFile, 'utf8');
function fn(name) {
  const m = new RegExp('(async\\s+)?function\\s+' + name + '\\s*\\(').exec(src); if (!m) throw new Error('no encontré la función ' + name);
  let i = src.indexOf('{', m.index), d = 0, j = i;
  for (; j < src.length; j++) { if (src[j] === '{') d++; else if (src[j] === '}') { d--; if (!d) break; } }
  return src.slice(m.index, j + 1);
}
function cst(name) {
  const m = new RegExp('const\\s+' + name + '\\s*=[^\\n]*;').exec(src); if (!m) throw new Error('no encontré la constante ' + name);
  return m[0];
}
const input = JSON.parse(fs.readFileSync(inFile, 'utf8'));
const out = [];
for (const esc of input.escenarios) {
  let captured = null; const toasts = [];
  const ctx = {
    state: { docId: 'doc1', fileName: 'TEST.pdf', style: input.style, teamName: 'TEAM', teamCode: '', category: 'GAME', pieces: esc.pieces,
             clips: Object.fromEntries(esc.pieces.map(p => [p.id, [0, 0, 1, 1]])), skipped: new Set(), noRef: new Set(),
             pieceNames: esc.pieceNames || {}, map: {}, sizesSel: new Set(esc.sizesSel || []), sizesDetected: esc.sizesDetected || [], sending: false },
    $: id => ({ checked: false, value: '', textContent: '', classList: { toggle() {} } }),
    costQuery: () => new URLSearchParams({ dpi: '300' }), refQuery: () => new URLSearchParams({ dpi: '150' }),
    setTab() {}, showToast: (m, t) => toasts.push(m),
    waitCostos: async () => ({ recibirDesdeExtractor: async p => { captured = p; return { total: p.pieces.length }; } }),
    console, URLSearchParams, Set, Object,
  };
  vm.createContext(ctx);
  for (const c of ['normCode', 'cleanName', 'translated', 'customName', 'SIZE_ORDER', 'pieceLabel']) vm.runInContext(cst(c), ctx);
  try { vm.runInContext(cst('isNumSize'), ctx); } catch (e) { /* versión sin soporte de tallas numéricas */ }
  try { vm.runInContext(fn('allSizes'), ctx); } catch (e) { /* versión sin soporte de tallas numéricas: sendToCosts usa SIZE_ORDER */ }
  for (const f of ['baseName', 'fileNames', 'sendToCosts']) vm.runInContext(fn(f), ctx);
  vm.runInContext('sendToCosts()', ctx).then(() => {});
  out.push({ nombre: esc.nombre, get payload() { return captured; }, toasts });
}
setTimeout(() => {
  fs.writeFileSync(outFile, JSON.stringify(out.map(o => ({ nombre: o.nombre, payload: o.payload, toasts: o.toasts })), null, 1));
  console.log(`ok: ${out.length} escenario(s)`);
}, 200);
