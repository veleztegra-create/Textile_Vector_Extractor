"""Prueba: un archivo de resultados ANTIGUO no puede hacer que una ejecución fallida aparezca como PASS.

Uso: python test_run_all_stale.py [--runner RUTA/run_all.py]
Por defecto prueba el run_all.py de esta carpeta; --runner permite apuntar a otro (p. ej. una versión anterior, para ver que falla).
Código de salida: 0 si todo PASS, 1 si algo FAIL.

  A. Integración: un programa que se rompe al importarse + resultados antiguos "PASS" plantados en TODOS los archivos que el
     ejecutor lee (results_*, fp_*, results_costos_dpi_*, bloques JS, docid_*). Ninguna etapa que lea resultados puede salir PASS.
  B. Código de salida: una suite que escribe un resultado "limpio" pero termina con un código de salida que lo contradice,
     o que no escribe nada y deja un resultado antiguo. Debe quedar FAIL en todos los casos salvo el control sano.
  C. Unitarias de las reglas (leer_resultados, limpiar, run con tiempo agotado). Se omiten si el ejecutor no las define.
"""
import argparse, importlib.util, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--runner")
args = ap.parse_args()
RUNNER = Path(args.runner).resolve() if args.runner else HERE / "run_all.py"
WORK = Path(tempfile.mkdtemp(prefix="stale_"))
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS  " if cond else "FAIL  ") + name + (f"   [{detail}]" if detail else ""))


def stages_of(stdout):
    """Estados que imprime el ejecutor: { nombre de etapa: (estado, detalle) }."""
    out = {}
    for line in stdout.splitlines():
        m = re.match(r"^\[(PASS|FAIL|OMITIDA)\s*\] (.+?)(?: — (.*))?$", line)
        if m:
            out[m.group(2)] = (m.group(1), m.group(3) or "")
    return out


SERVER, COSTOS, REGRESION = ("Pruebas de servidor (tests.py)", "Costos: DPI y dimensiones físicas (jsdom)", "Regresión byte a byte vs. versión anterior")
PIEZAS = "Piezas dobles (Left/Right) y por talla (S-M, L-XL, 2-3XL)"
ENVIO = "Tallas por pieza: extractor -> Costos -> Excel (jsdom)"
ANTERIOR = "Piezas y tallas: las pruebas fallan en la versión anterior (miden el cambio)"
OLD = {"marca": "ANTIGUO"}

# ================================================================== A. programa roto + resultados antiguos en todas partes
print("== A. Programa roto + resultados antiguos 'PASS' plantados en todos los archivos que el ejecutor lee")
broken = WORK / "programa_roto.py"
broken.write_text('raise RuntimeError("programa roto a propósito: falla al importarse")\n', encoding="utf-8")
out = WORK / "salida"
(out / "js").mkdir(parents=True)
viejos = {
    "results_programa.json": {**OLD, "label": "programa", "pass": 69, "fail": 0, "omitidas": 0, "fallidas": [], "omitidas_detalle": []},
    "fp_programa.json": {**OLD, "huella": "igual"},
    "results_baseline.json": {**OLD, "label": "baseline", "pass": 30, "fail": 39, "omitidas": 0, "fallidas": ["x"], "omitidas_detalle": []},
    "fp_baseline.json": {**OLD, "huella": "igual"},
    "results_costos_dpi_programa.json": {**OLD, "label": "programa", "pass": 206, "fail": 0, "omitidas": 0, "fallidas": [], "omitidas_detalle": []},
    "results_piezas_programa.json": {**OLD, "label": "programa", "pass": 50, "fail": 0, "omitidas": 0, "fallidas": [], "omitidas_detalle": []},
    "results_piezas_anterior.json": {**OLD, "label": "anterior", "pass": 10, "fail": 42, "omitidas": 0, "fallidas": ["x"], "omitidas_detalle": []},
    "results_envio_tallas_programa.json": {**OLD, "label": "programa", "pass": 17, "fail": 0, "omitidas": 0, "fallidas": [], "omitidas_detalle": []},
    "results_envio_tallas_anterior.json": {**OLD, "label": "anterior", "pass": 5, "fail": 12, "omitidas": 0, "fallidas": ["x"], "omitidas_detalle": []},
}
for name, content in viejos.items():
    (out / name).write_text(json.dumps(content), encoding="utf-8")
for i in (1, 2, 3):
    (out / "js" / f"block{i}.js").write_text("// ANTIGUO\nasync function exportZip() {}\n", encoding="utf-8")
for mode in ("reduced", "normal"):
    (out / f"docid_{mode}.txt").write_text("ANTIGUO", encoding="utf-8")
t0 = time.time()
r = subprocess.run([sys.executable, str(RUNNER), str(broken), "--baseline", str(broken), "--previous", str(broken), "--outdir", str(out)],
                   capture_output=True, text=True, cwd=str(WORK), timeout=1500)
(WORK / "A.log").write_text(r.stdout + r.stderr, encoding="utf-8")
st = stages_of(r.stdout)
print(f"   (ejecutor terminó en {time.time() - t0:.0f} s con código {r.returncode}; log: {WORK / 'A.log'})")
for k, v in st.items():
    print(f"   {v[0]:<8}{k} — {v[1][:110]}")
check("A1. las pruebas de servidor del programa roto quedan FAIL (no PASS por results_programa.json antiguo)", st.get(SERVER, ("?",))[0] == "FAIL", str(st.get(SERVER)))
check("A1b. las pruebas de piezas y tallas del programa roto quedan FAIL (no PASS por results_piezas_programa.json antiguo)", st.get(PIEZAS, ("?",))[0] == "FAIL", str(st.get(PIEZAS)))
check("A2. la regresión queda FAIL (no PASS por fp_programa.json / fp_baseline.json antiguos)", st.get(REGRESION, ("?",))[0] == "FAIL", str(st.get(REGRESION)))
for nombre in (COSTOS, ENVIO, ANTERIOR):
    check(f"A3. '{nombre[:48]}...' nunca queda PASS (FAIL, u OMITIDA si no hay node/jsdom)",
          st.get(nombre, ("?",))[0] in ("FAIL", "OMITIDA"), str(st.get(nombre)))
check("A4. el ejecutor termina con código de salida 1", r.returncode == 1, f"código {r.returncode}")
quedan = [n for n in list(viejos) + [f"js/block{i}.js" for i in (1, 2, 3)] + ["docid_reduced.txt", "docid_normal.txt"]
          if (out / n).exists() and "ANTIGUO" in (out / n).read_text(encoding="utf-8")]
check("A5. ningún archivo antiguo sobrevivió a la ejecución (se borraron antes de ejecutar cada etapa)", not quedan, str(quedan))
check("A6. el programa roto no produjo ningún resultado nuevo", not any((out / n).exists() for n in ("results_programa.json", "fp_programa.json", "results_costos_dpi_programa.json")))

# ================================================================== B. código de salida contra archivo de resultados
print("\n== B. Código de salida de la suite frente a su archivo de resultados")
STUB = '''import json, os, sys
label, outdir = sys.argv[2], sys.argv[3]
fail, rc = int(os.environ["STUB_FAIL"]), int(os.environ["STUB_RC"])
if os.environ.get("STUB_NOWRITE") != "1":
    json.dump({"label": label, "pass": 5, "fail": fail, "omitidas": 0, "fallidas": ["f%d" % i for i in range(fail)], "omitidas_detalle": []},
              open(os.path.join(outdir, "results_%s.json" % label), "w"))
    json.dump({"k": "v"}, open(os.path.join(outdir, "fp_%s.json" % label), "w"))
sys.exit(rc)
'''
mini = WORK / "mini"
mini.mkdir()
shutil.copy(RUNNER, mini / "run_all.py")
for f in ("make_pdf.py", "jscheck.py", "test_garment.pdf"):
    shutil.copy(HERE / f, mini / f)
(mini / "tests.py").write_text(STUB, encoding="utf-8")
trivial = WORK / "programa_trivial.py"
trivial.write_text("VERSION = 'x'\n", encoding="utf-8")


def correr(nombre, rc, fail, nowrite=False, stale=False):
    od = WORK / ("B_" + nombre)
    od.mkdir()
    if stale:
        (od / "results_programa.json").write_text(json.dumps({**OLD, "label": "programa", "pass": 69, "fail": 0, "omitidas": 0, "fallidas": [], "omitidas_detalle": []}), encoding="utf-8")
    env = dict(os.environ, PATH=os.devnull, STUB_RC=str(rc), STUB_FAIL=str(fail), STUB_NOWRITE="1" if nowrite else "0")   # sin PATH: node/npm no existen
    p = subprocess.run([sys.executable, str(mini / "run_all.py"), str(trivial), "--outdir", str(od)], capture_output=True, text=True, env=env, cwd=str(WORK), timeout=300)
    return stages_of(p.stdout).get(SERVER, ("?", ""))


casos = [
    ("control sano: código 0 y 0 FAIL", 0, 0, False, False, "PASS"),
    ("falla legítima: código 1 y 3 FAIL", 1, 3, False, False, "FAIL"),
    ("escribió resultados 'limpios' pero terminó con código 7", 7, 0, False, False, "FAIL"),
    ("escribió resultados con 3 FAIL pero terminó con código 0", 0, 3, False, False, "FAIL"),
    ("escribió resultados 'limpios' pero terminó con código 1", 1, 0, False, False, "FAIL"),
    ("terminó con código 0 sin escribir resultados", 0, 0, True, False, "FAIL"),
    ("terminó con código 1 sin escribir resultados", 1, 0, True, False, "FAIL"),
    ("no escribió resultados y había un resultado antiguo 'PASS'", 0, 0, True, True, "FAIL"),
]
for i, (nombre, rc, fail, nowrite, stale, esperado) in enumerate(casos, 1):
    estado, det = correr(f"{i}", rc, fail, nowrite, stale)
    check(f"B{i}. {nombre} -> {esperado}", estado == esperado, f"{estado} — {det[:100]}")

# ================================================================== C. unitarias
print("\n== C. Reglas del ejecutor (unitarias)")
spec = importlib.util.spec_from_file_location("run_all_bajo_prueba", str(RUNNER))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
if not all(hasattr(mod, n) for n in ("leer_resultados", "limpiar", "run")) or not hasattr(mod, "leer_resultados"):
    print("OMITIDA  C. el ejecutor no define leer_resultados/limpiar (versión anterior): se omiten las pruebas unitarias")
else:
    cp = lambda rc: subprocess.CompletedProcess([], rc, "", "")
    base = {"pass": 3, "fail": 0, "omitidas": 0, "fallidas": [], "omitidas_detalle": []}
    f = WORK / "res.json"

    def prueba(rc, contenido, antiguedad=0, existe=True):
        if f.exists():
            f.unlink()
        t0 = time.time()
        if existe:
            f.write_text(contenido if isinstance(contenido, str) else json.dumps(contenido), encoding="utf-8")
            if antiguedad:
                os.utime(f, (t0 - antiguedad, t0 - antiguedad))
        return mod.leer_resultados(cp(rc), f, t0)

    res, err = prueba(0, base);                                  check("C1. código 0 + resultados frescos con 0 FAIL -> se aceptan", res is not None and err is None)
    res, err = prueba(1, {**base, "fail": 2, "fallidas": ["a", "b"]}); check("C2. código 1 + resultados frescos con 2 FAIL -> se aceptan (falla legítima)", res is not None and res["fail"] == 2)
    res, err = prueba(0, None, existe=False);                    check("C3. código 0 sin archivo de resultados -> error", res is None and "sin generar" in err, str(err))
    res, err = prueba(1, None, existe=False);                    check("C4. código 1 (p. ej. traceback) sin archivo -> error", res is None and "sin generar" in err, str(err))
    res, err = prueba(2, base);                                  check("C5. código 2 aunque exista un archivo 'limpio' -> error", res is None and "código de salida 2" in err, str(err))
    res, err = prueba(mod.RC_TIMEOUT, base);                     check("C6. tiempo agotado aunque exista un archivo 'limpio' -> error", res is None and "tiempo" in err, str(err))
    res, err = prueba(0, base, antiguedad=3600);                 check("C7. archivo de hace 1 hora (anterior a la ejecución) -> error", res is None and "anterior" in err, str(err))
    res, err = prueba(0, {**base, "fail": 4});                   check("C8. código 0 pero el archivo declara 4 FAIL -> error por incoherencia", res is None and "incoherente" in err, str(err))
    res, err = prueba(1, base);                                  check("C9. código 1 pero el archivo declara 0 FAIL -> error por incoherencia", res is None and "incoherente" in err, str(err))
    res, err = prueba(0, "{no es json");                         check("C10. archivo ilegible -> error", res is None and "ilegible" in err, str(err))
    res, err = prueba(0, {"pass": 1});                           check("C11. archivo incompleto (faltan claves) -> error", res is None and "incompleto" in err, str(err))
    g = WORK / "borrame.json"; g.write_text("x"); h = WORK / "no_existe.json"
    check("C12. limpiar() borra los archivos existentes y tolera los que no existen", mod.limpiar([g, h]) is None and not g.exists())
    t1 = time.time(); p = mod.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
    check("C13. run() convierte un proceso colgado en código 124 en ~1 s (no bloquea ni lanza excepción)", p.returncode == mod.RC_TIMEOUT and time.time() - t1 < 10, f"rc={p.returncode} en {time.time() - t1:.1f} s")

fails = [n for n, ok in results if not ok]
print(f"\nRESUMEN STALE [{RUNNER.parent.name}/{RUNNER.name}]: {len(results) - len(fails)}/{len(results)} pruebas PASS, {len(fails)} FAIL")
sys.exit(1 if fails else 0)
