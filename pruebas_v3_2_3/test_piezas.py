"""Pruebas del reconocimiento de piezas dobles (Left/Right) y de piezas por talla (S-M, L-XL, 2-3XL...).

Uso: python test_piezas.py <programa.py> <etiqueta> [directorio_salida]
Escribe results_piezas_<etiqueta>.json en el directorio de salida. Código de salida: 0 sin FAIL, 1 con algún FAIL.
No necesita Node: usa PDFs sintéticos (build_pdfs.py), el analizador, la API Flask y PyMuPDF.
"""
import sys, io, os, json, re, tempfile, zipfile, logging, warnings, importlib.util
from pathlib import Path
warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_pdfs as B

try:
    import pymupdf as fitz
except ImportError:
    import fitz

module_path, label = Path(sys.argv[1]).resolve(), sys.argv[2]
OUT = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else Path(tempfile.gettempdir()) / "tegra_tests"
OUT.mkdir(parents=True, exist_ok=True)

spec = importlib.util.spec_from_file_location("piezas_mod_" + label, str(module_path))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
logging.disable(logging.CRITICAL)

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS  " if cond else "FAIL  ") + name + (f"   [{detail}]" if detail else ""))


def analyze(data):
    pub, internal = m.analyze_pdf(data, "TEST-0002-XYZ.pdf")
    pcs = [p for p in pub["pieces"] if p["code"] != "FRONT"]            # FRONT es la pieza de relleno de cada hoja
    warns = [w for w in pub["warnings"] if "etiqueta para" in w]
    return pub, internal, pcs, warns


def brief(pcs):
    return [(p["code"], p["default_name"], f"{p['part']}/{p['parts']}") for p in pcs]


# ======================================================================== 1. lector de tallas
NUEVAS = ("parse_size_spec", "parse_pure_size_line", "size_label", "plan_label")
FALTAN = [n for n in NUEVAS if not hasattr(m, n)]
print("== 1. Lector de tallas (parse_size_spec)")
if FALTAN:
    check("el programa incluye el lector de tallas y la planificación de piezas dobles/por talla", False, "faltan: " + ", ".join(FALTAN))
SI = lambda t, lone=True: ((m.parse_size_spec(t, lone) or {}).get("sizes") if not FALTAN else "SIN LECTOR")
tabla = [
    ("S-M", ["S", "M"]), ("L-XL", ["L", "XL"]), ("2-3XL", ["2XL", "3XL"]), ("2XL-3XL", ["2XL", "3XL"]), ("XXL-3XL", ["2XL", "3XL"]),
    ("XS/S", ["XS", "S"]), ("S,M,L", ["S", "M", "L"]), ("S TO XL", ["S", "M", "L", "XL"]), ("COLLAR S-M", ["S", "M"]),
    ("COLLAR (L-XL)", ["L", "XL"]), ("COLLAR_2XL-3XL", ["2XL", "3XL"]), ("COLLAR 2/3XL", ["2XL", "3XL"]), ("COLLAR Size: S-M", ["S", "M"]),
    ("COLLAR Size: L", ["L"]), ("COLLAR TALLA M L", ["M", "L"]), ("COLLAR XL", ["XL"]), ("COLLAR 4XL", ["4XL"]), ("NK BND 2-3X", ["2XL", "3XL"]),
    ("COLLAR S-M 14L x 3W", ["S", "M"]), ("XS-XL", ["XS", "S", "M", "L", "XL"]),
]
bad = [(t, SI(t), e) for t, e in tabla if SI(t) != e]
check(f"se leen {len(tabla)} formas de escribir tallas (S-M, L-XL, 2-3XL, XXL-3XL, XS/S, Size: L, TALLA M L...)", not bad, str(bad[:3]))
no_talla = ["L SLV", "R SLV", "BK L", "FRONT", "SLV LEFT", "SLV RIGTH", "COLLAR", "YK 2_L X 3_W", "BK SLOPER_1", "NAMEPLATE INTERLINING",
            "FT SD PNL", "SHDL PL", "SM", "COLLAR SM", "4.5_L X 1.5_W", "BASE-LAYER", "S", "M", "L", "67NM-BBGH-81F", "PIECE 2-3", "L-R", "SIDE"]
bad = [(t, SI(t)) for t in no_talla if SI(t)]
check(f"{len(no_talla)} textos que NO son tallas se rechazan (una L/S/M suelta, L SLV, YK 2_L X 3_W, PIECE 2-3...)", not bad, str(bad[:3]))
_lab = (lambda x: m.size_label(x)) if "size_label" not in FALTAN else (lambda x: "SIN size_label")
check("2-3XL se lee como 2XL y 3XL (la X compartida) y se etiqueta 2XL-3XL", _lab(SI("2-3XL") or []) == "2XL-3XL")
check("etiquetas compactas: S-M, L-XL, 2XL-3XL, S-XL y no contiguas S-M+2XL",
      [_lab(x) for x in (["S", "M"], ["L", "XL"], ["2XL", "3XL"], ["S", "M", "L", "XL"], ["S", "M", "2XL"])] == ["S-M", "L-XL", "2XL-3XL", "S-XL", "S-M+2XL"])
puras = {"S-M": ["S", "M"], "(L-XL)": ["L", "XL"], "[2-3XL]": ["2XL", "3XL"], "Size: 2-3XL": ["2XL", "3XL"], "TALLA: S/M": ["S", "M"],
         "COLLAR S-M": None, "S-M, L-XL": None, "S": None, "14 cm": None}
_pura = (lambda t: m.parse_pure_size_line(t)) if "parse_pure_size_line" not in FALTAN else (lambda t: "SIN LECTOR")
bad = [(t, _pura(t)) for t, e in puras.items() if _pura(t) != e]
check("una línea 'pura' de talla se acepta solo si no trae nada más (rechaza 'COLLAR S-M', leyendas 'S-M, L-XL' y una S suelta)", not bad, str(bad[:3]))
tx = m.detect_sizes([], ["COLLAR S-M", "COLLAR L-XL", "COLLAR 2-3XL"])
check("las tallas globales del PDF ahora incluyen 2XL y 3XL cuando solo se escriben como 2-3XL", tx[0] == ["S", "M", "L", "XL", "2XL", "3XL"], str(tx))

# ======================================================================== 2. parejas Left / Right
print("\n== 2. Piezas dobles sin lado -> Left / Right")
pub, internal, pcs, warns = analyze(B.pair_one_label("SHDL PL"))
check("una etiqueta SHDL PL con 2 piezas -> 'Shoulder Left' y 'Shoulder Right' (izquierda de la hoja = Left)",
      [(p["code"], p["default_name"]) for p in pcs] == [("L SHDL PL", "Shoulder Left"), ("R SHDL PL", "Shoulder Right")] and pcs[0]["rect"][0] < pcs[1]["rect"][0], str(brief(pcs)))
check("ya no se numeran (1/2, 2/2) ni sale el aviso 'una etiqueta para 2 piezas'", all(p["parts"] == 1 for p in pcs) and not warns, str(warns))
check("las piezas resueltas llevan variant=side y ninguna talla inventada", all(p.get("variant") == "side" and "sizes" not in p for p in pcs))
pub, internal, pcs, warns = analyze(B.pair_one_label("SHOULDER"))
check("SHOULDER (no está en el diccionario) -> 'Shoulder Left' / 'Shoulder Right'", [p["default_name"] for p in pcs] == ["Shoulder Left", "Shoulder Right"] and not warns, str(brief(pcs)))
pub, internal, pcs, warns = analyze(B.pair_one_label("SLV"))
check("SLV con 2 piezas -> 'L SLV' / 'R SLV' = 'Left sleeve' / 'Right sleeve' (como ya hacía con dos etiquetas)",
      [(p["code"], p["default_name"]) for p in pcs] == [("L SLV", "Left sleeve"), ("R SLV", "Right sleeve")] and not warns, str(brief(pcs)))
pub, internal, pcs, warns = analyze(B.pair_one_label("FT SD PNL"))
check("cualquier pieza doble parecida (FT SD PNL) -> Left/Right con el nombre del diccionario",
      [p["default_name"] for p in pcs] == ["Left front side panel", "Right front side panel"] and not warns, str(brief(pcs)))
pub, internal, pcs, warns = analyze(B.pair_two_labels("SHOULDER"))
check("dos etiquetas SHOULDER (una por pieza) -> Left/Right por posición", [p["default_name"] for p in pcs] == ["Shoulder Left", "Shoulder Right"] and pcs[0]["rect"][0] < pcs[1]["rect"][0], str(brief(pcs)))
pub, internal, pcs, warns = analyze(B.pair_two_labels("SLV"))
check("dos etiquetas SLV siguen dando 'Left sleeve' / 'Right sleeve' (comportamiento de siempre)", [(p["code"], p["default_name"]) for p in pcs] == [("L SLV", "Left sleeve"), ("R SLV", "Right sleeve")], str(brief(pcs)))
pub, internal, pcs, warns = analyze(B.pair_two_labels("SLEEVE"))
check("dos etiquetas SLEEVE (otro nombre de la misma familia) -> Left/Right", [p["code"] for p in pcs] == ["L SLEEVE", "R SLEEVE"], str(brief(pcs)))

print("\n== 3. Casos en los que NO se asigna Left/Right (se conserva la numeración y se avisa)")
pub, internal, pcs, warns = analyze(B.stacked_overlap_pair("SLV"))
check("dos piezas apiladas (una sobre otra) -> SLV (1/2), (2/2) + aviso 'no están una al lado de la otra'",
      [(p["part"], p["parts"]) for p in pcs] == [(1, 2), (2, 2)] and len(warns) == 1 and "una al lado de la otra" in warns[0], str(warns))
pub, internal, pcs, warns = analyze(B.pair_dissimilar("PANEL"))
check("pieza genérica doble de tamaño muy distinto (PANEL) -> numeradas + aviso 'no tienen tamaño parecido'",
      [(p["part"], p["parts"]) for p in pcs] == [(1, 2), (2, 2)] and len(warns) == 1 and "tamaño parecido" in warns[0], str(warns))
pub, internal, pcs, warns = analyze(B.pair_dissimilar("SHOULDER"))
check("pero en hombros/mangas no se exige tamaño parecido -> Left/Right", [p["default_name"] for p in pcs] == ["Shoulder Left", "Shoulder Right"] and not warns, str(brief(pcs)))
pub, internal, pcs, warns = analyze(B.pair_one_label("SLV LEFT"))
check("si el nombre YA indica el lado (SLV LEFT) con 2 piezas no se inventa otro: numeradas + aviso", [(p["code"], p["part"], p["parts"]) for p in pcs] == [("SLV LEFT", 1, 2), ("SLV LEFT", 2, 2)]
      and len(warns) == 1 and "ya indica el lado" in warns[0], str(warns))
pub, internal, pcs, warns = analyze(B.pair_two_labels("FT"))
check("dos etiquetas iguales de una pieza que no es pareja (FT) no se tocan", [p["code"] for p in pcs] == ["FT", "FT"] and all(p["parts"] == 1 for p in pcs))
pub, internal, pcs, warns = analyze(B.pair_two_labels("SHOULDER", label2="SLV"))
check("dos etiquetas de familias distintas (SHOULDER y SLV) no se emparejan entre sí", [p["code"] for p in pcs] == ["SHOULDER", "SLV"], str(brief(pcs)))
pub, internal, pcs, warns = analyze(B.named_pieces(["L SLV", "R SLV", "BK L", "YK 2_L X 3_W", "NK BND"]))
check("una L o una R sueltas son LADO, no talla: ninguna recibe tallas y sus nombres no cambian",
      [p["code"] for p in pcs] == ["L SLV", "R SLV", "BK L", "YK", "NK BND"] and not any("sizes" in p for p in pcs), str([p["code"] for p in pcs]))

# ======================================================================== 4. piezas por talla (las tallas van a 'sizes', NO al nombre)
print("\n== 4. Piezas por talla: las tallas se leen pero NO forman parte del nombre (van a la columna SIZE)")
def cs(pcs):
    return [(p["code"], p.get("sizes")) for p in pcs]
pub, internal, pcs, warns = analyze(B.named_pieces(["COLLAR S-M", "COLLAR L-XL", "COLLAR 2-3XL"]))
check("tallas escritas en el nombre (COLLAR S-M / L-XL / 2-3XL): el nombre queda COLLAR y cada pieza guarda SUS tallas",
      cs(pcs) == [("COLLAR", ["S", "M"]), ("COLLAR", ["L", "XL"]), ("COLLAR", ["2XL", "3XL"])], str(cs(pcs)))
check("su nombre en inglés NO lleva la talla ('Collar') ni se numeran; la talla compacta queda en sizes_label",
      [p["default_name"] for p in pcs] == ["Collar"] * 3 and all(p["parts"] == 1 for p in pcs) and [p.get("sizes_label") for p in pcs] == ["S-M", "L-XL", "2XL-3XL"],
      str([(p["default_name"], p.get("sizes_label")) for p in pcs]))
formas = ["COLLAR S-M", "COLLAR (L-XL)", "COLLAR_2XL-3XL", "COLLAR 2/3XL", "COLLAR Size: S-M", "COLLAR XXL-3XL", "COLLAR XS/S", "COLLAR XL", "COLLAR 4XL", "NK BND 2-3X"]
pub, internal, pcs, warns = analyze(B.named_pieces(formas))
esperado = [("COLLAR", ["S", "M"]), ("COLLAR", ["L", "XL"]), ("COLLAR", ["2XL", "3XL"]), ("COLLAR", ["2XL", "3XL"]), ("COLLAR", ["S", "M"]),
            ("COLLAR", ["2XL", "3XL"]), ("COLLAR", ["XS", "S"]), ("COLLAR", ["XL"]), ("COLLAR", ["4XL"]), ("NK BND", ["2XL", "3XL"])]
check("10 formas distintas de escribir la talla en la etiqueta se normalizan igual y NO quedan en el nombre", cs(pcs) == esperado, str(cs(pcs)[:4]))
pub, internal, pcs, warns = analyze(B.named_pieces(["COLLAR S-M 14L x 3W", "COLLAR L-XL 14L x 3W"], dim_lines=True))
check("también en las etiquetas de solo medidas (sin 'Piece Name:'): 'COLLAR S-M 14L x 3W' -> COLLAR + [S,M]", cs(pcs) == [("COLLAR", ["S", "M"]), ("COLLAR", ["L", "XL"])], str(cs(pcs)))
pub, internal, pcs, warns = analyze(B.named_pieces(["SLEEVE S-M", "FT 2-3XL", "YK L-XL", "BK XS/S"]))
check("cualquier pieza puede traer sus tallas (SLEEVE, FT, YK, BK) y su nombre no cambia",
      cs(pcs) == [("SLEEVE", ["S", "M"]), ("FT", ["2XL", "3XL"]), ("YK", ["L", "XL"]), ("BK", ["XS", "S"])], str(cs(pcs)))
pub, internal, pcs, warns = analyze(B.collars_one_label(["S-M", "L-XL", "2-3XL"]))
check("UNA etiqueta COLLAR con 3 piezas y su talla junto a cada una -> 3 piezas numeradas (1/3, 2/3, 3/3) con SUS tallas y sin aviso",
      [(p["code"], p["part"], p["parts"], p.get("sizes")) for p in pcs] == [("COLLAR", 1, 3, ["S", "M"]), ("COLLAR", 2, 3, ["L", "XL"]), ("COLLAR", 3, 3, ["2XL", "3XL"])] and not warns,
      str(cs(pcs)) + " " + str(warns))
check("cada talla se asignó a la pieza que tiene cerca (por posición, no por orden de lectura)", [p["rect"][0] for p in pcs] == sorted(p["rect"][0] for p in pcs))
doc = fitz.open(stream=B.collars_one_label(["S-M", "L-XL", "2-3XL"]), filetype="pdf")
pg0 = doc[0]
pub2, int2, _, _ = analyze(B.collars_one_label(["S-M", "L-XL", "2-3XL"]))
rem = [fitz.Rect(r) for r in int2["remove"][0]]
hits = {t: pg0.search_for(t) for t in ("S-M", "L-XL", "2-3XL")}
cubiertos = all(any(rr.contains(h) or rr.intersects(h) for rr in rem) for rects in hits.values() for h in rects[:1])
check("el texto de talla usado se borra del render (igual que las etiquetas)", cubiertos and all(hits.values()), str({k: len(v) for k, v in hits.items()}))
doc.close()
pub, internal, pcs, warns = analyze(B.collars_one_label(["S-M", "L-XL", None]))
check("si a alguna pieza le falta su talla NO se adivina: numeradas + aviso", [(p["part"], p["parts"]) for p in pcs] == [(1, 3), (2, 3), (3, 3)] and len(warns) == 1 and "distinguir por talla" in warns[0] and not any("sizes" in p for p in pcs), str(warns))
pub, internal, pcs, warns = analyze(B.collars_one_label(["S-M", "S-M", "L-XL"]))
check("si dos piezas dicen la misma talla tampoco se adivina: numeradas + aviso", [(p["part"], p["parts"]) for p in pcs] == [(1, 3), (2, 3), (3, 3)] and len(warns) == 1, str(warns))
pub, internal, pcs, warns = analyze(B.collars_one_label([None, None, None]))
check("sin textos de talla (3 cuellos iguales) se numera y se avisa, como antes", [(p["code"], p["part"], p["parts"]) for p in pcs] == [("COLLAR", 1, 3), ("COLLAR", 2, 3), ("COLLAR", 3, 3)] and len(warns) == 1, str(warns))
pub, internal, pcs, warns = analyze(B.label_with_size_below())
check("talla en una línea del mismo bloque de la etiqueta (COLLAR / S-M) -> COLLAR con sizes [S,M]", cs(pcs) == [("COLLAR", ["S", "M"])], str(cs(pcs)))
pub, internal, pcs, warns = analyze(B.two_collars_one_label_with_size("COLLAR S-M"))
check("pieza doble CON talla (COLLAR S-M, 2 piezas) -> 'Left collar' / 'Right collar' (sin talla en el nombre) y ambas con [S,M]",
      [(p["code"], p["default_name"], p.get("sizes")) for p in pcs] == [("L COLLAR", "Left collar", ["S", "M"]), ("R COLLAR", "Right collar", ["S", "M"])], str(brief(pcs)))
SIZE_IN_NAME = re.compile(r"(?<![A-Za-z0-9])(?:[2-5]XL|XL|XS|S-M|L-XL|S-L|\d-\dXL|S-5XL|XL-5XL)(?![A-Za-z0-9])")
todas = []
for pdf in (B.named_pieces(["COLLAR S-M", "COLLAR L-XL", "COLLAR 2-3XL"]), B.collars_one_label(["S-M", "L-XL", "2-3XL"]), B.label_with_size_below(), B.two_collars_one_label_with_size("COLLAR S-M"),
            B.named_pieces(["SLEEVE S-M", "FT 2-3XL"]), B.named_pieces(formas)):
    todas += analyze(pdf)[2]
check(f"en {len(todas)} piezas con tallas detectadas ninguna talla aparece en 'code' ni en 'default_name'", todas and not [p for p in todas if SIZE_IN_NAME.search(p["code"]) or SIZE_IN_NAME.search(p["default_name"])],
      str([p["code"] for p in todas if SIZE_IN_NAME.search(p["code"] + " " + p["default_name"])][:3]))

# ======================================================================== 5. lógica pura (plan_label) y forma de los datos
print("\n== 5. Lógica de decisión y forma de los datos")
R = fitz.Rect
a, b = R(0, 0, 100, 80), R(110, 0, 210, 80)
if "plan_label" in FALTAN:
    check("plan_label existe (lógica de decisión de lados y tallas)", False, "no existe en esta versión")
    m.plan_label = lambda *a, **k: ([{"side": "?", "sizes": "?", "part": 0, "parts": 0}] * 2, "SIN plan_label", [])
sp, why, _ = m.plan_label("PANEL", [], None, None, [a, b], [], [], set())
check("plan_label: pareja lado a lado y parecida -> L y R", [s["side"] for s in sp] == ["L", "R"] and not why)
sp, why, _ = m.plan_label("PANEL", [], None, None, [b, a], [], [], set())
check("plan_label: el orden de las regiones no importa, la izquierda siempre es L", [s["side"] for s in sp] == ["R", "L"])
sp, why, _ = m.plan_label("PANEL", [], None, None, [R(0, 0, 100, 80), R(0, 90, 100, 170)], [], [], set())
check("plan_label: apiladas -> numeradas", [s["side"] for s in sp] == [None, None] and "al lado" in why and [s["part"] for s in sp] == [1, 2])
sp, why, _ = m.plan_label("PANEL", [], None, None, [R(0, 0, 100, 80), R(110, 0, 130, 80)], [], [], set())
check("plan_label: tamaños muy distintos y nombre genérico -> numeradas", [s["side"] for s in sp] == [None, None] and "parecido" in why)
sp, why, _ = m.plan_label("SLV", [], None, None, [R(0, 0, 100, 80), R(110, 0, 130, 80)], [], [], set())
check("plan_label: familia en pareja ignora el tamaño -> L y R", [s["side"] for s in sp] == ["L", "R"])
sp, why, _ = m.plan_label("SLV", [], None, "L", [R(0, 0, 100, 80)], [], [], set())
check("plan_label: una sola región conserva el lado ya asignado por pareja de etiquetas", sp == [{"side": "L", "sizes": [], "part": 1, "parts": 1}])
sp, why, _ = m.plan_label("COLLAR", ["S", "M"], None, None, [a], [], [], set())
check("plan_label: una región con talla en el nombre la conserva", sp[0]["sizes"] == ["S", "M"] and sp[0]["side"] is None)
sp, why, _ = m.plan_label("COLLAR", [], ["L", "XL"], None, [a], [], [], set())
check("plan_label: una región con talla en una línea vecina la usa", sp[0]["sizes"] == ["L", "XL"])
base_keys = {"id", "page", "code", "default_name", "rect", "label", "part", "parts"}
garment = (HERE / "test_garment.pdf").read_bytes()
pubg, _ = m.analyze_pdf(garment, "TEST-0001-ABC.pdf")
check("una pieza sin lado ni talla conserva exactamente los campos de siempre (sin 'sizes' ni 'variant')", all(set(p) == base_keys for p in pubg["pieces"]))
j1 = json.dumps(m.analyze_pdf(B.collars_one_label(["S-M", "L-XL", "2-3XL"]), "x.pdf")[0], sort_keys=True, default=str)
j2 = json.dumps(m.analyze_pdf(B.collars_one_label(["S-M", "L-XL", "2-3XL"]), "x.pdf")[0], sort_keys=True, default=str)
check("el análisis es reproducible (mismo PDF, mismo resultado)", j1 == j2)

# ======================================================================== 6. API de extremo a extremo
print("\n== 6. API: subida, descarga y ZIP con los nombres nuevos")
client = m.app.test_client()
m.SESSIONS.clear()
up = client.post("/api/upload", data={"file": (io.BytesIO(B.pair_one_label("SHDL PL")), "TEST-0002-XYZ.pdf")}, content_type="multipart/form-data")
uj = up.get_json(silent=True) or {}
pj = [p for p in uj.get("pieces", []) if p["code"] != "FRONT"]
check("/api/upload devuelve las piezas ya resueltas (Left/Right) sin avisos de 'una etiqueta para'",
      up.status_code == 200 and [p["default_name"] for p in pj] == ["Shoulder Left", "Shoulder Right"] and not [w for w in uj.get("warnings", []) if "etiqueta para" in w],
      f"status={up.status_code} {[p['default_name'] for p in pj]}")
did = uj.get("doc_id", "x")
z = client.get(f"/api/zip/{did}?dpi=150&mode=art")
names = sorted(zipfile.ZipFile(io.BytesIO(z.data)).namelist()) if z.status_code == 200 else []
check("el ZIP por defecto nombra cada mitad distinto (Shoulder_Left / Shoulder_Right), sin sufijos _2",
      "TEST-0002-XYZ_Shoulder_Left.png" in names and "TEST-0002-XYZ_Shoulder_Right.png" in names and not any(n.endswith("_2.png") for n in names), str(names))
check("las piezas se pueden renderizar y descargar por separado", all(client.get(f"/api/piece/{did}/{p['id']}.png?dpi=150").status_code == 200 for p in pj))
up = client.post("/api/upload", data={"file": (io.BytesIO(B.collars_one_label(["S-M", "L-XL", "2-3XL"])), "TEST-0002-XYZ.pdf")}, content_type="multipart/form-data")
uj = up.get_json(silent=True) or {}
pj = [p for p in uj.get("pieces", []) if p["code"] != "FRONT"]
check("/api/upload de los cuellos por talla: 3 piezas con 'sizes' y 'sizes_label', sin talla en el nombre",
      [(p["code"], p.get("sizes"), p.get("sizes_label")) for p in pj] == [("COLLAR", ["S", "M"], "S-M"), ("COLLAR", ["L", "XL"], "L-XL"), ("COLLAR", ["2XL", "3XL"], "2XL-3XL")], str(pj and [p["code"] for p in pj]))
z = client.get(f"/api/zip/{uj.get('doc_id', 'x')}?dpi=150&mode=art")
names = sorted(n for n in zipfile.ZipFile(io.BytesIO(z.data)).namelist() if "FRONT" not in n) if z.status_code == 200 else []
check("el ZIP por defecto nombra los 3 cuellos sin talla y sin que choquen (Collar, Collar_2, Collar_3)",
      names == ["TEST-0002-XYZ_Collar.png", "TEST-0002-XYZ_Collar_2.png", "TEST-0002-XYZ_Collar_3.png"], str(names))

# ======================================================================== 7. PDF REAL con tallas divididas
print("\n== 7. PDF real del usuario (67NM-BBGH-81F, tallas divididas): mangas S-L y XL-5XL")
REAL = HERE / "ejemplo_tallas_divididas_real.pdf"
if not REAL.exists():
    print("OMITIDA  PDF real no incluido en el paquete")
else:
    rdata = REAL.read_bytes()
    pubr, intr = m.analyze_pdf(rdata, REAL.name)
    pr = pubr["pieces"]
    esperadas_r = [("NAMEPLATE", "Nameplate piece", "S-5XL"), ("L YK", "Left yoke piece", "S-5XL"), ("R YK", "Right yoke piece", "S-5XL"),
                   ("SLV Left", "Left sleeve", "S-L"), ("SLV Left", "Left sleeve", "XL-5XL"), ("SLV Rigth", "Right sleeve", "S-L"),
                   ("SLV Rigth", "Right sleeve", "XL-5XL"), ("BK", "Back piece", "S-5XL"), ("FT", "Front piece", "S-5XL")]
    check("9 piezas con su nombre SIN talla y su talla aparte en sizes_label",
          [(p["code"], p["default_name"], p.get("sizes_label")) for p in pr] == esperadas_r, str([(p["code"], p.get("sizes_label")) for p in pr]))
    check("las mangas se reparten bien: la columna de la izquierda es S-L y la de la derecha XL-5XL (Left y Right)",
          [(p["code"], p.get("sizes_label")) for p in pr if p["code"].startswith("SLV") and p["rect"][0] < 6000] == [("SLV Left", "S-L"), ("SLV Rigth", "S-L")]
          and [(p["code"], p.get("sizes_label")) for p in pr if p["code"].startswith("SLV") and p["rect"][0] > 6000] == [("SLV Left", "XL-5XL"), ("SLV Rigth", "XL-5XL")])
    ALL8 = ["S", "M", "L", "XL", "2XL", "3XL", "4XL", "5XL"]
    check("S-L = [S,M,L] y XL-5XL = [XL,2XL,3XL,4XL,5XL]; el resto trae las 8 tallas",
          [p.get("sizes") for p in pr] == [ALL8, ALL8, ALL8, ["S", "M", "L"], ["XL", "2XL", "3XL", "4XL", "5XL"], ["S", "M", "L"], ["XL", "2XL", "3XL", "4XL", "5XL"], ALL8, ALL8])
    check("ninguna talla en 'code' ni en 'default_name' de las 9 piezas", not [p for p in pr if SIZE_IN_NAME.search(p["code"]) or SIZE_IN_NAME.search(p["default_name"])])
    check("YK (una etiqueta, 2 piezas) pasa a Left/Right sin el aviso 'una etiqueta para 2 piezas'", not [w for w in pubr["warnings"] if "etiqueta para" in w], str([w for w in pubr["warnings"] if "etiqueta" in w]))
    check("las tallas globales siguen saliendo de las capas del PDF (S..5XL), como antes", pubr["sizes"] == ALL8 and pubr.get("sizes_source") == "las capas del PDF", f"{pubr['sizes']} / {pubr.get('sizes_source')}")
    docr = fitz.open(stream=rdata, filetype="pdf")
    pgr = docr[0]
    remr = [fitz.Rect(r) for r in intr["remove"][0]]
    cub = {t: all(any(rr.intersects(h) for rr in remr) for h in pgr.search_for(t)) for t in ("S-L", "XL-5XL", "Size: S-5XL")}
    check("las líneas de talla de las etiquetas (S-L, XL-5XL, Size: S-5XL) se siguen borrando del render", all(cub.values()), str(cub))
    docr.close()
    mr = m.app.test_client()
    m.SESSIONS.clear()
    up = mr.post("/api/upload", data={"file": (io.BytesIO(rdata), REAL.name)}, content_type="multipart/form-data")
    uj = up.get_json(silent=True) or {}
    check("/api/upload del PDF real: 200 y 9 piezas", up.status_code == 200 and len(uj.get("pieces", [])) == 9, f"status={up.status_code}")
    zr = mr.get(f"/api/zip/{uj.get('doc_id', 'x')}?dpi=72&mode=art")
    nr = sorted(zipfile.ZipFile(io.BytesIO(zr.data)).namelist()) if zr.status_code == 200 else []
    check("el ZIP por defecto del PDF real tiene 9 archivos con nombres únicos (los repetidos llevan _2) y ninguna talla en el nombre",
          len(nr) == 9 and len(set(nr)) == 9 and not [n for n in nr if SIZE_IN_NAME.search(n.replace("67NM-BBGH-81F", ""))], str(nr))

# ======================================================================== 8. tallas NUMÉRICAS (Size: 40,44,48,52,56,60,64)
print("\n== 8. Tallas numéricas: 'Size: 40,44,48,52,56,60,64' (patrones que no usan S, M, L...)")
ALL_NUM = ["40", "44", "48", "52", "56", "60", "64"]
num_ok = {"Size: 40,44,48,52,56,60,64": ALL_NUM, "Size: 40, 44, 48": ["40", "44", "48"], "Size: 40/44/48": ["40", "44", "48"], "Size: 40 44 48": ["40", "44", "48"],
          "Sizes: 40;44": ["40", "44"], "Sizes: 40,44": ["40", "44"], "Talla: 40": ["40"], "Tallas: 40,44": ["40", "44"], "SZ: 40": ["40"], "Size 40,44": ["40", "44"],
          "BK 2_L X 3_W Size: 40,44,48": ["40", "44", "48"], "Size: 040,044": ["40", "44"]}
bad = [(t, SI(t, False), e) for t, e in num_ok.items() if SI(t, False) != e]
check(f"se leen {len(num_ok)} formas de escribir tallas numéricas (comas, espacios, barras, punto y coma, Sizes/Talla/SZ, dentro de una línea de medidas)", not bad, str(bad[:3]))
num_no = ["5.16 cm", "10.43 cm", "530926F_24", "BK 2_L X 3_W", "40,44,48", "Size: 12.5", "Size: 10 cm", "Size: 40-64", "Style Name: 530926F_24", "Size: 400,440", "YK 2_L X 3_W", "6.8 cm", "25.4 cm"]
bad = [(t, SI(t, False)) for t in num_no if SI(t, False)]
check(f"{len(num_no)} textos con números que NO son tallas se rechazan (medidas, decimales, estilos, números sin 'Size:', rangos 40-64)", not bad, str(bad[:3]))
plural = {"Sizes: S-M": ["S", "M"], "SIZES: 2-3XL": ["2XL", "3XL"], "Size:S-M": ["S", "M"], "Talla: M L": ["M", "L"]}
bad = [(t, SI(t, False), e) for t, e in plural.items() if SI(t, False) != e]
check("regresión: 'Sizes:' (plural) no se confunde con la talla S (la s de 'Sizes')", not bad and not SI("Sizes", False) and not SI("Sizeable", False), str(bad[:3]))
_ordn = (lambda x: m.order_sizes(x)) if hasattr(m, "order_sizes") else (lambda x: "SIN order_sizes")
check("orden de tallas: letras en su orden y las numéricas de menor a mayor (S, M, 5XL, 40, 44, 64)", _ordn({"64", "40", "M", "S", "5XL", "44"}) == ["S", "M", "5XL", "40", "44", "64"])
check("etiqueta compacta de numéricas: 40-44-48-52-56-60-64; mixtas S-M+40-44", [_lab(ALL_NUM), _lab(["S", "M", "40", "44"])] == ["40-44-48-52-56-60-64", "S-M+40-44"], str([_lab(ALL_NUM), _lab(["S", "M", "40", "44"])]))
check("línea 'pura' de tallas numéricas: 'Size: 40,44,48' sí; '40,44,48' sin la palabra Size y 'BK Size: 40,44' no",
      [_pura("Size: 40,44,48"), _pura("40,44,48"), _pura("BK Size: 40,44")] == [["40", "44", "48"], None, None], str([_pura("Size: 40,44,48"), _pura("40,44,48"), _pura("BK Size: 40,44")]))
ds = m.detect_sizes
check("tallas globales por capas numéricas (40, 44, 48, 52) y por texto 'Size: 40,44,...,64'",
      ds(["40", "44", "48", "52", "ART"], []) == (["40", "44", "48", "52"], "las capas del PDF") and ds([], ["Size: 40,44,48,52,56,60,64", "BK 2_L X 3_W"]) == (ALL_NUM, "el texto del PDF"),
      str((ds(["40", "44", "48", "52", "ART"], []), ds([], ["Size: 40,44,48,52,56,60,64"]))))
check("una sola capa '40' o capas genéricas 1, 2, 3 NO se toman como tallas; si hay capas de letras, mandan las letras",
      ds(["40", "ART"], []) == ([], "") and ds(["1", "2", "3"], []) == ([], "") and ds(["S", "M", "L", "40"], [])[0] == ["S", "M", "L"], str((ds(["40", "ART"], []), ds(["1", "2", "3"], []))))
check("el limpiador de etiquetas quita la lista numérica completa de 'BK 2_L X 3_W Size: 40,44,48,52' (no deja ',44,48,52' en el nombre)",
      m._strip_noise("BK 2_L X 3_W Size: 40,44,48,52") == "BK 2_L X 3_W" and m._strip_noise("BK Size: S-5XL") == "BK", repr(m._strip_noise("BK 2_L X 3_W Size: 40,44,48,52")))

pub, internal, pcs, warns = analyze(B.numeric_labels())
check("etiquetas de tres líneas con 'Size: 40,44,...': cada pieza guarda sus tallas numéricas y su nombre NO las lleva",
      [(p["code"], p["default_name"], p.get("sizes")) for p in pcs] == [("BK", "Back piece", ALL_NUM), ("FT", "Front piece", ALL_NUM), ("SLV Left", "Left sleeve", ["40", "44", "48"]), ("SLV Left", "Left sleeve", ["52", "56", "60", "64"])],
      str([(p["code"], p.get("sizes_label")) for p in pcs]))
check("las mangas Left se reparten por talla numérica (40-44-48 a la izquierda, 52-56-60-64 a la derecha) y sizes_label las lista completas",
      [p.get("sizes_label") for p in pcs][2:] == ["40-44-48", "52-56-60-64"] and pcs[2]["rect"][0] < pcs[3]["rect"][0])
check("las tallas globales salen del texto ('Size: 40,44,...,64'), sin avisos de piezas", pub["sizes"] == ALL_NUM and pub.get("sizes_source") == "el texto del PDF" and not warns, f"{pub['sizes']} / {pub.get('sizes_source')}")
pub, internal, pcs, warns = analyze(B.named_pieces(["BK 2_L X 3_W Size: 40,44,48", "FT 2_L X 3_W Size: 52,56"], dim_lines=True))
check("también en una etiqueta de una sola línea con medidas: 'BK 2_L X 3_W Size: 40,44,48' -> BK + [40,44,48]",
      [(p["code"], p.get("sizes")) for p in pcs] == [("BK", ["40", "44", "48"]), ("FT", ["52", "56"])], str([(p["code"], p.get("sizes")) for p in pcs]))
pub, internal, pcs, warns = analyze(B.numeric_layers())
check("capas numéricas: tallas globales ['40','44','48','52'] desde las capas del PDF", pub["sizes"] == ["40", "44", "48", "52"] and pub.get("sizes_source") == "las capas del PDF", f"{pub['sizes']} / {pub.get('sizes_source')}")
pub, internal, pcs, warns = analyze(B.pair_one_label("SHDL PL"))
check("sin números ni letras de talla en el PDF, no se inventan tallas (sizes vacío)", pub["sizes"] == [] and not any("sizes" in p for p in pcs), str(pub["sizes"]))
m.SESSIONS.clear()
up = client.post("/api/upload", data={"file": (io.BytesIO(B.numeric_labels()), "TEST-0002-XYZ.pdf")}, content_type="multipart/form-data")
uj = up.get_json(silent=True) or {}
pj = uj.get("pieces", [])
check("/api/upload con tallas numéricas: piezas con sizes numéricas y sizes_label, y las globales en 'sizes'",
      up.status_code == 200 and [p.get("sizes_label") for p in pj] == ["40-44-48-52-56-60-64"] * 2 + ["40-44-48", "52-56-60-64"] and uj.get("sizes") == ALL_NUM, f"status={up.status_code} {[p.get('sizes_label') for p in pj]}")
zr = client.get(f"/api/zip/{uj.get('doc_id', 'x')}?dpi=72&mode=art")
nz = sorted(zipfile.ZipFile(io.BytesIO(zr.data)).namelist()) if zr.status_code == 200 else []
check("el ZIP por defecto tiene 4 archivos únicos (los repetidos llevan _2) y ningún número de talla en el nombre",
      len(nz) == 4 and len(set(nz)) == 4 and not [n for n in nz if re.search(r"(?<![A-Za-z0-9])(?:40|44|48|52|56|60|64)(?![A-Za-z0-9])", n.replace("530926F_24", ""))], str(nz))

fails = [n for n, ok in results if not ok]
(OUT / f"results_piezas_{label}.json").write_text(json.dumps({"label": label, "pass": len(results) - len(fails), "fail": len(fails), "omitidas": 0,
                                                              "fallidas": fails, "omitidas_detalle": []}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\nRESUMEN PIEZAS [{label}]: {len(results) - len(fails)}/{len(results)} pruebas PASS, {len(fails)} FAIL")
sys.exit(1 if fails else 0)
