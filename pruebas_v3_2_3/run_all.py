#!/usr/bin/env python3
"""Ejecutor único del paquete de pruebas de Textile Vector Extractor v3.2.3.

Uso:
    python run_all.py [RUTA_AL_PROGRAMA.py] [--baseline RUTA_AL_ORIGINAL.py] [--previous RUTA_VERSION_ANTERIOR.py] [--outdir DIR]

--baseline: la v3.2 original (regresión byte a byte de las salidas del extractor).
--previous: la versión inmediatamente anterior (comprueba que las pruebas de piezas dobles y por talla FALLAN allí, es decir, que miden el cambio).
Si no se indica el programa, se busca Textile_Vector_Extractor_v3_2_3.py junto a este archivo o en la carpeta superior.
Cada etapa termina como PASS, FAIL u OMITIDA (con el motivo). Una etapa OMITIDA NO cuenta como superada.
Antes de cada ejecución se borran los resultados anteriores que la etapa podría leer, y solo se aceptan resultados que ESA
ejecución haya generado, con un código de salida coherente (nunca se usa un archivo antiguo).
Código de salida: 0 si no hay FAIL, 1 si hay alguno, 4 si faltan dependencias de Python.
"""
import argparse, ast, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROGRAM_NAME = "Textile_Vector_Extractor_v3_2_3.py"
ENV = dict(os.environ, PYTHONWARNINGS="ignore")
stages = []


def add(name, status, detail=""):
    stages.append((name, status, detail))
    print(f"[{status:<7}] {name}" + (f" — {detail}" if detail else ""))


RC_TIMEOUT = 124      # código que se asigna a un proceso al que se le agotó el tiempo


def run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, env=ENV, **kw)
    except subprocess.TimeoutExpired as exc:
        txt = lambda v: v.decode("utf-8", "replace") if isinstance(v, bytes) else (v or "")
        return subprocess.CompletedProcess(cmd, RC_TIMEOUT, txt(exc.stdout), txt(exc.stderr) + f"\nTIEMPO AGOTADO tras {exc.timeout} s")


def limpiar(rutas):
    """Borra resultados de ejecuciones anteriores. Devuelve None, o un mensaje si alguno no se pudo borrar."""
    for p in rutas:
        try:
            Path(p).unlink(missing_ok=True)
        except OSError as exc:
            return f"no se pudo borrar el resultado anterior {Path(p).name}: {exc}"
    return None


def leer_resultados(proc, resf, t0):
    """Devuelve (resultados, None) o (None, motivo_del_fallo). Solo acepta un archivo generado por ESTA ejecución:
    proceso terminado con código 0 o 1, archivo creado después de t0, formato completo y código coherente con sus FAIL."""
    rc = proc.returncode
    if rc == RC_TIMEOUT:
        return None, "el proceso agotó su tiempo"
    if rc not in (0, 1):
        return None, f"el proceso terminó con código de salida {rc}"
    if not resf.exists():
        return None, f"el proceso terminó con código {rc} sin generar {resf.name}"
    if resf.stat().st_mtime < t0 - 2:
        return None, f"{resf.name} es anterior a esta ejecución (resultado antiguo)"
    try:
        res = json.loads(resf.read_text(encoding="utf-8"))
        fail = int(res["fail"])
        for k in ("pass", "omitidas", "fallidas", "omitidas_detalle"):
            res[k]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, f"{resf.name} ilegible o incompleto ({exc.__class__.__name__})"
    if rc != (0 if fail == 0 else 1):
        return None, f"código de salida {rc} incoherente con los {fail} FAIL que declara {resf.name}"
    return res, None


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_up(port, tries=60):
    for _ in range(tries):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/version", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("module", nargs="?")
    ap.add_argument("--baseline")
    ap.add_argument("--previous")
    ap.add_argument("--outdir")
    a = ap.parse_args()

    module = Path(a.module).resolve() if a.module else next(
        (c for c in (HERE / PROGRAM_NAME, HERE.parent / PROGRAM_NAME) if c.exists()), None)
    if not module or not module.exists():
        sys.exit(f"No encuentro el programa. Pásalo como argumento: python run_all.py RUTA/{PROGRAM_NAME}")
    outdir = Path(a.outdir).resolve() if a.outdir else Path(tempfile.mkdtemp(prefix="tegra_pruebas_"))
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"Programa : {module}\nSalida   : {outdir}\nPython   : {sys.version.split()[0]}  Node: {shutil.which('node') or 'NO INSTALADO'}\n")

    # Limpieza central: ningún resultado de una ejecución anterior puede quedar en la carpeta de salida (cada etapa vuelve a borrar el suyo)
    err_limpieza = limpiar([outdir / f"{pref}_{lab}.json" for pref in ("results", "fp", "results_costos_dpi", "results_piezas", "results_envio_tallas")
                            for lab in ("programa", "baseline", "anterior")])
    if err_limpieza:
        add("Limpieza de resultados anteriores", "FAIL", err_limpieza)

    # 0. dependencias de Python
    missing = []
    for mod, pipname in (("flask", "flask"), ("PIL", "pillow")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pipname)
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        try:
            import fitz  # noqa: F401
        except ImportError:
            missing.append("pymupdf")
    if missing:
        print("Faltan dependencias de Python:", ", ".join(missing), "\nInstálalas con: pip install -r requirements-test.txt")
        sys.exit(4)

    # 1. PDF de prueba
    pdf = HERE / "test_garment.pdf"
    if pdf.exists():
        add("PDF de prueba", "PASS", "incluido en el paquete")
    else:
        sys.path.insert(0, str(HERE))
        import make_pdf
        make_pdf.build(outdir / "test_garment.pdf")
        add("PDF de prueba", "PASS", f"generado en {outdir}")

    # 2. sintaxis Python
    try:
        ast.parse(module.read_text(encoding="utf-8"))
        add("Sintaxis Python del programa", "PASS")
    except SyntaxError as exc:
        add("Sintaxis Python del programa", "FAIL", str(exc))

    # 3. sintaxis JavaScript
    jsdir = outdir / "js"
    err = limpiar(list(jsdir.glob("block*.js")) if jsdir.exists() else [])
    if err:
        add("Sintaxis JavaScript (node --check)", "FAIL", err)
    else:
        r = run([sys.executable, str(HERE / "jscheck.py"), str(module), str(jsdir)])
        status = {0: "PASS", 3: "OMITIDA"}.get(r.returncode, "FAIL")
        add("Sintaxis JavaScript (node --check)", status, "node no está instalado" if r.returncode == 3 else
            (r.stdout.strip().splitlines()[0] if status == "PASS" else (r.stdout + r.stderr).strip()[-300:]))

    # 4. pruebas de servidor
    def server_tests(path, label):
        """Devuelve (resultados, log, error). Borra antes results_/fp_ de esa etiqueta; sin resultados válidos de ESTA ejecución -> error."""
        log = outdir / f"tests_{label}.log"
        resf = outdir / f"results_{label}.json"
        err = limpiar([resf, outdir / f"fp_{label}.json"])
        if err:
            return None, log, err
        t0 = time.time()
        r = run([sys.executable, str(HERE / "tests.py"), str(path), label, str(outdir)], timeout=900)
        log.write_text(r.stdout + r.stderr, encoding="utf-8")
        res, err = leer_resultados(r, resf, t0)
        return res, log, err

    res_srv, log, err_srv = server_tests(module, "programa")
    if err_srv:
        add("Pruebas de servidor (tests.py)", "FAIL", f"{err_srv}; ver {log}")
    else:
        res = res_srv
        detail = f"{res['pass']} PASS, {res['fail']} FAIL, {res['omitidas']} omitidas; log: {log}"
        add("Pruebas de servidor (tests.py)", "PASS" if res["fail"] == 0 else "FAIL", detail)
        for n in res["fallidas"]:
            print("           FALLA:", n)
        for n, why in res["omitidas_detalle"]:
            print(f"           omitida: {n} ({why})")

    # 5. pruebas de interfaz (funciones JS reales contra un servidor vivo)
    blockfile = next((f for f in sorted(jsdir.glob("block*.js")) if "async function exportZip" in f.read_text(encoding="utf-8")), None) if jsdir.exists() else None
    node = shutil.which("node")
    err_docid = limpiar([outdir / f"docid_{m_}.txt" for m_ in ("reduced", "normal")])     # antes de decidir si la etapa corre
    if err_docid:
        add("Pruebas de interfaz (uitest.js)", "FAIL", err_docid)
    elif not node or blockfile is None:
        add("Pruebas de interfaz (uitest.js)", "OMITIDA", "node no está instalado" if not node else "no se extrajo el bloque JS")
    else:
        ok_all, detail = True, []
        for mode, maxpx in (("reduced", 1_500_000), ("normal", 200_000_000)):
            port, didf = free_port(), outdir / f"docid_{mode}.txt"
            err = limpiar([didf])
            if err:
                ok_all = False; detail.append(f"{mode}: {err}"); continue
            srv = subprocess.Popen([sys.executable, str(HERE / "serve.py"), str(module), str(port), str(maxpx), str(didf)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV)
            try:
                if not wait_up(port):
                    ok_all = False; detail.append(f"{mode}: el servidor no arrancó"); continue
                r = run([node, str(HERE / "uitest.js"), f"http://127.0.0.1:{port}", str(didf), mode, str(blockfile)], timeout=300)
                (outdir / f"ui_{mode}.log").write_text(r.stdout + r.stderr, encoding="utf-8")
                last = [l for l in r.stdout.splitlines() if l.startswith("RESUMEN UI")]
                ok_all &= (r.returncode == 0)
                detail.append(last[-1] if last else f"{mode}: sin resumen")
                for l in r.stdout.splitlines():
                    if l.startswith("FAIL"):
                        print("           ", l)
            finally:
                srv.kill(); srv.wait()
        add("Pruebas de interfaz (uitest.js)", "PASS" if ok_all else "FAIL", " | ".join(detail))

    # 6. Costos: DPI y dimensiones físicas (página real en jsdom + .xlsx + TSV)
    def costos_dpi(path, label):
        """Devuelve (resultados, proceso, error). Borra antes results_costos_dpi_<etiqueta>.json; sin resultados válidos de ESTA ejecución -> error."""
        resf = outdir / f"results_costos_dpi_{label}.json"
        err = limpiar([resf])
        if err:
            return None, None, err
        t0 = time.time()
        r = run([sys.executable, str(HERE / "test_costos_dpi.py"), str(path), label, str(outdir)], timeout=1200)
        (outdir / f"tests_costos_dpi_{label}.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        res, err = leer_resultados(r, resf, t0)
        return res, r, err

    def suite(script, resname, path, label):
        """Igual que costos_dpi para cualquier suite: borra antes <resname>_<etiqueta>.json y solo acepta resultados de ESTA ejecución."""
        resf = outdir / f"{resname}_{label}.json"
        err = limpiar([resf])
        if err:
            return None, err
        t0 = time.time()
        r = run([sys.executable, str(HERE / script), str(path), label, str(outdir)], timeout=1200)
        (outdir / f"tests_{resname}_{label}.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        res, err = leer_resultados(r, resf, t0)
        return res, err

    npm = shutil.which("npm")
    if not node:
        add("Costos: DPI y dimensiones físicas (jsdom)", "OMITIDA", "node no está instalado")
    else:
        if not (HERE / "node_modules" / "jsdom").exists() and npm:
            print("           instalando dependencias de Node (npm install: jsdom, jszip)...")
            run([npm, "install", "--no-audit", "--no-fund"], cwd=str(HERE), timeout=600)
        if not (HERE / "node_modules" / "jsdom").exists():
            why = "faltan jsdom/jszip: ejecuta `npm install` en la carpeta del paquete (se necesita internet)"
            add("Costos: DPI y dimensiones físicas (jsdom)", "OMITIDA", why)
        else:
            res, r, err = costos_dpi(module, "programa")
            if err:
                add("Costos: DPI y dimensiones físicas (jsdom)", "FAIL", f"{err}; ver tests_costos_dpi_programa.log")
            else:
                add("Costos: DPI y dimensiones físicas (jsdom)", "PASS" if res["fail"] == 0 else "FAIL",
                    f"{res['pass']} PASS, {res['fail']} FAIL, {res['omitidas']} omitidas")
                for n in res["fallidas"][:15]:
                    print("           FALLA:", n)
                for n, why in res["omitidas_detalle"]:
                    print(f"           omitida: {n} ({why})")
    # 6b. piezas dobles (Left/Right) y por talla: análisis, API, nombres (solo Python)
    jsdom_ok = bool(node) and (HERE / "node_modules" / "jsdom").exists()
    resp_, errp = suite("test_piezas.py", "results_piezas", module, "programa")
    if errp:
        add("Piezas dobles (Left/Right) y por talla (S-M, L-XL, 2-3XL)", "FAIL", f"{errp}; ver tests_results_piezas_programa.log")
    else:
        add("Piezas dobles (Left/Right) y por talla (S-M, L-XL, 2-3XL)", "PASS" if resp_["fail"] == 0 else "FAIL", f"{resp_['pass']} PASS, {resp_['fail']} FAIL")
        for n in resp_["fallidas"][:15]:
            print("           FALLA:", n)

    # 6c. envío de las tallas por pieza hasta Costos y el Excel (jsdom)
    if not jsdom_ok:
        add("Tallas por pieza: extractor -> Costos -> Excel (jsdom)", "OMITIDA", "faltan node o jsdom/jszip")
    else:
        rese_, erre = suite("test_envio_tallas.py", "results_envio_tallas", module, "programa")
        if erre:
            add("Tallas por pieza: extractor -> Costos -> Excel (jsdom)", "FAIL", f"{erre}; ver tests_results_envio_tallas_programa.log")
        else:
            add("Tallas por pieza: extractor -> Costos -> Excel (jsdom)", "PASS" if rese_["fail"] == 0 else "FAIL", f"{rese_['pass']} PASS, {rese_['fail']} FAIL")
            for n in rese_["fallidas"][:15]:
                print("           FALLA:", n)

    # 6d. las pruebas de este cambio deben FALLAR en la versión anterior
    if not a.previous:
        add("Piezas y tallas: las pruebas fallan en la versión anterior (miden el cambio)", "OMITIDA", "no se indicó --previous")
    else:
        prev = Path(a.previous).resolve()
        rp, ep = suite("test_piezas.py", "results_piezas", prev, "anterior")
        parts, bad_prev = [], ep
        if not ep:
            parts.append(f"piezas: {rp['fail']} de {rp['pass'] + rp['fail']} fallan")
            if rp["fail"] == 0:
                bad_prev = "las pruebas de piezas no fallan en la versión anterior"
        if not bad_prev and jsdom_ok:
            re_, ee = suite("test_envio_tallas.py", "results_envio_tallas", prev, "anterior")
            if ee:
                bad_prev = ee
            else:
                parts.append(f"envío de tallas: {re_['fail']} de {re_['pass'] + re_['fail']} fallan")
                if re_["fail"] == 0:
                    bad_prev = "las pruebas de envío de tallas no fallan en la versión anterior"
        add("Piezas y tallas: las pruebas fallan en la versión anterior (miden el cambio)", "FAIL" if bad_prev else "PASS", bad_prev or "; ".join(parts))

    # 7. regresión contra una línea base (opcional)
    if not a.baseline:
        add("Regresión byte a byte vs. versión anterior", "OMITIDA", "no se indicó --baseline")
    else:
        base = Path(a.baseline).resolve()
        _, blog, berr = server_tests(base, "baseline")  # en la versión anterior se esperan FAIL en las pruebas de los defectos
        fa, fb = outdir / "fp_baseline.json", outdir / "fp_programa.json"
        if berr:
            add("Regresión byte a byte vs. versión anterior", "FAIL", f"la ejecución de la línea base no es fiable: {berr}; ver {blog}")
        elif res_srv is None:
            add("Regresión byte a byte vs. versión anterior", "FAIL", f"la ejecución del programa no es fiable: {err_srv}")
        elif not (fa.exists() and fb.exists()):
            add("Regresión byte a byte vs. versión anterior", "FAIL", f"faltan huellas; ver {blog}")
        else:
            A, B = json.loads(fa.read_text()), json.loads(fb.read_text())
            diff = [k for k in sorted(A) if A[k] != B.get(k)]
            add("Regresión byte a byte vs. versión anterior", "PASS" if not diff else "FAIL",
                f"{len(A)} huellas comparadas" + (f"; diferentes: {diff}" if diff else ", todas idénticas"))

    print("\n==== RESUMEN ====")
    for name, status, _ in stages:
        print(f"{status:<8} {name}")
    fails = [s for s in stages if s[1] == "FAIL"]
    omit = [s for s in stages if s[1] == "OMITIDA"]
    print(f"\n{len(stages) - len(fails) - len(omit)} etapas PASS, {len(fails)} FAIL, {len(omit)} OMITIDAS (las omitidas NO están verificadas).")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
