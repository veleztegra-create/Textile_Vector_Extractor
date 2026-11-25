"""Comprueba la sintaxis de los bloques <script> inline del programa con `node --check`.
Uso: python jscheck.py <modulo.py> [directorio_salida]
Códigos de salida: 0 = todo OK, 1 = error de sintaxis, 3 = OMITIDA (node no está instalado)."""
import importlib.util, re, shutil, subprocess, sys, tempfile, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
module_path = Path(sys.argv[1]).resolve()
outdir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(tempfile.mkdtemp(prefix="tegra_js_"))
outdir.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location("jsmod", str(module_path))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
html = m.HTML_TEMPLATE + "\n" + m.COSTOS_HTML
blocks = [b for attrs, b in re.findall(r"<script([^>]*)>(.*?)</script>", html, flags=re.S) if "src=" not in attrs]
files = []
for i, b in enumerate(blocks, 1):
    f = outdir / f"block{i}.js"
    f.write_text(b, encoding="utf-8")
    files.append(f)
print(f"{len(blocks)} bloques <script> inline extraídos en {outdir}")
node = shutil.which("node")
if not node:
    print("OMITIDA: 'node' no está instalado; no se comprobó la sintaxis JavaScript.")
    sys.exit(3)
bad = 0
for f in files:
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    ok = r.returncode == 0
    bad += (not ok)
    print(f"  {f.name}: {f.stat().st_size:>6} bytes -> {'OK' if ok else 'ERROR: ' + r.stderr.strip()[:300]}")
sys.exit(1 if bad else 0)
