"""PDFs sintéticos para probar las piezas dobles (Left/Right) y las piezas por talla. Cada función devuelve los bytes de un PDF.
Convención de las hojas: las etiquetas 'Piece Name:' van DEBAJO de su pieza (o superpuestas); siempre hay una pieza FRONT aparte para
que la hoja tenga más de una etiqueta (con una sola, el programa trata toda la hoja como una pieza)."""
import warnings
warnings.filterwarnings("ignore")
try:
    import pymupdf as fitz
except ImportError:
    import fitz


def _page(w=900, h=700):
    doc = fitz.open()
    pg = doc.new_page(width=w, height=h)
    pg.insert_text((30, 30), "Style Name: TEST-0002-XYZ", fontsize=12)
    return doc, pg


def _rect(pg, r, color=(0.8, 0.1, 0.1)):
    pg.draw_rect(fitz.Rect(*r), color=None, fill=color)


def _fin(doc):
    data = doc.tobytes()
    doc.close()
    return data


def _front(pg):
    _rect(pg, (560, 60, 800, 330), (0.1, 0.2, 0.8))
    pg.insert_text((620, 350), "Piece Name: FRONT", fontsize=11)


def pair_one_label(label="SHDL PL", gap=8, w=100, h=80, wA=None, hA=None, stacked=False):
    """Una etiqueta (debajo) para dos regiones: lado a lado, o apiladas si stacked=True."""
    doc, pg = _page()
    wA, hA = wA or w, hA or h
    if stacked:
        _rect(pg, (60, 60, 60 + wA, 60 + hA))
        _rect(pg, (60, 60 + hA + gap, 60 + w, 60 + hA + gap + h))
        pg.insert_text((60, 60 + hA + gap + h + 24), f"Piece Name: {label}", fontsize=22)
    else:
        _rect(pg, (60, 60, 60 + wA, 60 + hA))
        _rect(pg, (60 + wA + gap, 60, 60 + wA + gap + w, 60 + h))
        pg.insert_text((70, 60 + max(h, hA) + 24), f"Piece Name: {label}", fontsize=22)
    _front(pg)
    return _fin(doc)


def pair_two_labels(label="SHOULDER", dx=200, label2=None):
    """Dos etiquetas (iguales, o distintas con label2), una por pieza."""
    doc, pg = _page()
    _rect(pg, (60, 60, 160, 140))
    pg.insert_text((62, 160), f"Piece Name: {label}", fontsize=11)
    _rect(pg, (60 + dx, 60, 160 + dx, 140))
    pg.insert_text((62 + dx, 160), f"Piece Name: {label2 or label}", fontsize=11)
    _front(pg)
    return _fin(doc)


def named_pieces(names, dim_lines=False):
    """Una etiqueta por pieza con el nombre tal cual (para probar los formatos de talla). dim_lines=True usa líneas con medidas
    sin 'Piece Name:' (p. ej. 'COLLAR S-M 14L x 3W'), el otro formato de etiqueta que lee el programa."""
    doc, pg = _page()
    for i, n in enumerate(names):
        x = 30 + (i % 5) * 160
        y0 = 60 + (i // 5) * 140
        _rect(pg, (x, y0, x + 120, y0 + 40))
        pg.insert_text((x, y0 + 56), n if dim_lines else f"Piece Name: {n}", fontsize=8)
    return _fin(doc)


def collars_one_label(sizes_text, label="COLLAR", n=3):
    """Una etiqueta superpuesta a n cuellos y, debajo de cada uno, su texto de talla (None = sin texto)."""
    doc, pg = _page()
    xs = [40 + i * 150 for i in range(n)]
    for x in xs:
        _rect(pg, (x, 60, x + 130, 110))
    pg.insert_text((40, 90), f"Piece Name: {label}", fontsize=30)
    for x, t in zip(xs, sizes_text):
        if t:
            pg.insert_text((x + 40, 128), t, fontsize=10)
    _front(pg)
    return _fin(doc)


def label_with_size_below(label="COLLAR", size="S-M"):
    """Etiqueta con la talla en una línea del mismo bloque, justo debajo."""
    doc, pg = _page()
    _rect(pg, (60, 60, 200, 110))
    pg.insert_textbox(fitz.Rect(60, 118, 330, 160), f"Piece Name: {label}\n{size}", fontsize=10)
    _front(pg)
    return _fin(doc)


def two_collars_one_label_with_size(label="COLLAR S-M"):
    """Una etiqueta con talla en el nombre para DOS regiones (cuello izquierdo y derecho de una misma talla)."""
    doc, pg = _page()
    _rect(pg, (40, 60, 170, 110))
    _rect(pg, (180, 60, 310, 110))
    pg.insert_text((40, 90), f"Piece Name: {label}", fontsize=22)
    _front(pg)
    return _fin(doc)


def stacked_overlap_pair(label="SLV"):
    """Dos regiones APILADAS (una encima de la otra) con una etiqueta superpuesta a ambas: no son izquierda/derecha."""
    doc, pg = _page()
    _rect(pg, (60, 60, 160, 120))
    _rect(pg, (60, 128, 160, 188))
    pg.insert_text((62, 126), f"Piece Name: {label}", fontsize=20)
    _front(pg)
    return _fin(doc)


def pair_dissimilar(label="PANEL"):
    """Dos regiones lado a lado de tamaño MUY distinto (180x80 y 60x80) con la etiqueta debajo, solapando a ambas."""
    doc, pg = _page()
    _rect(pg, (60, 60, 240, 140))
    _rect(pg, (248, 60, 308, 140))
    text = f"Piece Name: {label}"
    fs = 180.0 / fitz.get_text_length(text, fontsize=1)       # texto de 180 pt de ancho, desde x=150 hasta x=330
    pg.insert_text((150, 164), text, fontsize=fs)
    _front(pg)
    return _fin(doc)


def numeric_labels(sleeves_split=True):
    """Etiquetas de tres líneas como en los PDF reales (código de estilo / nombre con medidas / talla debajo) pero con tallas NUMÉRICAS:
    'Size: 40,44,48,52,56,60,64'. Con sleeves_split=True las dos mangas Left se reparten en 40,44,48 y 52,56,60,64."""
    doc, pg = _page()
    spec = [("BK", "Size: 40,44,48,52,56,60,64"), ("FT", "Size: 40,44,48,52,56,60,64")]
    if sleeves_split:
        spec += [("SLV Left", "Size: 40,44,48"), ("SLV Left", "Size: 52,56,60,64")]
    for i, (name, size_line) in enumerate(spec):
        x = 30 + i * 200
        _rect(pg, (x, 60, x + 140, 160))
        pg.insert_textbox(fitz.Rect(x, 168, x + 190, 230), f"530926F_24\n{name} 2_L X 3_W\n{size_line}", fontsize=10)
    return _fin(doc)


def numeric_layers(names=("40", "44", "48", "52")):
    """PDF con capas (OCG) llamadas como tallas numéricas y dos piezas etiquetadas."""
    doc, pg = _page()
    ocgs = [doc.add_ocg(n, on=True) for n in names]
    for i, oc in enumerate(ocgs):
        pg.draw_rect(fitz.Rect(40 + i * 6, 60, 180 + i * 6, 160), color=None, fill=(0.8, 0.1, 0.1), oc=oc)
    pg.insert_text((40, 190), "Piece Name: BK", fontsize=11)
    _rect(pg, (400, 60, 540, 160), (0.1, 0.2, 0.8))
    pg.insert_text((400, 190), "Piece Name: FT", fontsize=11)
    return _fin(doc)
