"""Uso: python tests.py <ruta_modulo.py> <etiqueta> [directorio_salida]
Ejecuta pruebas por corrección. Escribe en <directorio_salida> (por defecto, el temporal del sistema):
  fp_<etiqueta>.json (huella de regresión) y results_<etiqueta>.json (conteo de PASS/FAIL/OMITIDAS).
Código de salida: 0 si no hay FAIL, 1 si hay alguno. Las pruebas que no se pueden ejecutar se marcan OMITIDA."""
import sys, io, os, re, json, time, socket, zipfile, shutil, hashlib, logging, tempfile, subprocess, warnings, importlib.util
import urllib.parse, urllib.request
warnings.filterwarnings("ignore")
from PIL import Image

path, label = os.path.abspath(sys.argv[1]), sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else os.path.join(tempfile.gettempdir(), "tegra_tests")
os.makedirs(OUT_DIR, exist_ok=True)
PDF_PATH = os.path.join(HERE, "test_garment.pdf")
if not os.path.exists(PDF_PATH):                      # normalmente viene incluido en el paquete
    sys.path.insert(0, HERE)
    import make_pdf
    PDF_PATH = str(make_pdf.build(os.path.join(OUT_DIR, "test_garment.pdf")))
PDF = open(PDF_PATH, "rb").read()

spec = importlib.util.spec_from_file_location("mod_" + label, path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
logging.disable(logging.CRITICAL)

results, skips, fp = [], [], {}


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS  " if cond else "FAIL  ") + name + (f"   [{detail}]" if detail else ""))


def skip(name, reason):
    skips.append((name, reason))
    print(f"OMITIDA  {name}   [{reason}]")


def port_busy(port):
    with socket.socket() as sk:
        sk.settimeout(1)
        return sk.connect_ex(("127.0.0.1", port)) == 0


def sha(b):
    return hashlib.sha256(b).hexdigest()[:16]


def disp_name(resp):
    cd = resp.headers.get("Content-Disposition", "")
    mt = re.search(r'filename="?([^";]+)"?', cd)
    return mt.group(1) if mt else None


def new_doc():
    return m.new_session(PDF, "TEST-0001-ABC.pdf")["doc_id"]


client = m.app.test_client()

# ------------------------------------------------------------------ 1. VERSION
print("\n== 1. VERSION")
V = m.VERSION
check("VERSION tiene formato vX.Y.Z y ya no es la v3.0.0 errónea", re.fullmatch(r"v\d+\.\d+\.\d+", V or "") is not None and V != "v3.0.0", str(V))
check("el encabezado (docstring) declara la misma versión", V in (m.__doc__ or ""), str(V))
check("/version devuelve la misma versión", client.get("/version").get_json().get("version") == V)
html = client.get("/").get_data(as_text=True)
check("'/' muestra la versión, sin v3.0.0 ni marcador __VERSION__",
      V in html and "v3.0.0" not in html and "__VERSION__" not in html)

# ------------------------------------------------------------------ 2. --inspect
print("\n== 2. --inspect")
tmp = tempfile.mkdtemp()
pdf_copy = os.path.join(tmp, "TEST-0001-ABC.pdf")
shutil.copy(PDF_PATH, pdf_copy)
py = sys.executable
env = dict(os.environ, PYTHONWARNINGS="ignore")


def run(args, timeout=60):
    try:
        return subprocess.run([py, path] + args, capture_output=True, text=True, timeout=timeout, env=env, cwd=tmp)
    except subprocess.TimeoutExpired:
        return None


r = run(["--inspect", pdf_copy])
out_json = os.path.join(tmp, "TEST-0001-ABC.inspect.json")
rep = {}
if r is not None and r.returncode == 0 and os.path.exists(out_json):
    rep = json.load(open(out_json, encoding="utf-8"))
check("--inspect con PDF válido: exit 0", r is not None and r.returncode == 0, f"rc={None if r is None else r.returncode}")
check("--inspect: el JSON NO está vacío y trae 2 piezas", len(rep.get("pieces", [])) == 2, f"claves={sorted(rep)[:4]}")
check("--inspect: incluye capas/avisos y omite catálogos estáticos",
      "layers" in rep and "warnings" in rep and "dictionary" not in rep and "team_catalog" not in rep)

r = run(["--inspect"], timeout=15)
check("--inspect sin archivo: sale con código 2 y muestra uso (no arranca el servidor)",
      r is not None and r.returncode == 2 and "Uso" in r.stderr, "TIMEOUT (arrancó el servidor)" if r is None else f"rc={r.returncode}")

r = run(["--inspect", os.path.join(tmp, "no_existe.pdf")], timeout=15)
check("--inspect archivo inexistente: código 1 y mensaje claro",
      r is not None and r.returncode == 1 and "No se pudo leer" in r.stderr, "TIMEOUT" if r is None else f"rc={r.returncode}")

bad = os.path.join(tmp, "malo.pdf")
open(bad, "wb").write(b"esto no es un pdf" * 50)
r = run(["--inspect", bad], timeout=30)
check("--inspect archivo corrupto: código 1 y mensaje claro (sin traceback)",
      r is not None and r.returncode == 1 and "No se pudo analizar" in r.stderr and "Traceback" not in r.stderr,
      "TIMEOUT" if r is None else f"rc={r.returncode}")

# arranque normal del servidor (regresión)
SRV_PORT = getattr(m, "PORT", 8000)
if port_busy(SRV_PORT):
    skip("arranque normal del servidor sigue funcionando", f"el puerto {SRV_PORT} está ocupado en este equipo")
else:
    srv = subprocess.Popen([py, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, cwd=tmp)
    ver = None
    for _ in range(40):
        try:
            ver = json.load(urllib.request.urlopen(f"http://127.0.0.1:{SRV_PORT}/version", timeout=2))
            break
        except Exception:
            time.sleep(0.5)
    srv.kill(); srv.wait()
    check("arranque normal del servidor sigue funcionando (/version responde)", ver is not None and "version" in ver, str(ver))

# ------------------------------------------------------------------ 3. /api/sheet
print("\n== 3. /api/sheet: validación de page y max")
did = new_doc()
base_sheet = client.get(f"/api/sheet/{did}")
check("sheet con parámetros por defecto: 200 PNG", base_sheet.status_code == 200 and base_sheet.data[:4] == b"\x89PNG")
fp["sheet_default"] = sha(base_sheet.data)
for q in ("page=abc", "max=abc", "page=1.5", "page=", "max=", "page=abc&max=abc", "page=1e3", "max=%20"):
    rr = client.get(f"/api/sheet/{did}?{q}")
    body = rr.get_json(silent=True) or {}
    check(f"sheet ?{q}: HTTP 400 con mensaje JSON (no 500)", rr.status_code == 400 and "error" in body, f"status={rr.status_code}")
for q in ("page=0", "page=-3", "page=999", "page=2&max=100"):
    rr = client.get(f"/api/sheet/{did}?{q}")
    check(f"sheet ?{q}: se acota y responde 200 PNG (comportamiento previo)", rr.status_code == 200 and rr.data[:4] == b"\x89PNG", f"status={rr.status_code}")
a = client.get(f"/api/sheet/{did}?max=100").data
b = client.get(f"/api/sheet/{did}?max=400").data
check("sheet max=100 se acota a 400 (misma imagen que max=400)", a == b)
c = client.get(f"/api/sheet/{did}?max=99999").data
d = client.get(f"/api/sheet/{did}?max=4000").data
check("sheet max=99999 se acota a 4000 (misma imagen que max=4000)", c == d)
check("sheet con doc inexistente sigue dando 404", client.get("/api/sheet/noexiste").status_code == 404)

# ------------------------------------------------------------------ 4. TTL
print("\n== 4. Vencimiento de sesiones (SESSION_TTL)")
did = new_doc()
check("sesión nueva es accesible", m.get_session(did) is not None)
m.SESSIONS[did]["ts"] = time.time() - m.SESSION_TTL - 5
rr = client.get(f"/api/sheet/{did}")
check("sesión vencida (TTL+5 s): responde 404 'La sesión expiró'",
      rr.status_code == 404 and "expir" in json.dumps(rr.get_json(silent=True) or {}), f"status={rr.status_code}")
check("sesión vencida: fue eliminada de SESSIONS", did not in m.SESSIONS)
did = new_doc()
m.SESSIONS[did]["ts"] = time.time() - m.SESSION_TTL + 30
check("sesión a 30 s de vencer sigue válida", client.get(f"/api/sheet/{did}").status_code == 200)
check("el acceso renueva la actividad (ventana deslizante)", time.time() - m.SESSIONS[did]["ts"] < 5)
did_a = new_doc()
m.SESSIONS[did_a]["ts"] = time.time() - m.SESSION_TTL - 1
for ep in (f"/api/pieces/{did_a}", f"/api/piece/{did_a}/p01.png?dpi=300", f"/api/zip/{did_a}"):
    check(f"vencida también en {ep.split('/')[2]}: 404", client.get(ep).status_code == 404)
m.SESSIONS.clear()
ids = [new_doc() for _ in range(m.MAX_SESSIONS + 1)]
check("límite MAX_SESSIONS sigue aplicándose", len(m.SESSIONS) == m.MAX_SESSIONS and ids[0] not in m.SESSIONS)
did = ids[-1]
check("/api/close sigue funcionando", client.post(f"/api/close/{did}").get_json().get("success") is True and did not in m.SESSIONS)

# ------------------------------------------------------------------ 5. DPI efectivo
print("\n== 5. DPI efectivo")
H = lambda r, k: r.headers.get(k)
has_prefix = lambda r, pre: any(k.upper().startswith(pre.upper()) for k in r.headers.keys())
fr = m.fitz.Rect(60, 110, 360, 410)
docx = m.fitz.open(stream=PDF, filetype="pdf")
png_ok, w_ok, h_ok, eff_ok = m.render_png(docx[0], fr, 300, True, False)
check("sin reducción: render_png devuelve el DPI pedido (300)", eff_ok == 300, str(eff_ok))
fp["render_unreduced_png"] = sha(png_ok)

ORIG_MAX = m.MAX_PIXELS
m.MAX_PIXELS = 1_500_000
png_r, w_r, h_r, eff_direct = m.render_png(docx[0], fr, 300, True, False)
check("con límite bajo: render_png reduce el DPI (<300) y respeta el máximo de píxeles",
      eff_direct < 300 and w_r * h_r <= 1_500_000, f"eff={eff_direct}, {w_r}x{h_r}")
meta = Image.open(io.BytesIO(png_r)).info.get("dpi", (0,))[0]
check("el PNG reducido guarda el DPI real en sus metadatos", round(meta) == eff_direct, f"meta={meta}")
docx.close()

did = new_doc()
rr = client.get(f"/api/piece/{did}/p01.png?dpi=300&name=Frente")
eff_r = int(H(rr, "X-Effective-DPI") or 0)       # DPI real que informa la API: base de las comparaciones siguientes
check("piece reducida: X-Requested-DPI=300 y X-Effective-DPI real (menor que 300)",
      rr.status_code == 200 and H(rr, "X-Requested-DPI") == "300" and 0 < eff_r < 300, f"{H(rr, 'X-Requested-DPI')}/{H(rr, 'X-Effective-DPI')}")
check("piece reducida: el nombre de descarga lleva _<DPI>DPI", disp_name(rr) == f"Frente_{eff_r}DPI.png", str(disp_name(rr)))
check("piece reducida: X-File-Name coincide con el nombre de descarga",
      urllib.parse.unquote(H(rr, "X-File-Name") or "") == f"Frente_{eff_r}DPI.png")
check("piece reducida: dpi de metadatos del PNG == X-Effective-DPI",
      round(Image.open(io.BytesIO(rr.data)).info.get("dpi", (0,))[0]) == eff_r)
rr2 = client.get(f"/api/piece/{did}/p02.png?dpi=300&name=Espalda")
check("piece NO reducida: nombre intacto y X-Effective-DPI=300",
      disp_name(rr2) == "Espalda.png" and H(rr2, "X-Effective-DPI") == "300", str(disp_name(rr2)))
rr3 = client.get(f"/api/piece/{did}/p01.png?dpi=300&name=Frente.PNG")
rr4 = client.get(f"/api/piece/{did}/p02.png?dpi=300&name=Espalda.PNG")
check("extensión .PNG se conserva (reducida: sufijo antes; no reducida: intacta)",
      disp_name(rr3) == f"Frente_{eff_r}DPI.PNG" and disp_name(rr4) == "Espalda.PNG", f"{disp_name(rr3)} | {disp_name(rr4)}")
rr5 = client.get(f"/api/piece/{did}/p01.png?dpi=300")
check("sin parámetro name: el nombre por defecto también lleva el sufijo",
      (disp_name(rr5) or "").endswith(f"_{eff_r}DPI.png"), str(disp_name(rr5)))
rr6 = client.get(f"/api/piece/{did}/p01.png?preview=1")
check("miniatura (preview) sin cambios: 200 PNG y sin cabeceras de DPI",
      rr6.status_code == 200 and rr6.data[:4] == b"\x89PNG" and "X-Effective-DPI" not in rr6.headers)

NAMES = urllib.parse.quote(json.dumps({"p01": "Frente", "p02": "Espalda"}))

print("   -- ZIP modo art --")
z = client.get(f"/api/zip/{did}?dpi=300&mode=art&names={NAMES}")
zf = zipfile.ZipFile(io.BytesIO(z.data))
check("ZIP art con una pieza reducida: nombres de archivo",
      sorted(zf.namelist()) == sorted([f"Frente_{eff_r}DPI.png", "Espalda.png"]), str(zf.namelist()))
check("ZIP art: resumen de arte (Requested=300, Count=1, Min=real), sin cabeceras de referencias, total=1",
      H(z, "X-DPI-Art-Requested") == "300" and H(z, "X-DPI-Art-Reduced-Count") == "1" and H(z, "X-DPI-Art-Min") == str(eff_r)
      and not has_prefix(z, "X-DPI-Ref-") and H(z, "X-DPI-Reduced-Count") == "1",
      f"{H(z, 'X-DPI-Art-Requested')}/{H(z, 'X-DPI-Art-Reduced-Count')}/{H(z, 'X-DPI-Art-Min')}")
check("ZIP: ya no se emiten las cabeceras ambiguas X-DPI-Requested / X-DPI-Min",
      "X-DPI-Requested" not in z.headers and "X-DPI-Min" not in z.headers)
check("ZIP art: nombre por defecto usa el rango real", disp_name(z) == f"TEST-0001-ABC_Piezas_PNG_{eff_r}-300DPI.zip", str(disp_name(z)))
z2 = client.get(f"/api/zip/{did}?dpi=300&mode=art&names={NAMES}&zipname=TEST-0001-ABC_Piezas_PNG_300DPI.zip")
check("ZIP art: el zipname con '300DPI' que manda la interfaz se corrige al rango real",
      disp_name(z2) == f"TEST-0001-ABC_Piezas_PNG_{eff_r}-300DPI.zip" and urllib.parse.unquote(H(z2, "X-File-Name") or "") == disp_name(z2),
      str(disp_name(z2)))

print("   -- ZIP modo ref (el DPI pedido es refdpi, no dpi) --")
z4 = client.get(f"/api/zip/{did}?dpi=300&mode=ref&refdpi=600&names={NAMES}")
n4 = zipfile.ZipFile(io.BytesIO(z4.data)).namelist()
eff_ref = int(H(z4, "X-DPI-Ref-Min") or 0)
check("ZIP ref: Ref-Requested=600 (refdpi) y NO 300 (dpi de arte); 1 reducida; sin cabeceras de arte; total=1",
      H(z4, "X-DPI-Ref-Requested") == "600" and H(z4, "X-DPI-Ref-Reduced-Count") == "1" and 0 < eff_ref < 600
      and not has_prefix(z4, "X-DPI-Art-") and H(z4, "X-DPI-Reduced-Count") == "1" and "X-DPI-Requested" not in z4.headers,
      f"{H(z4, 'X-DPI-Ref-Requested')}/{H(z4, 'X-DPI-Ref-Reduced-Count')}/{H(z4, 'X-DPI-Ref-Min')}")
check("ZIP ref reducido: sufijo _<DPI>DPI después de _REF solo en la pieza reducida",
      sorted(n4) == sorted([f"Referencias_con_patron/Frente_REF_{eff_ref}DPI.png", "Referencias_con_patron/Espalda_REF.png"]), str(sorted(n4)))
z5 = client.get(f"/api/zip/{did}?dpi=300&mode=ref&names={NAMES}")
check("ZIP ref sin refdpi: Ref-Requested=150 (valor por defecto), 0 reducidas, sin Ref-Min",
      H(z5, "X-DPI-Ref-Requested") == "150" and H(z5, "X-DPI-Ref-Reduced-Count") == "0" and "X-DPI-Ref-Min" not in z5.headers
      and H(z5, "X-DPI-Reduced-Count") == "0", f"{H(z5, 'X-DPI-Ref-Requested')}/{H(z5, 'X-DPI-Ref-Reduced-Count')}")

print("   -- ZIP modo both (dos resoluciones pedidas distintas) --")
z3 = client.get(f"/api/zip/{did}?dpi=300&mode=both&names={NAMES}")
n3 = zipfile.ZipFile(io.BytesIO(z3.data)).namelist()
check("ZIP both: carpeta de arte usa el DPI real y la de referencias no cambia",
      f"Arte_PNG_{eff_r}-300DPI/Frente_{eff_r}DPI.png" in n3 and f"Arte_PNG_{eff_r}-300DPI/Espalda.png" in n3
      and "Referencias_con_patron/Frente_REF.png" in n3, str(sorted(n3)))
z6 = client.get(f"/api/zip/{did}?dpi=300&mode=both&refdpi=600&names={NAMES}")
n6 = zipfile.ZipFile(io.BytesIO(z6.data)).namelist()
check("ZIP both (dpi=300, refdpi=600): resúmenes SEPARADOS (Art 300→real, Ref 600→real) y total=2",
      H(z6, "X-DPI-Art-Requested") == "300" and H(z6, "X-DPI-Art-Reduced-Count") == "1" and H(z6, "X-DPI-Art-Min") == str(eff_r)
      and H(z6, "X-DPI-Ref-Requested") == "600" and H(z6, "X-DPI-Ref-Reduced-Count") == "1" and H(z6, "X-DPI-Ref-Min") == str(eff_ref)
      and H(z6, "X-DPI-Reduced-Count") == "2" and H(z6, "X-DPI-Art-Min") != H(z6, "X-DPI-Ref-Min"),
      f"art {H(z6, 'X-DPI-Art-Requested')}/{H(z6, 'X-DPI-Art-Min')} | ref {H(z6, 'X-DPI-Ref-Requested')}/{H(z6, 'X-DPI-Ref-Min')} | total {H(z6, 'X-DPI-Reduced-Count')}")
check("ZIP both (refdpi=600): nombres de ambos conjuntos con su propio sufijo",
      f"Arte_PNG_{eff_r}-300DPI/Frente_{eff_r}DPI.png" in n6 and f"Referencias_con_patron/Frente_REF_{eff_ref}DPI.png" in n6, str(sorted(n6)))
z7 = client.get(f"/api/zip/{did}?dpi=150&mode=both&refdpi=600&names={NAMES}")
check("ZIP both solo con referencias reducidas: Art 0 reducidas y sin Art-Min; Ref 1; total=1",
      H(z7, "X-DPI-Art-Requested") == "150" and H(z7, "X-DPI-Art-Reduced-Count") == "0" and "X-DPI-Art-Min" not in z7.headers
      and H(z7, "X-DPI-Ref-Requested") == "600" and H(z7, "X-DPI-Ref-Reduced-Count") == "1" and H(z7, "X-DPI-Reduced-Count") == "1",
      f"art {H(z7, 'X-DPI-Art-Reduced-Count')} | ref {H(z7, 'X-DPI-Ref-Reduced-Count')} | total {H(z7, 'X-DPI-Reduced-Count')}")

m.MAX_PIXELS = ORIG_MAX
print("   -- sin reducción (límite original restaurado) --")
rr = client.get(f"/api/piece/{did}/p01.png?dpi=300&name=Frente")
check("sin reducción: nombre sin sufijo y X-Effective-DPI=300", disp_name(rr) == "Frente.png" and H(rr, "X-Effective-DPI") == "300", str(disp_name(rr)))
fp["piece_p01_300"] = sha(rr.data)
fp["piece_p02_300"] = sha(client.get(f"/api/piece/{did}/p02.png?dpi=300&name=Espalda").data)
z = client.get(f"/api/zip/{did}?dpi=300&mode=both&names={NAMES}")
zf = zipfile.ZipFile(io.BytesIO(z.data))
check("sin reducción: ZIP both con carpeta Arte_PNG_300DPI",
      sorted(zf.namelist()) == sorted(["Arte_PNG_300DPI/Frente.png", "Arte_PNG_300DPI/Espalda.png",
                                       "Referencias_con_patron/Frente_REF.png", "Referencias_con_patron/Espalda_REF.png"]), str(sorted(zf.namelist())))
check("sin reducción: resúmenes Art(300)/Ref(150) con 0 reducidas, sin ningún *-Min, total=0",
      H(z, "X-DPI-Art-Requested") == "300" and H(z, "X-DPI-Ref-Requested") == "150"
      and H(z, "X-DPI-Art-Reduced-Count") == "0" and H(z, "X-DPI-Ref-Reduced-Count") == "0" and H(z, "X-DPI-Reduced-Count") == "0"
      and "X-DPI-Art-Min" not in z.headers and "X-DPI-Ref-Min" not in z.headers)
check("sin reducción: nombre del ZIP por defecto igual que antes",
      disp_name(client.get(f"/api/zip/{did}?dpi=300&mode=art&names={NAMES}")) == "TEST-0001-ABC_Piezas_PNG_300DPI.zip")
zc = client.get(f"/api/zip/{did}?mode=ref&refdpi=1500&names={NAMES}")
check("refdpi fuera de rango se acota a MAX_DPI y la cabecera informa el valor acotado (1200)",
      zc.status_code == 200 and H(zc, "X-DPI-Ref-Requested") == str(m.MAX_DPI), f"{H(zc, 'X-DPI-Ref-Requested')} (MAX_DPI={m.MAX_DPI})")
fp["zip_both_members"] = {n: sha(zf.read(n)) for n in sorted(zf.namelist())}
fp["zip_art_default_name"] = disp_name(client.get(f"/api/zip/{did}?dpi=300&mode=art&names={NAMES}"))

# ------------------------------------------------------------------ 6. regresión general
print("\n== 6. Regresión de rutas existentes")
up = client.post("/api/upload", data={"file": (io.BytesIO(PDF), "TEST-0001-ABC.pdf")}, content_type="multipart/form-data")
uj = up.get_json(silent=True) or {}
check("/api/upload sigue funcionando (200, 2 piezas, doc_id)", up.status_code == 200 and len(uj.get("pieces", [])) == 2 and "doc_id" in uj, f"status={up.status_code}")
fp["upload_analysis"] = sha(json.dumps({k: v for k, v in uj.items() if k != "doc_id"}, sort_keys=True).encode())
pj = client.get(f"/api/pieces/{uj.get('doc_id', 'x')}").get_json(silent=True) or {}
check("/api/pieces sigue funcionando", pj.get("success") is True and len(pj.get("pieces", [])) == 2)
fp["pieces_endpoint"] = sha(json.dumps(pj, sort_keys=True).encode())
check("/costos sigue funcionando", client.get("/costos").status_code == 200)
check("/api/close sigue funcionando (200)", client.post(f"/api/close/{uj.get('doc_id', 'x')}").status_code == 200)

json.dump(fp, open(os.path.join(OUT_DIR, f"fp_{label}.json"), "w"), indent=1, sort_keys=True)
fails = [n for n, ok in results if not ok]
json.dump({"label": label, "pass": len(results) - len(fails), "fail": len(fails), "omitidas": len(skips),
           "fallidas": fails, "omitidas_detalle": [list(x) for x in skips]},
          open(os.path.join(OUT_DIR, f"results_{label}.json"), "w"), indent=1, ensure_ascii=False)
print(f"\nRESUMEN [{label}]: {len(results) - len(fails)}/{len(results)} pruebas PASS, {len(fails)} FAIL, {len(skips)} OMITIDAS")
sys.exit(1 if fails else 0)
