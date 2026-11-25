# Paquete de pruebas — Textile Vector Extractor v3.2.3

Cubre (0) **piezas dobles (Left/Right) y tallas por pieza** (v3.2.3; las tallas van a la columna SIZE, NUNCA en el nombre; incluye
**tallas numéricas** como `Size: 40,44,48,52,56,60,64`), (1) las cinco correcciones de la v3.2.1 (VERSION, `--inspect`, `/api/sheet`, vencimiento de sesiones, DPI efectivo en el
extractor), (2) **el DPI y las dimensiones físicas en Costos** (v3.2.2), (3) la **constancia de DPI estimado en el Excel**
(columna R) y (4) la garantía del propio ejecutor: **nunca se usan resultados antiguos**. No usa rutas del equipo donde se creó.

## Requisitos
- Python 3.10+ y `pip install -r requirements-test.txt` (flask, pymupdf, pillow, openpyxl).
- Node.js (recomendado). Sin Node, las etapas de JavaScript y de Costos se marcan **OMITIDA** (no verificadas).
- `npm install` en esta carpeta (jsdom, jszip) para las pruebas de Costos; `run_all.py` lo intenta solo si hay internet.
- Puerto 8000 libre para una prueba de arranque (si está ocupado esa prueba se marca OMITIDA).

## Uso
    python run_all.py RUTA/Textile_Vector_Extractor_v3_2_3.py
    python run_all.py RUTA/Textile_Vector_Extractor_v3_2_3.py --baseline RUTA/v3_2_original.py --previous RUTA/Textile_Vector_Extractor_v3_2_2.py

- `--baseline`: la v3.2 original; compara byte a byte las salidas del extractor sin reducción de DPI.
- `--previous`: la versión anterior (p. ej. la v3.2.3 de antes del soporte de tallas numéricas, o la v3.2.2); comprueba que las pruebas de piezas dobles y
  tallas **fallan** allí (es decir, que miden el cambio).

Garantía del ejecutor: antes de cada etapa se **borran** los resultados anteriores que podría leer (`results_*`, `fp_*`,
`results_costos_dpi_*`, bloques JS, `docid_*`); un proceso con código de salida anómalo, sin archivo de resultados, con tiempo agotado,
con un archivo anterior a la ejecución o con un código incoherente con sus FAIL deja la etapa en **FAIL**. Demostración:

    python test_run_all_stale.py                      # 28 comprobaciones; debe dar 28/28
    python test_run_all_stale.py --runner OTRO/run_all.py   # contra un ejecutor antiguo: debe FALLAR (ver "stale" abajo)
Resultados y registros en la carpeta que imprime el ejecutor (`--outdir` para elegirla). Salida 0 = sin FAIL; 1 = algún FAIL; 4 = faltan dependencias.

## Archivos
- `run_all.py` — ejecutor único (etapas PASS / FAIL / OMITIDA).
- `test_run_all_stale.py` — demuestra que un resultado antiguo no puede hacer que una ejecución fallida salga PASS
  (A: programa roto + archivos antiguos "PASS" plantados; B: códigos de salida contradictorios; C: reglas unitarias).
- `ejemplo_tallas_divididas_real.pdf` — PDF real del usuario (67NM-BBGH-81F, Buffalo Bills) con tallas divididas: mangas S-L y XL-5XL, YK doble, etiquetas
  de tres líneas (código de estilo / nombre con medidas / talla). Lo usan `test_piezas.py` (sección 7) y `test_envio_tallas.py`.
- `test_piezas.py` + `build_pdfs.py` — **v3.2.3**: lector de tallas (S-M, L-XL, 2-3XL, XXL-3XL, XS/S, Size: L... y numéricas: Size: 40,44,48..., capas 40/44/48/52), parejas Left/Right
  (una etiqueta con 2 piezas, dos etiquetas iguales, apiladas, tamaños dispares, lado ya indicado), piezas por talla (en el nombre, en una línea
  vecina, en un texto junto a cada pieza), casos que NO deben cambiar, y la API (subida, ZIP, nombres). PDFs sintéticos; no necesita Node.
- `test_envio_tallas.py` + `uitest_envio.js` + `uitest_tarjetas.js` — la cadena completa: análisis -> tarjetas del extractor (etiqueta "Tallas: S-L")
  -> `sendToCosts` real -> Costos (jsdom) -> Excel (.xlsx) y TSV; comprueba que las tallas de cada pieza llegan a la columna SIZE, que los nombres
  (Left/Right, piezas repetidas) NO llevan talla, y la convivencia con la lista global de tallas (la talla propia se limita a las tallas seleccionadas).
  Con tallas numéricas comprueba además el selector del extractor (chips 40..64), la cuadrícula de tallas de Costos y sus botones "todas/ninguna".
- `tests.py` — pruebas de servidor del extractor (69 comprobaciones).
- `uitest.js` + `serve.py` — funciones JS reales del extractor (`downloadPiece`, `exportZip`) contra un servidor vivo.
- `jscheck.py` — `node --check` de los 3 bloques `<script>` inline.
- `test_costos_dpi.py` + `costos_dpi.js` + `package.json` — **Costos**: carga la página real en jsdom, procesa PNG con DPI y tamaño
  físico conocidos (150, 288, 300, 600, 1200, sin DPI, DPI inválido, exportación del extractor con DPI reducido), y compara
  pantalla == Excel (.xlsx, leído también con openpyxl) == portapapeles (TSV); constancia "DPI ESTIMADO" en la columna R
  (con y sin efectos especiales); y plantilla intacta (partes del paquete, filas, columnas A–W, estilos y fórmulas).
- `make_pdf.py` / `test_garment.pdf` — PDF sintético (FRONT 300×300 pt, BACK 100×100 pt).

## Límites conocidos
- Las imágenes de Costos son sintéticas (color sólido, mitad transparente): se mide DPI y dimensiones, no calidad de arte.
- jsdom no es un navegador real: la decodificación de imagen, el canvas, las descargas y el portapapeles están simulados; todo el
  resto del código de la página es el real.
- **Las piezas dobles y por talla se probaron con PDFs sintéticos**: la forma exacta en que aparecen las tallas y las etiquetas en TUS PDF reales
  (texto cerca de la pieza, dentro del nombre, en capas...) no está verificada; ver "Cómo se reconoce" en el resumen de la versión.
- El límite real de 200 M de píxeles no se prueba: se baja `MAX_PIXELS` para forzar la reducción de DPI.
- Probado en Linux; no se ha ejecutado en Windows ni macOS.
