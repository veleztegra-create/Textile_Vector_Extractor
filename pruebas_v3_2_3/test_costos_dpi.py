"""Pruebas del DPI y las dimensiones físicas en Costos.

Uso: python test_costos_dpi.py <programa.py> <etiqueta> [directorio_salida]
Requiere: node + `npm install` en esta carpeta (jsdom, jszip). openpyxl es opcional (verificación independiente del .xlsx).
Salida: results_costos_dpi_<etiqueta>.json en el directorio de salida. Código de salida: 0 sin FAIL, 1 con algún FAIL.

Cada caso es un PNG con DPI conocido y un tamaño físico conocido; se procesa con las funciones REALES de la página de
Costos (jsdom) y se compara contra la verdad. Luego se exporta a .xlsx y a TSV y se comprueba que coincidan con la pantalla.
"""
import sys, io, os, re, json, zlib, struct, base64, shutil, tempfile, subprocess, warnings, zipfile, importlib.util, logging
from pathlib import Path
warnings.filterwarnings("ignore")
from PIL import Image

HERE = Path(__file__).resolve().parent
module_path, label = Path(sys.argv[1]).resolve(), sys.argv[2]
OUT = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else Path(tempfile.gettempdir()) / "tegra_tests"
OUT.mkdir(parents=True, exist_ok=True)
WORK = Path(tempfile.mkdtemp(prefix="costos_dpi_"))

results, skips = [], []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS  " if cond else "FAIL  ") + name + (f"   [{detail}]" if detail else ""))


def skip(name, why):
    skips.append((name, why))
    print(f"OMITIDA  {name}   [{why}]")


# ---------------------------------------------------------------- programa bajo prueba
spec = importlib.util.spec_from_file_location("costos_mod_" + label, str(module_path))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
logging.disable(logging.CRITICAL)
client = m.app.test_client()
(WORK / "costos.html").write_text(client.get("/costos").get_data(as_text=True), encoding="utf-8")

# ---------------------------------------------------------------- utilidades PNG
def chunk(typ, data):
    return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)


def set_phys(png, x, y, unit):
    """Quita cualquier pHYs y, si x no es None, inserta uno nuevo (ppm x/y, unidad) tras IHDR."""
    out, i = [png[:8]], 8
    while i < len(png):
        ln = struct.unpack(">I", png[i:i + 4])[0]
        typ = png[i + 4:i + 8]
        if typ != b"pHYs":
            out.append(png[i:i + 12 + ln])
        if typ == b"IHDR" and x is not None:
            out.append(chunk(b"pHYs", struct.pack(">IIB", x, y, unit)))
        i += 12 + ln
    return b"".join(out)


def read_phys(png):
    """Lectura independiente (Python) del DPI declarado: (x, y) o None si no hay pHYs en metros."""
    i = 8
    while i + 8 <= len(png):
        ln = struct.unpack(">I", png[i:i + 4])[0]
        typ = png[i + 4:i + 8]
        if typ == b"pHYs":
            if len(png) < i + 17:
                return None                      # chunk truncado: no hay DPI legible
            x, y, u = struct.unpack(">IIB", png[i + 8:i + 17])
            return (x * 0.0254, y * 0.0254) if u == 1 else None
        if typ in (b"IDAT", b"IEND"):
            return None
        i += 12 + ln
    return None


def solid_png(w, h, dpi=None):
    buf = io.BytesIO()
    kw = {"dpi": (dpi[0], dpi[1])} if dpi else {}
    Image.new("RGBA", (w, h), (200, 30, 30, 255)).save(buf, "PNG", **kw)
    return buf.getvalue()


def b64(b):
    return base64.b64encode(b).decode()


# ---------------------------------------------------------------- casos
KW, KH = 3.00, 2.00      # tamaño físico conocido (pulgadas) de los casos sintéticos
items = []               # un elemento por imagen procesada, en el orden de las tarjetas
specs = []


def add_upload(name, png, w, h, kind, known=None, note=""):
    specs.append({"mode": "upload", "name": name, "fileName": f"TEST-0001-ABC_{name}.png", "width": w, "height": h, "pngB64": b64(png)})
    items.append({"name": name, "kind": kind, "w": w, "h": h, "known": known, "phys": read_phys(png), "note": note})


for d in (150, 288, 300, 600, 1200):
    w, h = round(KW * d), round(KH * d)
    add_upload(f"{d}DPI", solid_png(w, h, (d, d)), w, h, "valido", (KW, KH))

# PNG de 600 DPI reales (1800x1200 = 3x2 in) cuyos metadatos faltan o están dañados: el DPI no se puede conocer
base = solid_png(1800, 1200, (300, 300))
add_upload("SIN_DPI", solid_png(1800, 1200), 1800, 1200, "estimado", (KW, KH), "sin pHYs")
add_upload("PHYS_CERO", set_phys(base, 0, 0, 1), 1800, 1200, "estimado", (KW, KH), "pHYs X=Y=0")
add_upload("PHYS_ABSURDO", set_phys(base, 0xFFFFFFFF, 0xFFFFFFFF, 1), 1800, 1200, "estimado", (KW, KH), "pHYs 4294967295")
add_upload("PHYS_MUY_BAJO", set_phys(base, 100, 100, 1), 1800, 1200, "estimado", (KW, KH), "pHYs 2.54 DPI")
add_upload("PHYS_UN_EJE", set_phys(base, 23622, 0, 1), 1800, 1200, "estimado", (KW, KH), "X válido, Y=0")
add_upload("PHYS_SIN_UNIDAD", set_phys(base, 23622, 23622, 0), 1800, 1200, "estimado", (KW, KH), "unidad desconocida")
trunc = set_phys(base, 11811, 11811, 1)
trunc = trunc[:33 + 8 + 4]                              # corta el pHYs a la mitad
add_upload("PHYS_TRUNCADO", trunc, 1800, 1200, "estimado", (KW, KH), "chunk pHYs truncado")
# extra (no pedido): DPI distinto por eje
add_upload("ANISOTROPICO_300x600", solid_png(900, 1200, (300, 600)), 900, 1200, "valido", (KW, KH), "300x600 DPI")

# PNG exportados por el propio extractor, con reducción de DPI (límite de píxeles bajado para forzarla)
PDF = (HERE / "test_garment.pdf").read_bytes()
did = m.new_session(PDF, "TEST-0001-ABC.pdf")["doc_id"]
ORIG_MAX = m.MAX_PIXELS
m.MAX_PIXELS = 1_500_000
tve_pieces, tve_meta = [], []
for pid, placement, dpi_req, side_pt in (("p01", "FRONT", 300, 300.0), ("p01", "FRONT", 600, 300.0), ("p02", "BACK", 300, 100.0)):
    url = f"/api/piece/{did}/{pid}.png?dpi={dpi_req}&alpha=1&trim=1"
    r = client.get(url)
    png = r.data
    im = Image.open(io.BytesIO(png))
    tve_pieces.append({"id": pid, "placement": placement, "fileName": f"TEST-0001-ABC_{placement}_{dpi_req}.png", "url": url,
                       "pngB64": b64(png), "width": im.size[0], "height": im.size[1]})
    tve_meta.append({"name": f"EXTRACTOR_{placement}_pedido{dpi_req}", "w": im.size[0], "h": im.size[1], "side_in": side_pt / 72,
                     "req": dpi_req, "eff_header": r.headers.get("X-Effective-DPI"), "phys": read_phys(png), "known": (side_pt / 72, side_pt / 72)})
m.MAX_PIXELS = ORIG_MAX
specs.append({"mode": "extractor", "name": "extractor", "pieces": tve_pieces})
for t in tve_meta:
    items.append({"name": t["name"], "kind": "extractor", "w": t["w"], "h": t["h"], "known": t["known"], "phys": t["phys"],
                  "req": t["req"], "eff_header": t["eff_header"], "note": "exportación del extractor"})

# ---------------------------------------------------------------- ejecución en la página real
AVISO = "DPI ESTIMADO: dimensiones estimadas a 300 DPI (PNG sin DPI válido)"      # texto exacto que debe aparecer en el Excel
EFECTOS = {"TEST-0001-ABC_150DPI.png": ["FOIL"], "TEST-0001-ABC_SIN_DPI.png": ["FOIL"]}   # un caso válido y uno estimado con efectos
(WORK / "specs.json").write_text(json.dumps({"specs": specs, "efectos": EFECTOS}), encoding="utf-8")
out_json, out_xlsx = WORK / "out.json", WORK / "salida.xlsx"
if not (HERE / "node_modules" / "jsdom").exists():
    print("Falta node_modules: ejecuta `npm install` en", HERE)
    sys.exit(3)
r = subprocess.run(["node", str(HERE / "costos_dpi.js"), str(WORK / "costos.html"), str(WORK / "specs.json"), str(out_json), str(out_xlsx)],
                   capture_output=True, text=True, cwd=str(HERE), timeout=600)
print(r.stdout.strip() or r.stderr.strip()[-500:])
data = json.loads(out_json.read_text(encoding="utf-8"))
if "harnessError" in data:
    print("FALLO DEL ARNÉS:", data["harnessError"])
    sys.exit(1)
shutil.copy(out_xlsx, OUT / f"costos_dpi_{label}.xlsx")

md, cards, xr, tsv, alerts = data["metadatos"], data["cards"], data["excelRows"], data["tsv"], data["alerts"]
check("el arnés procesó todas las imágenes (tarjetas == metadatos == filas Excel == filas TSV)",
      len(items) == len(md) == len(cards) == len(xr) == len(tsv), f"items={len(items)} md={len(md)} cards={len(cards)} xlsx={len(xr)} tsv={len(tsv)}")
check("la página no produjo errores de JavaScript", not data["errors"], "; ".join(data["errors"][:2]))
if len(md) != len(items):
    sys.exit(1)

num = lambda s: float(re.search(r"[-\d.]+", s).group())
rows_out = []
print("\n== Dimensiones y área contra el tamaño físico conocido")
for k, it in enumerate(items):
    mm, card = md[k], cards[k]
    nm = it["name"]
    W, H = it["known"]
    true_dpi = it["phys"]
    ancho, alto, area = float(mm["ancho"]), float(mm["alto"]), float(mm["area"])
    est = bool(mm.get("dpiEstimado"))
    # --- ink / colores: no deben haber cambiado (requisito 7)
    ink_exp = (it["w"] // 2) * it["h"]
    check(f"[{nm}] conteo de tinta, tela, colores y complejidad intactos",
          mm["pixelsInk"] == ink_exp and mm["pixelsFabric"] == it["w"] * it["h"] - ink_exp and mm["colores"] == 1 and mm["complejidad"] == "LOW",
          f"ink={mm['pixelsInk']} (esperado {ink_exp}), colores={mm['colores']}")
    if it["kind"] in ("valido", "extractor"):
        tx, ty = true_dpi
        tolW, tolH = 0.5 / tx + 0.005 + 1e-6, 0.5 / ty + 0.005 + 1e-6
        tolA = W * tolH + H * tolW + tolW * tolH + 0.005
        ok_dims = abs(ancho - W) <= tolW and abs(alto - H) <= tolH
        check(f"[{nm}] ancho y alto = tamaño físico conocido", ok_dims,
              f"{ancho:.2f}x{alto:.2f} in vs {W:.4f}x{H:.4f} in (tol ±{tolW:.4f}); PNG {it['w']}x{it['h']} px a {tx:.1f}x{ty:.1f} DPI")
        check(f"[{nm}] área = área física conocida", abs(area - W * H) <= tolA, f"{area:.2f} in² vs {W * H:.3f} in² (tol ±{tolA:.3f})")
        expect_txt = (f"{round(tx)} DPI" if abs(tx - ty) < 0.5 else f"{round(tx)}×{round(ty)} DPI")
        check(f"[{nm}] DPI usado = DPI de los metadatos del PNG, no estimado",
              (not est) and abs(mm.get("dpiX", 0) - tx) < 0.05 and abs(mm.get("dpiY", 0) - ty) < 0.05
              and card["rows"].get("DPI usado:") == expect_txt,
              f"usado {mm.get('dpiX')}x{mm.get('dpiY')} ({card['rows'].get('DPI usado:')}), metadatos {tx:.2f}x{ty:.2f}")
        if it["kind"] == "extractor":
            eff = float(it["eff_header"])
            check(f"[{nm}] se usa el DPI EFECTIVO ({eff:.0f}), no el pedido ({it['req']})",
                  abs(mm.get("dpiX", 0) - eff) < 0.05 and eff < it["req"] or (eff == it["req"] and abs(mm.get("dpiX", 0) - eff) < 0.05),
                  f"usado {mm.get('dpiX')}, X-Effective-DPI {eff:.0f}, pedido {it['req']}")
    elif it["kind"] == "estimado":
        check(f"[{nm}] DPI faltante/inválido: se usa 300 y se marca como ESTIMADO",
              est and mm["dpiX"] == 300 and mm["dpiY"] == 300 and "(estimado)" in card["rows"].get("DPI usado:", ""),
              f"estimado={est}, usado={mm.get('dpiX')}x{mm.get('dpiY')}, pantalla='{card['rows'].get('DPI usado:')}' ({it['note']})")
        check(f"[{nm}] dimensiones estimadas = píxeles / 300 (no se inventa otro valor)",
              abs(ancho - round(it["w"] / 300, 2)) < 1e-9 and abs(alto - round(it["h"] / 300, 2)) < 1e-9, f"{ancho:.2f}x{alto:.2f}")
        check(f"[{nm}] advertencia visible en la tarjeta y alerta al cargar",
              any("ESTIMADAS" in a for a in card["avisos"]) and any(a["phase"] == f"spec:{k}" and "ESTIMARON" in a["msg"] and it["name"] in a["msg"] for a in alerts),
              "; ".join(card["avisos"])[:90])
    if it["kind"] == "valido" and it["name"] == "300DPI":
        check(f"[{nm}] a 300 DPI no aparece ninguna advertencia de resolución", not card["avisos"] or all("NAME" in a for a in card["avisos"]), str(card["avisos"]))
    rows_out.append((nm, it["w"], it["h"], f"{true_dpi[0]:.0f}" if true_dpi else "—", f"{W:.3f}x{H:.3f}", f"{ancho:.2f}x{alto:.2f}",
                     f"{W * H:.2f}", f"{area:.2f}", card["rows"].get("DPI usado:", "—")))

print("\n== Pantalla == Excel (.xlsx) == portapapeles (TSV)")
for k, it in enumerate(items):
    mm, card, x, t = md[k], cards[k], xr[k], tsv[k]
    nm = it["name"]
    s_size, s_area = card["rows"]["Tamaño:"], card["rows"]["Área:"]
    s_ancho, s_alto = [v.strip().strip('"') for v in s_size.split("×")]
    s_area_v = s_area.replace("in²", "").strip()
    G, Hh, I, O, P = (float(x[c]["v"]) for c in ("G", "H", "I", "O", "P"))
    check(f"[{nm}] Excel G/H = ancho/alto de la pantalla ({s_ancho} x {s_alto})", G == float(s_ancho) and Hh == float(s_alto), f"G={G} H={Hh}")
    check(f"[{nm}] Excel I (fórmula +H*G) = área de la pantalla ({s_area_v})",
          x["I"]["f"] == f"+H{5 + k}*G{5 + k}" and abs(I - float(s_area_v)) <= 0.005 + 1e-9 and abs(I - G * Hh) < 1e-9, f"I={I} fórmula={x['I']['f']}")
    check(f"[{nm}] TSV G/H/I idénticos a la pantalla", t[6] == s_ancho and t[7] == s_alto and t[8] == s_area_v, f"{t[6]}|{t[7]}|{t[8]}")
    check(f"[{nm}] el DPI de la pantalla es coherente con lo que recibe el Excel (G·DPI ≈ píxeles de ancho, H·DPI ≈ alto)",
          abs(G * mm.get("dpiX", 300) - it["w"]) <= 0.005 * mm.get("dpiX", 300) + 0.5 and abs(Hh * mm.get("dpiY", 300) - it["h"]) <= 0.005 * mm.get("dpiY", 300) + 0.5,
          f"{G}in x {mm.get('dpiX')} = {G * mm.get('dpiX', 300):.1f} px (real {it['w']}); {Hh}in x {mm.get('dpiY')} = {Hh * mm.get('dpiY', 300):.1f} px (real {it['h']})")
    check(f"[{nm}] P (área impresa) del Excel = I·O y coincide con el TSV (dif. por redondeo de área ≤ 0,005·O)",
          abs(P - I * O) < 1e-9 and abs(P - float(t[15])) <= 0.0051 * max(O, 1e-9) + 1e-9, f"P xlsx={P:.6f} tsv={t[15]}")

print("\n== Constancia de DPI estimado en el Excel (columna R = COMMENTS) y plantilla intacta")
tinta = data["comentarioBase"]


def esperado_r(it):
    efx = EFECTOS.get(f"TEST-0001-ABC_{it['name']}.png", [])
    base = " + ".join(x for x in [tinta] + efx if x)
    if it["kind"] != "estimado":
        return base
    return (base + " | " + AVISO) if base else AVISO


def esperado_tsv(it):
    c = tinta or "HSWB"
    return c + " | " + AVISO if it["kind"] == "estimado" else c


for k, it in enumerate(items):
    nm, est = it["name"], it["kind"] == "estimado"
    R = data["excelR"][k]
    r_txt = R["texto"] if R else None
    check(f"[{nm}] Excel R (COMMENTS) " + ("lleva la constancia de DPI estimado" if est else "queda como siempre, SIN constancia"),
          r_txt == esperado_r(it), f"R='{r_txt}'")
    check(f"[{nm}] la vista previa 'COMMENTS:' de la tarjeta coincide con la columna R del Excel",
          cards[k]["preview"] == "COMMENTS: " + (r_txt or ""), f"tarjeta='{cards[k]['preview']}'")
    check(f"[{nm}] TSV (portapapeles) columna R " + ("lleva la constancia" if est else "sin constancia"),
          tsv[k][17] == esperado_tsv(it), f"TSV R='{tsv[k][17]}'")

# --- plantilla original intacta: partes del paquete, filas, columnas, estilos y fórmulas
tz = zipfile.ZipFile(io.BytesIO(base64.b64decode(m.EXCEL_TEMPLATE_B64)))
gz = zipfile.ZipFile(OUT / f"costos_dpi_{label}.xlsx")
check("el .xlsx conserva exactamente las mismas partes que la plantilla (sin partes nuevas ni faltantes)", set(tz.namelist()) == set(gz.namelist()))
otras = [n for n in tz.namelist() if n != "xl/worksheets/sheet1.xml" and tz.read(n) != gz.read(n)]
check("todas las partes salvo la hoja (estilos, libro, temas, relaciones...) son idénticas byte a byte a la plantilla", not otras, str(otras[:3]))
txml, gxml = tz.read("xl/worksheets/sheet1.xml").decode(), gz.read("xl/worksheets/sheet1.xml").decode()


def sin_filas(xml, a, b):
    for r_ in range(a, b + 1):
        xml = re.sub(r'<row r="%d"[^>]*?(?:/>|>.*?</row>)' % r_, "", xml, flags=re.S)
    return xml


check("la hoja es idéntica a la plantilla fuera de las filas de datos (encabezados, anchos, filtros, comentarios, impresión)",
      sin_filas(txml, 5, 4 + len(items)) == sin_filas(gxml, 5, 4 + len(items)))


def celdas(xml, r_):
    mm = re.search(r'<row r="%d"[^>]*?(?:/>|>(.*?)</row>)' % r_, xml, re.S)
    body = (mm.group(1) or "") if mm else ""
    out = {}
    for col, attrs in re.findall(r'<c r="([A-Z]+)%d"([^>]*?)/?>' % r_, body):
        st = re.search(r'\bs="(\d+)"', attrs)
        out[col] = st.group(1) if st else None
    return out


tplt = celdas(txml, 5)
COLS = list("ABCDEFGHIJKLMNOPQRSTUVW")
mal_estilo, mal_form = [], []
for k in range(len(items)):
    r_ = 5 + k
    cg = celdas(gxml, r_)
    if list(cg) != COLS or any(cg[c] != tplt.get(c) for c in COLS):
        mal_estilo.append((items[k]["name"], r_))
    esperadas = {"I": f"+H{r_}*G{r_}", "J": f"K{r_}+L{r_}", "N": f"IFERROR(K{r_}/J{r_},0)", "O": f"IFERROR(L{r_}/J{r_},0)", "P": f"IFERROR(I{r_}*O{r_},0)"}
    for c, f in esperadas.items():
        mf = re.search(r'<c r="%s%d"[^>]*><f>([^<]*)</f>' % (c, r_), gxml)
        if not mf or mf.group(1) != f:
            mal_form.append((items[k]["name"], c))
check("todas las filas (con y sin DPI estimado) tienen las columnas A–W con el estilo de la plantilla (incluida la R)", not mal_estilo, str(mal_estilo[:3]))
check("las fórmulas de I, J, N, O y P siguen siendo las originales en todas las filas", not mal_form, str(mal_form[:3]))
check("la columna R de la plantilla es visible (no oculta) y se llama COMMENTS",
      'min="18" max="18"' in txml and not re.search(r'<col min="18" max="18"[^>]*hidden', txml)
      and "COMMENTS" in tz.read("xl/sharedStrings.xml").decode())

print("\n== Verificación independiente del .xlsx con openpyxl")
try:
    import openpyxl
except ImportError:
    openpyxl = None
if openpyxl is None:
    skip("lectura independiente del .xlsx con openpyxl", "openpyxl no está instalado (pip install openpyxl)")
else:
    wv = openpyxl.load_workbook(OUT / f"costos_dpi_{label}.xlsx", data_only=True).worksheets[0]
    wf = openpyxl.load_workbook(OUT / f"costos_dpi_{label}.xlsx", data_only=False).worksheets[0]
    bad = []
    for k in range(len(items)):
        r_ = 5 + k
        G, Hh, I, P = (wv[f"{c}{r_}"].value for c in "GHIP")
        sG, sH = float(cards[k]["rows"]["Tamaño:"].split("×")[0].strip().strip('"')), float(cards[k]["rows"]["Tamaño:"].split("×")[1].strip().strip('"'))
        if not (G == sG and Hh == sH and abs(I - G * Hh) < 1e-9 and str(wf[f"I{r_}"].value).replace("=", "") == f"+H{r_}*G{r_}"
                and (wv[f"R{r_}"].value or "") == esperado_r(items[k])):
            bad.append((items[k]["name"], G, Hh, I, wf[f"I{r_}"].value, wv[f"R{r_}"].value))
    check("openpyxl lee en el .xlsx los mismos G/H que la pantalla, la fórmula I=+H*G con su valor y el comentario R esperado", not bad, str(bad[:2]))

# ---------------------------------------------------------------- avisos de DPI estimado al exportar a Excel
est_names = [f"TEST-0001-ABC_{it['name']}.png" for it in items if it["kind"] == "estimado"]
ex_alert = " ".join(a["msg"] for a in alerts if a["phase"] == "excel")
check("al descargar el Excel se advierte de las imágenes con DPI estimado (todas listadas)",
      "ESTIMADAS" in ex_alert and all(n in ex_alert for n in est_names), ex_alert[:110])

print("\n== Resumen de la tabla (px | DPI metadatos | físico conocido | informado | área conocida | área informada | DPI usado en pantalla)")
for rw in rows_out:
    print("  {:<34}{:>5}x{:<5}{:>6}  {:>13} -> {:>11}   {:>7} -> {:>7}   {}".format(*rw))

fails = [n for n, ok in results if not ok]
(OUT / f"results_costos_dpi_{label}.json").write_text(json.dumps({
    "label": label, "pass": len(results) - len(fails), "fail": len(fails), "omitidas": len(skips),
    "fallidas": fails, "omitidas_detalle": [list(x) for x in skips]}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\nRESUMEN COSTOS-DPI [{label}]: {len(results) - len(fails)}/{len(results)} pruebas PASS, {len(fails)} FAIL, {len(skips)} OMITIDAS")
sys.exit(1 if fails else 0)
