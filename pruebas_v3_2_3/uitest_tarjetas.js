// Uso: node uitest_tarjetas.js <extractor.html> <analisis.json> <salida.json>
// Carga la página REAL del extractor en jsdom, le da las piezas ya analizadas por el servidor y ejecuta su renderPiecesList real.
// Devuelve, por tarjeta: nombre mostrado, código, etiqueta de tallas (texto, tooltip, oculta o no) y archivo.
const fs = require('fs');
const { JSDOM, VirtualConsole } = require('jsdom');
const [htmlPath, inFile, outFile] = process.argv.slice(2);
if (!htmlPath || !inFile || !outFile) { console.error('Uso: node uitest_tarjetas.js <extractor.html> <analisis.json> <salida.json>'); process.exit(2); }
const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push(String((e && e.message) || e).slice(0, 200)));
const dom = new JSDOM(fs.readFileSync(htmlPath, 'utf8'), {
  runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/', virtualConsole: vc,
  beforeParse(win) { win.fetch = async () => ({ ok: false, status: 404, json: async () => ({}), blob: async () => new win.Blob([]) }); },
});
const win = dom.window;
const input = JSON.parse(fs.readFileSync(inFile, 'utf8'));
(async () => {
  await new Promise(r => win.document.readyState === 'complete' ? r() : win.addEventListener('load', r));
  const res = [];
  for (const esc of input.escenarios) {
    win.__pieces = esc.pieces;
    win.eval(`state.docId = 'doc1'; state.style = ${JSON.stringify(input.style)}; state.pieces = window.__pieces; state.skipped = new Set(); state.noRef = new Set();
              state.pieceNames = {}; state.map = {}; state.clips = Object.fromEntries(state.pieces.map(p => [p.id, [0, 0, 10, 10]]));
              renderPiecesList(new URLSearchParams());`);
    let chips = null;
    if (esc.sizesDetected) {
      win.__det = esc.sizesDetected;
      win.eval(`initCostData({ sizes: window.__det, sizes_source: 'el texto del PDF' }); renderPiecesList(new URLSearchParams());`);
      chips = [...win.document.querySelectorAll('#sizeChips button')].map(b => ({ t: b.textContent, sel: /bg-red-600\/30/.test(b.className) }));
    }
    const cards = [...win.document.querySelectorAll('#piecesContainer [data-pid]')].map(c => {
      const t = c.querySelector('.card-tallas');
      return { codigo: c.querySelector('.card-code').textContent, titulo: c.querySelector('.card-title').value, archivo: c.querySelector('.card-file').textContent,
               tallas: t ? t.textContent : null, tooltip: t ? t.title : null, oculta: t ? t.classList.contains('hidden') : null };
    });
    res.push({ nombre: esc.nombre, cards, chips });
  }
  fs.writeFileSync(outFile, JSON.stringify({ errors, res }, null, 1));
  console.log(`ok: ${res.length} escenario(s), ${errors.length} error(es) de página`);
  process.exit(0);
})().catch(e => { console.error('FALLO DEL ARNÉS:', e.stack || e); fs.writeFileSync(outFile, JSON.stringify({ harnessError: String(e), errors })); process.exit(1); });
