"""Servidor de prueba: python serve.py <modulo.py> <puerto> <max_pixels> <archivo_doc_id>
Carga el programa, baja MAX_PIXELS (para forzar reducción de DPI), crea una sesión con test_garment.pdf
y guarda su doc_id en <archivo_doc_id>."""
import sys, warnings, logging, importlib.util
from pathlib import Path
warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
module_path, port, maxpx, out = Path(sys.argv[1]).resolve(), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
spec = importlib.util.spec_from_file_location("srv", str(module_path))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
logging.disable(logging.CRITICAL)
m.MAX_PIXELS = maxpx
did = m.new_session((HERE / "test_garment.pdf").read_bytes(), "TEST-0001-ABC.pdf")["doc_id"]
Path(out).write_text(did)
m.app.run(host="127.0.0.1", port=port, threaded=True)
