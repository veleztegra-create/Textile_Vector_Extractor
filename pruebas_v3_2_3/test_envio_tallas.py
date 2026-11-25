"""Pruebas de la cadena completa: PDF -> análisis -> payload del extractor -> Costos -> Excel (.xlsx) y TSV.
Las tallas de cada pieza (S-L, XL-5XL...) viajan SOLO a la columna SIZE: nunca forman parte del nombre/placement/archivo.
Incluye el PDF real con tallas divididas del usuario (mangas S-L y XL-5XL, nombres repetidos) y la regla de convivencia con la
lista global de tallas (la talla propia de la pieza se limita a las tallas seleccionadas).

Uso: python test_envio_tallas.py <programa.py> <etiqueta> [directorio_salida]
Requiere node y `npm install` en esta carpeta (jsdom, jszip). Código de salida: 0 sin FAIL, 1 con algún FAIL, 3 sin node_modules.
"""
import sys, io, os, re, json, base64, tempfile, subprocess, logging, warnings, importlib.util
from pathlib import Path
warnings.filterwarnings("ignore")
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_pdfs as B

module_path, label = Path(sys.argv[1]).resolve(), sys.argv[2]
OUT = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else Path(tempfile.gettempdir()) / "tegra_tests"
OUT.mkdir(parents=True, exist_ok=True)
WORK = Path(tempfile.mkdtemp(prefix="envio_tallas_"))
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS  " if cond else "FAIL  ") + name + (f"   [{detail}]" if detail else ""))


if not (HERE / "node_modules" / "jsdom").exists():
    print("Falta node_modules: ejecuta `npm install` en", HERE)
    sys.exit(3)

spec = importlib.util.spec_from_file_location("envio_mod_" + label, str(module_path))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
logging.disable(logging.CRITICAL)
STYLE = "TEST-0002-XYZ"
ALL8 = ["S", "M", "L", "XL", "2XL", "3XL", "4XL", "5XL"]
SIZE_IN_NAME = re.compile(r"(?<![A-Za-z0-9])(?:[2-5]XL|XL|XS|S-M|L-XL|S-L|\d-\dXL|S-5XL|XL-5XL)(?![A-Za-z0-9])")

# ---- 1. análisis real del servidor: PDF real del usuario + hojas sintéticas
REAL = HERE / "ejemplo_tallas_divididas_real.pdf"
ALL_NUM = ["40", "44", "48", "52", "56", "60", "64"]
fuentes = {"pdf_real": REAL.read_bytes(), "numerico": B.numeric_labels(), "cuellos_por_talla": B.collars_one_label(["S-M", "L-XL", "2-3XL"]),
           "hombros_pareja": B.pair_one_label("SHDL PL"), "cuello_doble_con_talla": B.two_collars_one_label_with_size("COLLAR S-M")}
_pub = {n: m.analyze_pdf(d, f"{STYLE}.pdf")[0] for n, d in fuentes.items()}
analisis = {n: p["pieces"] for n, p in _pub.items()}
esc = [{"nombre": n, "pieces": p, "sizesSel": ALL8} for n, p in analisis.items()]
esc.append({"nombre": "numerico", "pieces": analisis["numerico"], "sizesSel": ALL_NUM, "sizesDetected": ALL_NUM})
esc.append({"nombre": "numerico_seleccion_parcial", "pieces": analisis["numerico"], "sizesSel": ["44", "48", "52"], "sizesDetected": ALL_NUM})
esc.append({"nombre": "numerico_sin_interseccion", "pieces": analisis["numerico"], "sizesSel": ["40"], "sizesDetected": ALL_NUM})
esc.append({"nombre": "pdf_real_seleccion_parcial", "pieces": analisis["pdf_real"], "sizesSel": ["S", "M", "L", "XL", "2XL", "3XL"]})
esc.append({"nombre": "pdf_real_sin_interseccion", "pieces": analisis["pdf_real"], "sizesSel": ["S", "M"]})
esc.append({"nombre": "pdf_real_sin_seleccion", "pieces": analisis["pdf_real"], "sizesSel": []})
ren = [dict(p) for p in analisis["cuellos_por_talla"]]
esc.append({"nombre": "renombrada_a_mano", "pieces": ren, "sizesSel": ALL8, "pieceNames": {ren[1]["id"]: "Cuello grande"}})
(WORK / "analisis.json").write_text(json.dumps({"style": STYLE, "escenarios": esc}), encoding="utf-8")

# ---- 2. sendToCosts REAL del extractor
blocks = [b for a, b in re.findall(r"<script([^>]*)>(.*?)</script>", m.HTML_TEMPLATE, flags=re.S) if "src=" not in a]
block = next(b for b in blocks if "async function sendToCosts" in b)
(WORK / "extractor_block.js").write_text(block, encoding="utf-8")
r = subprocess.run(["node", str(HERE / "uitest_envio.js"), str(WORK / "extractor_block.js"), str(WORK / "analisis.json"), str(WORK / "payloads.json")],
                   capture_output=True, text=True, cwd=str(HERE), timeout=120)
print(r.stdout.strip() or r.stderr.strip()[-400:])
payloads = {p["nombre"]: p["payload"] for p in json.loads((WORK / "payloads.json").read_text(encoding="utf-8"))} if (WORK / "payloads.json").exists() else {}
E = lambda n: (payloads.get(n) or {"pieces": []})["pieces"]

print("\n== A. Payload que el extractor envía a Costos (las tallas viajan en 'sizes', NO en el nombre)")
pr = E("pdf_real")
check("PDF real: 9 piezas, placement sin tallas (Left sleeve ×2, Right sleeve ×2...)",
      [x["placement"] for x in pr] == ["Nameplate piece", "Left yoke piece", "Right yoke piece", "Left sleeve", "Left sleeve", "Right sleeve", "Right sleeve", "Back piece", "Front piece"],
      str([x["placement"] for x in pr]))
check("PDF real: cada pieza viaja con SUS tallas (mangas S-L = [S,M,L], XL-5XL = [XL..5XL]; el resto las 8)",
      [x.get("sizes") for x in pr] == [ALL8, ALL8, ALL8, ["S", "M", "L"], ["XL", "2XL", "3XL", "4XL", "5XL"], ["S", "M", "L"], ["XL", "2XL", "3XL", "4XL", "5XL"], ALL8, ALL8],
      str([x.get("sizes") for x in pr][3:7]))
files = [x["file"] for x in pr]
check("PDF real: los 9 archivos tienen nombre único (los repetidos con _2) y ninguna talla en el nombre",
      len(set(files)) == 9 and f"{STYLE}_Left_sleeve.png" in files and f"{STYLE}_Left_sleeve_2.png" in files and not [f for f in files if SIZE_IN_NAME.search(f.replace(STYLE, ""))], str(files))
check("la lista global de tallas seleccionadas se sigue enviando igual", (payloads.get("pdf_real") or {}).get("sizes") == ALL8)
parcial = E("pdf_real_seleccion_parcial")
check("convivencia con la lista global: si se desmarcan 4XL y 5XL, la talla propia se limita a lo seleccionado (XL-5XL -> XL,2XL,3XL; S-5XL -> S..3XL; S-L igual)",
      [x.get("sizes") for x in parcial] == [ALL8[:6]] * 3 + [["S", "M", "L"], ["XL", "2XL", "3XL"], ["S", "M", "L"], ["XL", "2XL", "3XL"], ALL8[:6], ALL8[:6]],
      str([x.get("sizes") for x in parcial]))
sini = E("pdf_real_sin_interseccion")
check("si la selección global no toca la talla propia de una pieza (XL-5XL con solo S,M marcadas) se conserva la talla propia",
      [x.get("sizes") for x in sini][3:7] == [["S", "M", "L"][:2], ["XL", "2XL", "3XL", "4XL", "5XL"], ["S", "M"], ["XL", "2XL", "3XL", "4XL", "5XL"]],
      str([x.get("sizes") for x in sini]))
ssel = E("pdf_real_sin_seleccion")
check("sin tallas seleccionadas se envía la talla propia sin filtrar", [x.get("sizes") for x in ssel][3:7] == [["S", "M", "L"], ["XL", "2XL", "3XL", "4XL", "5XL"], ["S", "M", "L"], ["XL", "2XL", "3XL", "4XL", "5XL"]])
pn = E("numerico")
check("tallas numéricas: el payload lleva las globales (40..64) y cada pieza las SUYAS (las mangas 40-44-48 y 52-56-60-64), sin números en nombre ni archivo",
      (payloads.get("numerico") or {}).get("sizes") == ALL_NUM and [x.get("sizes") for x in pn] == [ALL_NUM, ALL_NUM, ["40", "44", "48"], ["52", "56", "60", "64"]]
      and [x["placement"] for x in pn] == ["Back piece", "Front piece", "Left sleeve", "Left sleeve"]
      and not [x for x in pn if re.search(r"(?<![A-Za-z0-9])(?:40|44|48|52|56|60|64)(?![A-Za-z0-9])", x["file"].replace(STYLE, ""))],
      str([(x["placement"], x.get("sizes")) for x in pn]))
pnp = E("numerico_seleccion_parcial")
check("numéricas: si solo se marcan 44, 48 y 52, la talla propia se limita a lo marcado (piezas de 7 -> 44,48,52; manga 40-44-48 -> 44,48; manga 52..64 -> 52)",
      [x.get("sizes") for x in pnp] == [["44", "48", "52"], ["44", "48", "52"], ["44", "48"], ["52"]], str([x.get("sizes") for x in pnp]))
pns = E("numerico_sin_interseccion")
check("numéricas: si lo marcado (solo 40) no toca la talla propia de una pieza (manga 52..64), se conserva la propia",
      [x.get("sizes") for x in pns] == [["40"], ["40"], ["40"], ["52", "56", "60", "64"]], str([x.get("sizes") for x in pns]))
pl = E("cuellos_por_talla")
check("cuellos por talla: 3 piezas numeradas, placement y archivo SIN talla, cada una con SUS tallas",
      [x.get("sizes") for x in pl] == [["S", "M"], ["L", "XL"], ["2XL", "3XL"], []] and [x["placement"] for x in pl][:3] == ["Collar 1", "Collar 2", "Collar 3"]
      and not [x for x in pl if SIZE_IN_NAME.search(x["placement"]) or SIZE_IN_NAME.search(x["file"].replace(STYLE, ""))], str([(x["placement"], x.get("sizes")) for x in pl]))
pl2 = E("hombros_pareja")
check("hombros: 'Shoulder Left' / 'Shoulder Right', archivos distintos y sin tallas inventadas",
      [x["placement"] for x in pl2][:2] == ["Shoulder Left", "Shoulder Right"] and [x["file"] for x in pl2][:2] == [f"{STYLE}_Shoulder_Left.png", f"{STYLE}_Shoulder_Right.png"] and all(x.get("sizes") == [] for x in pl2))
pl3 = E("cuello_doble_con_talla")
check("cuello doble con talla: 'Left collar' / 'Right collar' (sin talla en el nombre), ambos con [S,M]",
      [(x["placement"], x.get("sizes")) for x in pl3][:2] == [("Left collar", ["S", "M"]), ("Right collar", ["S", "M"])], str([(x["placement"], x.get("sizes")) for x in pl3]))
pl4 = E("renombrada_a_mano")
check("si el usuario renombra una pieza a mano, la talla sigue viajando", [(x["placement"], x.get("sizes")) for x in pl4][1] == ("Cuello grande", ["L", "XL"]))

# ---- 3. Costos (jsdom): B = tallas FIJAS enviadas a mano (prueba solo a Costos); C = payload real del PDF real; D = con selección parcial
print("\n== B/C/D. Costos recibe las tallas por pieza: tarjeta, Excel (.xlsx) y portapapeles (TSV)")
base_png = io.BytesIO()
Image.new("RGBA", (300, 200), (200, 30, 30, 255)).save(base_png, "PNG", dpi=(300, 300))
png_b64 = base64.b64encode(base_png.getvalue()).decode()
J = lambda sz: "-".join(sz) if sz else "-".join(ALL8)           # SIZE = tallas unidas con '-'; sin tallas propias, la lista global


def spec_de(nombre, piezas, glob):
    seen, ps = {}, []
    for i, (pl_, sz) in enumerate(piezas):
        base = re.sub(r"[ ()/]+", "_", pl_)
        seen[base] = seen.get(base, 0) + 1
        ps.append({"id": f"p{i + 1:02d}", "placement": pl_, "fileName": f"{STYLE}_{base}{'' if seen[base] == 1 else '_' + str(seen[base])}.png",
                   "url": f"/api/piece/{nombre}/p{i + 1:02d}.png", "pngB64": png_b64, "width": 300, "height": 200, "sizes": sz})
    return {"mode": "extractor", "name": nombre, "globalSizes": glob, "pieces": ps}


FIJAS = [("Left sleeve", ["S", "M", "L"]), ("Left sleeve", ["XL", "2XL", "3XL", "4XL", "5XL"]), ("Right sleeve", ["S", "M", "L"]), ("Front piece", [])]
real_pc = [(x["placement"], x.get("sizes", [])) for x in pr]
parc_pc = [(x["placement"], x.get("sizes", [])) for x in parcial]
num_pc = [(x["placement"], x.get("sizes", [])) for x in pn]
specs = [spec_de("fijo", FIJAS, ALL8), spec_de("real", real_pc, ALL8), spec_de("parcial", parc_pc, ALL8[:6]), spec_de("numerico", num_pc, ALL_NUM)]
esperadas = {"fijo": [J(s) for _, s in FIJAS], "real": [J(s) for _, s in real_pc], "parcial": [J(s) for _, s in parc_pc], "numerico": [J(s) for _, s in num_pc]}
(WORK / "specs.json").write_text(json.dumps({"specs": specs, "efectos": {}}), encoding="utf-8")
(WORK / "costos.html").write_text(m.app.test_client().get("/costos").get_data(as_text=True), encoding="utf-8")
r = subprocess.run(["node", str(HERE / "costos_dpi.js"), str(WORK / "costos.html"), str(WORK / "specs.json"), str(WORK / "out.json"), str(WORK / "salida.xlsx")],
                   capture_output=True, text=True, cwd=str(HERE), timeout=300)
print(r.stdout.strip() or r.stderr.strip()[-400:])
data = json.loads((WORK / "out.json").read_text(encoding="utf-8")) if (WORK / "out.json").exists() else {}
cards, excelA, tsv, md = data.get("cards", []), data.get("excelA", []), data.get("tsv", []), data.get("metadatos", [])
total = len(FIJAS) + len(real_pc) + len(parc_pc) + len(num_pc)
check(f"Costos procesó las {total} piezas (tarjetas == metadatos == filas Excel == filas TSV), incluidas las de nombre repetido",
      len(cards) == len(excelA) == len(tsv) == len(md) == total, f"{len(cards)}/{len(md)}/{len(excelA)}/{len(tsv)} de {total}")
if len(md) == total:
    a = 0
    for nombre, etiqueta in (("fijo", "B (tallas enviadas a mano)"), ("real", "C (payload del PDF real)"), ("parcial", "D (PDF real con tallas 4XL y 5XL desmarcadas)"),
                             ("numerico", "E (tallas numéricas 40..64)")):
        n = len(esperadas[nombre]); sl = slice(a, a + n); a += n
        check(f"{etiqueta}: la insignia de tallas de cada tarjeta es la de SU pieza", [c.get("tallas") for c in cards[sl]] == esperadas[nombre], str([c.get("tallas") for c in cards[sl]][:5]))
        check(f"{etiqueta}: Excel columna A (SIZE) = tallas de cada pieza", [(x or {}).get("texto") for x in excelA[sl]] == esperadas[nombre], str([(x or {}).get("texto") for x in excelA[sl]][:5]))
        check(f"{etiqueta}: TSV (portapapeles) columna A (SIZE) = tallas de cada pieza", [t[0] for t in tsv[sl]] == esperadas[nombre])
    check("pantalla == Excel == TSV en las filas (metadatos.tallas = Excel A = TSV A)", [x.get("tallas") for x in md] == [(x or {}).get("texto") for x in excelA] == [t[0] for t in tsv])
    check("las dos mangas 'Left sleeve' del PDF real son filas distintas que solo se distinguen por su SIZE (S-M-L y XL-2XL-3XL-4XL-5XL)",
          [x.get("placement") for x in md[4:13]][3:5] == ["Left sleeve", "Left sleeve"] and [(x or {}).get("texto") for x in excelA[4:13]][3:5] == ["S-M-L", "XL-2XL-3XL-4XL-5XL"],
          str([(x.get("placement"), (e or {}).get("texto")) for x, e in zip(md[4:13], excelA[4:13])][3:5]))
    try:
        import openpyxl
        ws = openpyxl.load_workbook(WORK / "salida.xlsx", data_only=True).worksheets[0]
        got = [ws[f"A{5 + i}"].value for i in range(total)]
        check("openpyxl lee en el .xlsx las mismas tallas por fila", got == esperadas["fijo"] + esperadas["real"] + esperadas["parcial"] + esperadas["numerico"], str(got[:4]))
    except ImportError:
        print("OMITIDA  lectura independiente con openpyxl (no instalado)")
check("E: Excel/TSV con tallas numéricas: 'S' = 40-44-48-52-56-60-64 y las mangas 40-44-48 / 52-56-60-64",
      esperadas["numerico"] == ["40-44-48-52-56-60-64", "40-44-48-52-56-60-64", "40-44-48", "52-56-60-64"], str(esperadas["numerico"]))
tg = data.get("tallasGrid") or {}
LET9 = ["XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL", "5XL"]
ini, tod, nin = ({x["t"]: x["c"] for x in tg.get(k, [])} for k in ("inicial", "todas", "ninguna"))
check("Costos muestra en su cuadrícula las tallas numéricas recibidas (40..64) junto a las de letras, marcadas las numéricas y sin marcar las letras",
      list(ini) == LET9 + ALL_NUM and all(ini[t] for t in ALL_NUM) and not any(ini[t] for t in LET9), str(list(ini)[:12]))
check("el botón 'todas las tallas' de Costos selecciona también las numéricas, y pulsarlo otra vez las deselecciona todas (letras y números)",
      all(tod.values()) and len(tod) == 16 and not any(nin.values()) and len(nin) == 16, f"todas={sum(tod.values())}/{len(tod)} ninguna={sum(nin.values())}/{len(nin)}")
check("la página de Costos no produjo errores de JavaScript", not data.get("errors"), "; ".join(data.get("errors", [])[:2]))

# ---- 4. la página REAL del extractor: etiqueta 'Tallas: ...' en cada tarjeta (jsdom)
print("\n== E. Tarjetas del extractor: la talla se ve en una etiqueta aparte, no en el nombre")
(WORK / "extractor.html").write_text(m.app.test_client().get("/").get_data(as_text=True), encoding="utf-8")
(WORK / "tarj_in.json").write_text(json.dumps({"style": "530926F_24", "escenarios": [{"nombre": "pdf_real", "pieces": analisis["pdf_real"]},
                                                                                       {"nombre": "numerico", "pieces": analisis["numerico"], "sizesDetected": ALL_NUM},
                                                                                       {"nombre": "hombros_sin_tallas", "pieces": analisis["hombros_pareja"]}]}), encoding="utf-8")
r = subprocess.run(["node", str(HERE / "uitest_tarjetas.js"), str(WORK / "extractor.html"), str(WORK / "tarj_in.json"), str(WORK / "tarj_out.json")],
                   capture_output=True, text=True, cwd=str(HERE), timeout=120)
print(r.stdout.strip() or r.stderr.strip()[-400:])
td = json.loads((WORK / "tarj_out.json").read_text(encoding="utf-8")) if (WORK / "tarj_out.json").exists() else {"res": [], "errors": ["sin salida"]}
tarj = {x["nombre"]: x["cards"] for x in td.get("res", [])}
real = tarj.get("pdf_real", [])
check("PDF real: cada tarjeta muestra su talla en la etiqueta (S-5XL, S-L, XL-5XL...) y sus títulos NO llevan talla",
      [c["tallas"] for c in real] == ["Tallas: S-5XL"] * 3 + ["Tallas: S-L", "Tallas: XL-5XL", "Tallas: S-L", "Tallas: XL-5XL", "Tallas: S-5XL", "Tallas: S-5XL"]
      and [c["titulo"] for c in real] == ["Nameplate piece", "Left yoke piece", "Right yoke piece", "Left sleeve", "Left sleeve", "Right sleeve", "Right sleeve", "Back piece", "Front piece"],
      str([(c["titulo"], c["tallas"]) for c in real][3:5]))
check("las dos mangas 'Left sleeve' se distinguen en pantalla por su etiqueta (S-L / XL-5XL) y sus archivos por el sufijo _2",
      [(c["titulo"], c["tallas"], c["archivo"]) for c in real][3:5] == [("Left sleeve", "Tallas: S-L", "530926F_24_Left_sleeve.png"), ("Left sleeve", "Tallas: XL-5XL", "530926F_24_Left_sleeve_2.png")])
check("la etiqueta es visible y su ayuda lista las tallas (S, M, L / XL, 2XL, 3XL, 4XL, 5XL)",
      all(c["oculta"] is False for c in real) and "S, M, L" in (real[3]["tooltip"] or "") and "XL, 2XL, 3XL, 4XL, 5XL" in (real[4]["tooltip"] or ""), str(real[3:5] and [real[3]["tooltip"], real[4]["tooltip"]]))
hs = tarj.get("hombros_sin_tallas", [])
check("una pieza sin talla propia no muestra etiqueta (queda oculta) y el resto de la tarjeta no cambia",
      hs and all(c["oculta"] is True for c in hs if c["codigo"] != "Código: FRONT") and [c["titulo"] for c in hs][:2] == ["Shoulder Left", "Shoulder Right"], str([(c["titulo"], c["oculta"]) for c in hs]))
nm = tarj.get("numerico", [])
check("tarjetas con tallas numéricas: etiqueta 'Tallas: 40-44-48-52-56-60-64' y títulos sin números (Back piece, Front piece, Left sleeve ×2)",
      [c["tallas"] for c in nm] == ["Tallas: 40-44-48-52-56-60-64"] * 2 + ["Tallas: 40-44-48", "Tallas: 52-56-60-64"] and [c["titulo"] for c in nm] == ["Back piece", "Front piece", "Left sleeve", "Left sleeve"],
      str([(c["titulo"], c["tallas"]) for c in nm]))
chips = next((x.get("chips") for x in td.get("res", []) if x["nombre"] == "numerico"), None) or []
check("el selector de tallas del extractor muestra las 9 de letras (sin marcar) y las 7 numéricas detectadas (marcadas), en ese orden",
      [c["t"] for c in chips] == LET9 + ALL_NUM and all(c["sel"] for c in chips if c["t"] in ALL_NUM) and not any(c["sel"] for c in chips if c["t"] in LET9),
      str([(c["t"], c["sel"]) for c in chips][8:12]))
solo_jsdom = [e for e in td.get("errors", []) if "tailwind is not defined" not in e and "HTMLCanvasElement" not in e]
check("la página del extractor no produjo errores de JavaScript propios (solo las 2 limitaciones conocidas de jsdom: Tailwind del CDN y canvas)", not solo_jsdom, "; ".join(solo_jsdom[:2]))

fails = [n for n, ok in results if not ok]
(OUT / f"results_envio_tallas_{label}.json").write_text(json.dumps({"label": label, "pass": len(results) - len(fails), "fail": len(fails), "omitidas": 0,
                                                                   "fallidas": fails, "omitidas_detalle": []}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\nRESUMEN ENVIO-TALLAS [{label}]: {len(results) - len(fails)}/{len(results)} pruebas PASS, {len(fails)} FAIL")
sys.exit(1 if fails else 0)
