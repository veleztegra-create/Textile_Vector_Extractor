#!/usr/bin/env node
// Uso: node costos_dpi.js <costos.html> <specs.json> <salida.json> <salida.xlsx>
// Carga la página REAL de Costos en jsdom y ejecuta sus funciones reales:
//   procesarArchivos (subida manual) / recibirDesdeExtractor (envío desde el extractor)
//   -> tarjetas en pantalla -> descargarExcelConDatos (.xlsx) y copiarDatosAlPortapapeles (TSV).
// Solo se sustituye lo que un navegador aporta y jsdom no: decodificación de imagen, canvas, descargas, portapapeles.
const fs = require('fs');
const { JSDOM, VirtualConsole } = require('jsdom');
const JSZip = require('jszip');

const [htmlPath, specsPath, outPath, xlsxPath] = process.argv.slice(2);
if (!htmlPath || !specsPath || !outPath || !xlsxPath) { console.error('Uso: node costos_dpi.js <costos.html> <specs.json> <salida.json> <salida.xlsx>'); process.exit(2); }
const html = fs.readFileSync(htmlPath, 'utf8');
const parsed = JSON.parse(fs.readFileSync(specsPath, 'utf8'));
const specs = Array.isArray(parsed) ? parsed : parsed.specs;
const efectosPorNombre = Array.isArray(parsed) ? {} : (parsed.efectos || {});   // { nombre de archivo: [efectos] }

const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push(String((e && e.message) || e).slice(0, 220)));
vc.on('error', m => errors.push('console.error: ' + String(m).slice(0, 220)));

const captured = { xlsx: null, clipboard: null, downloads: [] };
const origGen = JSZip.prototype.generateAsync;     // en Node no existe type:'blob': se genera en bytes y se envuelve en Blob
JSZip.prototype.generateAsync = async function (o) {
  const d = await origGen.call(this, Object.assign({}, o, { type: 'uint8array' }));
  captured.xlsx = Buffer.from(d);
  return new dom.window.Blob([d]);
};

const alerts = [];   // { phase, tipo, msg }
let phase = 'carga';

const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/costos', virtualConsole: vc,
  beforeParse(win) {
    win.JSZip = JSZip;
    if (!win.Blob.prototype.arrayBuffer) {
      win.Blob.prototype.arrayBuffer = function () {
        return new Promise((res, rej) => { const fr = new win.FileReader(); fr.onload = () => res(fr.result); fr.onerror = rej; fr.readAsArrayBuffer(this); });
      };
    }
    win.URL.createObjectURL = () => 'blob:fake';
    win.URL.revokeObjectURL = () => {};
    win.HTMLAnchorElement.prototype.click = function () { captured.downloads.push(this.download || ''); };
    win.HTMLCanvasElement.prototype.getContext = function () { return { drawImage() {}, getImageData: () => ({ data: win.__pixels }) }; };
    Object.defineProperty(win.navigator, 'clipboard', { value: { writeText: async t => { captured.clipboard = t; } }, configurable: true });
    win.Image = class { set src(v) { this._s = v; setTimeout(() => this.onload && this.onload(), 0); } get src() { return this._s; }
                        get width() { return win.__imgW; } get height() { return win.__imgH; } };
  },
});
const win = dom.window;
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function waitFor(cond, what, ms = 60000) {
  const t0 = Date.now();
  while (!cond()) { if (Date.now() - t0 > ms) throw new Error('timeout esperando: ' + what); await sleep(15); }
}

(async () => {
  await new Promise(r => win.document.readyState === 'complete' ? r() : win.addEventListener('load', r));
  // las alertas reales se registran y se siguen mostrando
  const origAlert = win.mostrarAlerta;
  win.mostrarAlerta = function (msg, tipo) { alerts.push({ phase, tipo, msg }); return origAlert.call(this, msg, tipo); };
  // imagen sintética: mitad izquierda opaca (tinta), mitad derecha transparente
  win.eval(`window.__mk = function (w, h) { const a = new Uint8ClampedArray(w * h * 4), half = Math.floor(w / 2);
    for (let y = 0; y < h; y++) { const o = y * w * 4; for (let x = 0; x < half; x++) { const k = o + x * 4; a[k] = 200; a[k+1] = 30; a[k+2] = 30; a[k+3] = 255; } } return a; };`);
  const setPixels = (w, h) => { win.__imgW = w; win.__imgH = h; win.__pixels = win.__mk(w, h); };

  const dpiLeidos = [];
  for (const [i, spec] of specs.entries()) {
    phase = 'spec:' + i;
    const before = win.eval('imagenesProcesadas.length');
    const alertsBefore = alerts.length;
    if (spec.mode === 'upload') {
      const bytes = Buffer.from(spec.pngB64, 'base64');
      const file = new win.File([bytes], spec.fileName, { type: 'image/png' });
      dpiLeidos.push(win.leerDPIdePNG(await file.arrayBuffer()));
      setPixels(spec.width, spec.height);
      win.procesarArchivos([file]);
      await waitFor(() => win.eval('imagenesProcesadas.length') === before + 1 && alerts.length > alertsBefore, 'subida ' + spec.name);
    } else if (spec.mode === 'extractor') {
      const byUrl = {}, dims = [];
      for (const p of spec.pieces) { byUrl[p.url] = Buffer.from(p.pngB64, 'base64'); dims.push({ w: p.width, h: p.height }); dpiLeidos.push(win.leerDPIdePNG(new win.Uint8Array(byUrl[p.url]).buffer)); }
      win.fetch = async url => ({ ok: true, status: 200, blob: async () => new win.Blob([byUrl[url]], { type: 'image/png' }) });
      win.cargarImagenDesdeBlob = async () => { const d = dims.shift(); setPixels(d.w, d.h); return { width: d.w, height: d.h, src: 'data:image/png;base64,' }; };
      await win.recibirDesdeExtractor({ origen: spec.name + '.pdf', pdf: spec.name + '.pdf', style: 'TEST-0001-ABC', teamName: 'TEAM', sizes: spec.globalSizes || ['M'], category: '',
        pieces: spec.pieces.map(p => ({ id: p.id, placement: p.placement, file: p.fileName, sizes: p.sizes || [], url: p.url, refUrl: null })) });
      await waitFor(() => win.eval('imagenesProcesadas.length') === before + spec.pieces.length, 'extractor ' + spec.name);
    } else throw new Error('modo desconocido ' + spec.mode);
  }

  // efectos especiales simulados (lo que harían los chips de la tarjeta) y vista previa 'COMMENTS:' actualizada
  win.eval('(function (m) { imagenesProcesadas.forEach(i => { const e = m[i.metadatos.nombre]; if (e) i.metadatos.efectos = e; }); actualizarPreviews(); })(' + JSON.stringify(efectosPorNombre) + ')');
  const comentarioBase = win.document.getElementById('commentsInput').value;

  // ---- pantalla
  const cards = [...win.document.querySelectorAll('#thumbnailsGrid .thumbnail-card')].map(c => ({
    avisos: [...c.querySelectorAll('.aviso')].map(a => a.textContent.trim()),
    preview: (c.querySelector('.comentario-preview') || { textContent: null }).textContent,
    tallas: (c.querySelector('.badge-tallas') || { textContent: null }).textContent,
    rows: Object.fromEntries([...c.querySelectorAll('.info-row')].map(r => {
      const l = r.querySelector('.info-label'), v = r.querySelector('.info-value');
      return [l && l.textContent.trim(), v ? v.textContent.trim() : null];
    }).filter(x => x[0] && x[1] !== null)),
  }));
  const metadatos = JSON.parse(win.eval(`JSON.stringify(imagenesProcesadas.map(i => { const m = Object.assign({}, i.metadatos); delete m.src; delete m.refSrc; return m; }))`));

  // ---- Excel (.xlsx) y portapapeles (TSV) con las mismas imágenes procesadas
  phase = 'excel';
  for (const id of ['customerSelect', 'categorySelect']) {
    const el = win.document.getElementById(id);
    el.value = [...el.options].find(o => o.value && o.value !== '__OTRO__').value;
  }
  win.document.getElementById('chkRefsExcel').checked = false;
  await win.descargarExcelConDatos();
  await waitFor(() => captured.xlsx !== null, 'xlsx');
  await sleep(50);
  phase = 'tsv';
  win.copiarDatosAlPortapapeles();
  await waitFor(() => captured.clipboard !== null, 'tsv');

  fs.writeFileSync(xlsxPath, captured.xlsx);
  const z = await JSZip.loadAsync(captured.xlsx);
  const xml = await z.file('xl/worksheets/sheet1.xml').async('string');
  const celda = (c, r) => { const m = new RegExp('<c r="' + c + r + '"[^>]*>(?:<f>([^<]*)</f>)?<v>([^<]*)</v>').exec(xml); return m ? { f: m[1] || null, v: m[2] } : null; };
  const celdaTxt = (c, r) => {
    const m = new RegExp('<c r="' + c + r + '"([^>]*?)(?:/>|>([\\s\\S]*?)</c>)').exec(xml);
    if (!m) return null;
    const t = m[2] ? /<t[^>]*>([\s\S]*?)<\/t>/.exec(m[2]) : null;
    const unesc = x => x.replace(/&quot;/g, '"').replace(/&gt;/g, '>').replace(/&lt;/g, '<').replace(/&amp;/g, '&');
    return { texto: t ? unesc(t[1]) : '', estilo: (/\bs="(\d+)"/.exec(m[1]) || [])[1] || null };
  };
  const excelR = metadatos.map((_, i) => celdaTxt('R', 5 + i));
  const excelA = metadatos.map((_, i) => celdaTxt('A', 5 + i));
  const excelRows = metadatos.map((_, i) => Object.fromEntries(['G', 'H', 'I', 'J', 'K', 'L', 'O', 'P'].map(c => [c, celda(c, 5 + i)])));
  const tsv = captured.clipboard.trim().split('\n').map(l => l.split('\t'));

  const grid = () => [...win.document.querySelectorAll('#tallasGrid input.talla-checkbox')].map(i => ({ t: i.id.replace('talla-', ''), c: i.checked }));
  const tallasGrid = { inicial: grid() };
  win.seleccionarTodasTallas(); tallasGrid.todas = grid();
  win.seleccionarTodasTallas(); tallasGrid.ninguna = grid();
  fs.writeFileSync(outPath, JSON.stringify({ errors, alerts, tallasGrid, cards, metadatos, dpiLeidos, excelRows, excelR, excelA, comentarioBase, tsv, downloads: captured.downloads }, null, 1));
  console.log(`ok: ${metadatos.length} imagen(es), ${cards.length} tarjeta(s), ${alerts.length} alerta(s), ${errors.length} error(es) de página`);
  process.exit(0);
})().catch(e => { console.error('FALLO DEL ARNÉS:', e.stack || e); fs.writeFileSync(outPath, JSON.stringify({ harnessError: String(e), errors, alerts })); process.exit(1); });
