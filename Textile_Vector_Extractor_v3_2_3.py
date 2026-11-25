"""
Textile Vector Extractor v3.2.3 + Sistema de Costos Serigrafía (integrados en una sola app)
Motor real (PyMuPDF) + interfaz "Tegra Pre-Press Suite". Pestaña 1: Extractor. Pestaña 2: Costos.

Uso:    python Textile_Vector_Extractor.py        (abre http://localhost:8000)
Diagnóstico: python Textile_Vector_Extractor.py --inspect archivo.pdf
Requisitos:  pip install flask pymupdf pillow
"""
import io
import json
import logging
import math
import os
import re
import socket
import sys
import threading
import time
import uuid
import webbrowser
import zipfile
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, jsonify, request, send_file

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import pymupdf as fitz
except ImportError:
    import fitz

VERSION = "v3.2.3"
PORT = 8000

# ---------------------------------------------------------------- Configuración
DEFAULT_DPI = 300
MIN_DPI, MAX_DPI = 72, 1200
MAX_PIXELS = 200_000_000
MAX_UPLOAD_MB = 200
PAD_PT = 4
TRIM_PROBE_DPI = 144
TRIM_PROBE_MAX_PIXELS = 30_000_000
TRIM_PAD_PT = 0
CLUSTER_TOL = 5
MAX_REGION_FRACTION = 0.60
MIN_UNNAMED_FRACTION = 0.01
LEGACY_LEFT_RIGHT, LEGACY_ABOVE, LEGACY_BELOW = 350, 900, 100
SESSION_TTL = 2 * 3600
MAX_SESSIONS = 6
CACHE_MAX = 80

PIECE_TRANSLATIONS = {
    "FT": "Front piece",
    "BK": "Back piece",
    "SHLDR": "Shoulder piece",
    "SHDL PL": "Shoulder piece",
    "SHDL": "Shoulder piece",
    "L SLV": "Left sleeve",
    "R SLV": "Right sleeve",
    "NAMEPLATE": "Nameplate piece",
    "FT SD PNL": "Front side panel",
    "BK SD PNL": "Back side panel",
    "NK BND": "Neck band",
    "NAMEPLATE INTERLINING": "Interlining layer",
    "BK SLOPER": "Back sloper",
    "FT SLOPER": "Front sloper",
    "BK SLOPER_1": "Back sloper variation",
    "COLLAR": "Collar",
    "RIB": "Rib",
    "YK": "Yoke piece",
    "SLV LEFT": "Left sleeve",
    "SLV RIGHT": "Right sleeve",
    "SLV RIGTH": "Right sleeve",
}

SIZE_LAYER_RE = re.compile(r"^(?:x{0,3}s|x{0,3}l|m|[2-9]x[sl]|\d{1,2})$", re.IGNORECASE)
PATTERN_KEYWORDS = ("pattern", "patrón", "patron", "sloper", "grad", "guide", "schematic",
                    "body", "cut", "corte", "outline", "contorno", "silhouette")
SPEC_KEYWORDS = ("dimension", "measure", "medida", "cota", "header", "note", "direction", "isolation")
ART_KEYWORDS = ("artwork", "placement", "player", "color cad", "logo", "graphic", "sublim",
                "twill", "embroid", "perforation", "heat transfer", "print")
MIN_ART_FILL_AREA = 300

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("extractor")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.json.sort_keys = False

STYLE_RE = re.compile(r"Style\s*Name\s*:[ \t]*([^\n\r]*)", re.IGNORECASE)
PIECE_RE = re.compile(r"Piece\s*Name\s*:[ \t]*([^\n\r]*)", re.IGNORECASE)
DIM_RE = re.compile(
    r"\s*\d+(?:\.\d+)?\s*_?\s*L\s*[x\u00D7X]\s*\d+(?:\.\d+)?\s*_?\s*W.*$", re.IGNORECASE
)
_DICT_UPPER = {" ".join(k.upper().split()): v for k, v in PIECE_TRANSLATIONS.items()}
_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])("
    + "|".join(
        r"\s+".join(re.escape(w) for w in k.split())
        for k in sorted(PIECE_TRANSLATIONS, key=len, reverse=True)
    )
    + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)

# ---------------------------------------------------------------- Datos para Costos
# Catálogo código -> nombre de equipo (el mismo que usaba el Sistema de Costos).
TEAM_CODES = {'OH': 'Ohio',
 'TX': 'Texas',
 'TEX': 'Texas',
 'CAL': 'California',
 'CA': 'California',
 'FLA': 'Florida',
 'FL': 'Florida',
 'NC': 'North Carolina',
 'SC': 'South Carolina',
 'GA': 'Georgia',
 'GEO': 'Georgia Bulldogs',
 'ALA': 'Alabama',
 'AL': 'Alabama',
 'MS': 'Mississippi',
 'TN': 'Tennessee',
 'KY': 'Kentucky',
 'VA': 'Virginia',
 'PA': 'Pennsylvania',
 'NY': 'New York',
 'NJ': 'New Jersey',
 'MI': 'Michigan',
 'IL': 'Illinois',
 'IN': 'Indiana',
 'WI': 'Wisconsin',
 'MN': 'Minnesota',
 'IA': 'Iowa',
 'MO': 'Missouri',
 'AR': 'Arkansas',
 'LA': 'Louisiana',
 'OK': 'Oklahoma',
 'KS': 'Kansas',
 'NE': 'Nebraska',
 'CO': 'Colorado',
 'UT': 'Utah',
 'AZ': 'Arizona',
 'NV': 'Nevada',
 'NM': 'New Mexico',
 'ID': 'Idaho',
 'MT': 'Montana',
 'WY': 'Wyoming',
 'WA': 'Washington',
 'OR': 'Oregon',
 'ARI': 'Arizona Cardinals',
 'ATL': 'Atlanta Falcons',
 'BAL': 'Baltimore Ravens',
 'BUF': 'Buffalo Bills',
 'CAR': 'Carolina Panthers',
 'CHI': 'Chicago Bears',
 'CIN': 'Cincinnati Bengals',
 'CLE': 'Cleveland Browns',
 'DAL': 'Dallas Cowboys',
 'DEN': 'Denver Broncos',
 'DET': 'Detroit Lions',
 'GBP': 'Green Bay Packers',
 'HOU': 'Houston Texans',
 'IND': 'Indianapolis Colts',
 'JAG': 'Jacksonville Jaguars',
 'KCC': 'Kansas City Chiefs',
 'LAC': 'Los Angeles Chargers',
 'LVR': 'Las Vegas Raiders',
 'MIA': 'Miami Dolphins',
 'MIN': 'Minnesota Vikings',
 'NEP': 'New England Patriots',
 'NOS': 'New Orleans Saints',
 'NYG': 'New York Giants',
 'NYJ': 'New York Jets',
 'PHI': 'Philadelphia Eagles',
 'PIT': 'Pittsburgh Steelers',
 'RAM': 'Los Angeles Rams',
 'SEA': 'Seattle Seahawks',
 'SF9': 'San Francisco 49ers',
 'TBB': 'Tampa Bay Buccaneers',
 'TEN': 'Titans',
 'WAS': 'Washington Commanders'}

STYLE_FILE_RE = re.compile(r"[A-Z0-9]{2,5}(?:-[A-Z0-9]{1,5}){2,4}")
SIZE_ORDER = ["XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL", "5XL"]
_SIZE_ALIAS = {"XXL": "2XL", "XXXL": "3XL", "XXXXL": "4XL", "XXXXXL": "5XL"}
FILE_STOPWORDS = {
    "ON", "PL", "PPF", "WHT", "BLK", "NVY", "RED", "GRY", "GRN", "BLU", "PRACTICE", "MOCKUP", "MOCKUPS",
    "SLV", "SLEEVE", "SLEEVES", "FT", "BK", "FRONT", "BACK", "JSY", "JERSEY", "TEMPLATE", "PROTO", "SAMPLE",
    "NFL", "NCAA", "NBA", "ELITE", "GAME", "LTD", "PRO", "AND", "THE", "MANGA", "MANGAS", "COPY", "COPIA",
    "FINAL", "NEW", "OLD",
}
REF_FOLDER = "Referencias_con_patron"


def normalize_size(s):
    t = re.sub(r"\s+", "", (s or "").upper())
    t = _SIZE_ALIAS.get(t, t)
    return t if t in SIZE_ORDER else None


def expand_size_range(a, b):
    a, b = normalize_size(a), normalize_size(b)
    if not a or not b:
        return []
    i, j = sorted((SIZE_ORDER.index(a), SIZE_ORDER.index(b)))
    return SIZE_ORDER[i:j + 1]


def order_sizes(sizes):
    """Letras (XS..5XL) en su orden y, después, las tallas numéricas (40, 44, 48...) de menor a mayor."""
    s = set(sizes)
    return [x for x in SIZE_ORDER if x in s] + sorted((x for x in s if str(x).isdigit()), key=int)


def detect_sizes(layer_names, text_lines):
    """Tallas del PDF: primero por capas (S, M, L, 2XL... o numéricas 40, 44...), si no por texto (S-3XL, 'Size: 40,44,48')."""
    found = {normalize_size(n) for n in layer_names if SIZE_LAYER_RE.match((n or "").strip())}
    found.discard(None)
    if found:
        return [s for s in SIZE_ORDER if s in found], "las capas del PDF"
    nums = {str(int(n.strip())) for n in layer_names if re.fullmatch(r"\d{2,3}", (n or "").strip()) and 20 <= int(n.strip()) <= 200}
    if len(nums) >= 2:                      # capas de talla numérica (la clasificación ya las trata como capas de talla)
        return order_sizes(nums), "las capas del PDF"
    rng = set()
    for t in text_lines:
        for m in SIZE_RANGE_RE.finditer(t):
            a, b = re.split(r"\s*-\s*", m.group(0))
            rng.update(expand_size_range(a, b))
        sp = parse_size_spec(t, lone=False)
        if sp:
            rng.update(sp["sizes"])
    return order_sizes(rng), ("el texto del PDF" if rng else "")


# ---------------------------------------------------------------- tallas por pieza (v3.2.3)
# Reconoce rangos y listas de tallas escritos de muchas formas: S-M, L-XL, 2-3XL, 2XL-3XL, XXL-3XL, XS/S, S,M,
# "Size: S-M", "(L-XL)", "COLLAR_2XL-3XL"... Una S, M o L suelta NO cuenta como talla (puede ser Left), salvo tras "Size:"/"Talla:".
_SZ_TOK = r"(?:[2-5]XL?|X{2,5}L|XL|XS|S|M|L)"
_SZ_SEP = r"(?:[-\u2013\u2014/,&+]|\bTO\b|\bTHRU\b)"
_SZ_NUM = r"[2-5]\s*[-\u2013\u2014/]\s*[2-5]\s*XL?"
_SZ_KW_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<kw>(?:SIZES?|TALLAS?|SZ)\b\s*[:=#\-]?\s*)"
    r"(?:(?P<num>" + _SZ_NUM + r")|(?P<seq>" + _SZ_TOK + r"(?:(?:\s*" + _SZ_SEP + r"\s*|\s+)" + _SZ_TOK + r")*))(?![A-Za-z0-9])",
    re.IGNORECASE)
_SZ_GEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:(?P<num>" + _SZ_NUM + r")|(?P<seq>" + _SZ_TOK + r"(?:\s*" + _SZ_SEP + r"\s*" + _SZ_TOK + r")*))(?![A-Za-z0-9])",
    re.IGNORECASE)


# Tallas NUMÉRICAS (p. ej. 'Size: 40,44,48,52,56,60,64'): solo se aceptan tras la palabra Size/Talla, porque un número suelto puede ser
# una medida, un estilo o un código. No se aceptan decimales ni medidas con unidad (cm, mm, in), y un rango 'Size: 40-64' NO se expande
# (no se sabe de cuánto en cuánto va la serie): se deja sin leer y la pieza usa la lista global.
_SZ_KWNUM_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<kw>(?:SIZES?|TALLAS?|SZ)\b\s*[:=#]?\s*)"
    r"(?P<nums>\d{1,3}(?:(?:\s*[,;/]\s*|\s+)\d{1,3})*)"
    r"(?![A-Za-z0-9])(?!\.\d)(?!\s*[-\u2013\u2014]\s*\d)(?!\s*(?:cm|mm|in|pt)\b)",
    re.IGNORECASE)


def _norm_tok(t):
    t = re.sub(r"\s+", "", t or "").upper()
    m = re.fullmatch(r"([2-5])XL?", t)
    if m:
        return f"{m.group(1)}XL"
    m = re.fullmatch(r"(X{2,5})L", t)
    if m:
        return f"{len(m.group(1))}XL"
    return t if t in SIZE_ORDER else None


def _eval_seq(seq):
    """Evalúa 'S-M', 'XS/S', 'S,M,L'... De izquierda a derecha: '-' / 'TO' / 'THRU' forman rango; '/', ',', '&', '+' o espacio, lista."""
    sizes, prev, rng, n_rng = set(), None, False, 0
    for m in re.finditer(r"(?P<t>" + _SZ_TOK + r")|(?P<s>" + _SZ_SEP + r")", seq, re.IGNORECASE):
        if m.group("t"):
            tok = _norm_tok(m.group("t"))
            if tok is None:
                continue
            if rng and prev:
                sizes.update(expand_size_range(prev, tok))
                n_rng += 1
            else:
                sizes.add(tok)
            prev, rng = tok, False
        else:
            rng = m.group("s").upper() in ("-", "\u2013", "\u2014", "TO", "THRU")
    return sizes, n_rng


def parse_size_spec(text, lone=True):
    """Tallas escritas en un texto. Devuelve {'sizes': [...letras en SIZE_ORDER y numéricas de menor a mayor], 'spans': [...], 'multi': bool} o None.
    lone=False ignora las tallas sueltas (XL, 2XL...) y exige un rango o lista con separador."""
    text = text or ""
    sizes, spans, taken = set(), [], []
    stat = {"n": 0, "rng": 0}

    def take(m, kw_mode):
        if m.group("num"):
            a, b = re.findall(r"[2-5]", m.group("num"))[:2]
            got, rng = set(expand_size_range(f"{a}XL", f"{b}XL")), 1
        else:
            toks = re.findall(_SZ_TOK, m.group("seq"), re.IGNORECASE)
            if not kw_mode and len(toks) == 1 and (len(toks[0]) == 1 or not lone):
                return False
            got, rng = _eval_seq(m.group("seq"))
        if not got:
            return False
        sizes.update(got)
        spans.append(m.span())
        stat["n"] += 1
        stat["rng"] += rng
        return True

    for m in _SZ_KW_RE.finditer(text):
        if take(m, True):
            taken.append(m.span())
    for m in _SZ_KWNUM_RE.finditer(text):                    # 'Size: 40,44,48,52,56,60,64'
        if any(m.start() < b and a < m.end() for a, b in taken):
            continue
        nums = {str(int(t)) for t in re.findall(r"\d{1,3}", m.group("nums")) if 1 <= int(t) <= 200}
        if nums:
            sizes.update(nums)
            spans.append(m.span())
            taken.append(m.span())
            stat["n"] += 1
    for m in _SZ_GEN_RE.finditer(text):
        if any(m.start() < b and a < m.end() for a, b in taken):
            continue
        take(m, False)
    if not sizes:
        return None
    return {"sizes": order_sizes(sizes), "spans": sorted(spans), "multi": stat["n"] > 1 or stat["rng"] > 1}


def remove_size_text(text, spans):
    t = text or ""
    for a, b in sorted(spans, reverse=True):
        t = t[:a] + " " + t[b:]
    t = re.sub(r"[\(\[\{]\s*[\)\]\}]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"^[\s_\-\u2013\u2014/,&+:]+|[\s_\-\u2013\u2014/,&+:]+$", "", t)


def parse_pure_size_line(text):
    """Tallas de una línea que es SOLO una talla/rango (p. ej. '(S-M)', '2-3XL', 'Size: L-XL'); None si trae algo más."""
    t = re.sub(r"^[\(\[\{]\s*|\s*[\)\]\}]$", "", (text or "").strip())
    r = parse_size_spec(t, lone=True)
    if not r or r["multi"] or re.search(r"[A-Za-z0-9]", remove_size_text(t, r["spans"])):
        return None
    return r["sizes"]


def size_label(sizes):
    """['S','M'] -> 'S-M'; ['L','XL'] -> 'L-XL'; ['2XL','3XL'] -> '2XL-3XL'; no contiguas -> 'S-M+2XL'; numéricas -> '40-44-48'."""
    idx = sorted({SIZE_ORDER.index(s) for s in sizes if s in SIZE_ORDER})
    runs = []
    for i in idx:
        if runs and i == runs[-1][1] + 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    parts = [SIZE_ORDER[a] if a == b else f"{SIZE_ORDER[a]}-{SIZE_ORDER[b]}" for a, b in runs]
    nums = sorted((s for s in sizes if str(s).isdigit()), key=int)
    if nums:
        parts.append("-".join(str(n) for n in nums))          # tallas numéricas: 40-44-48-52-56-60-64
    return "+".join(parts)


def parse_pdf_filename(filename):
    """De '67NM-BBGH-81F BUF_on530926F_24_PL_...' saca style=67NM-BBGH-81F y equipo=BUF (Buffalo Bills)."""
    orig = Path(filename or "").stem
    style, rest = "", orig.upper()
    # Primero se respeta mayúsculas/minúsculas: en '67NM-SAGR-9BFon381892F' el 'on' pegado es minúscula y no es del estilo.
    for text in (orig, orig.upper()):
        for m in STYLE_FILE_RE.finditer(text):
            if re.search(r"\d", m.group(0)) and re.search(r"[A-Z]", m.group(0)):
                style = m.group(0)
                rest = (text[:m.start()] + " " + text[m.end():]).upper()
                break
        if style:
            break
    tokens = [t for t in re.split(r"[\s_.\-]+", rest) if t]
    code = next((t for t in tokens if t in TEAM_CODES), "")
    candidates = []
    for t in tokens:
        if re.fullmatch(r"[A-Z]{2,4}", t) and t not in FILE_STOPWORDS and t not in candidates:
            candidates.append(t)
    return {"style": style, "team_code": code, "team_name": TEAM_CODES.get(code, ""),
            "team_candidates": candidates[:6]}


CATEGORY_WORDS = {"GAME": "NFL Game", "ELITE": "NFL Elite", "LIMITED": "NFL Limited"}
TITLE_STOPWORDS = FILE_STOPWORDS | {
    "GAME", "ELITE", "LIMITED", "JSY", "TM", "BLNK", "ALT", "VF", "VFII", "SCHEM", "SCHE", "SCHEMATIC",
    "SCHEMATICS", "RVLY", "NON", "RECYCLED", "ANNIVERSARY",
}


def _find_style(up):
    for m in STYLE_FILE_RE.finditer(up):
        t = m.group(0)
        if re.search(r"\d", t) and re.search(r"[A-Z]", t):
            return t, m.end()
    return "", 0


def parse_schematic(text):
    """'PPF 67NM-0F49-7TF GBP M VF GAME JSY ALT ... Schematic' -> estilo, equipo (GBP) y categoría (NFL Game)."""
    raw = re.sub(r"\s+", " ", text or "").strip()
    up = raw.upper()
    if not re.search(r"\bSCHE(?:M\w*)?\b", up):
        return None
    style, end = _find_style(up)
    tokens = [t for t in re.split(r"[^A-Z0-9]+", up[end:] if style else up) if t]
    code = next((t for t in tokens if t in TEAM_CODES), "")
    cat_word = next((t for t in tokens if t in CATEGORY_WORDS), "")
    cands = []
    for t in tokens:
        if re.fullmatch(r"[A-Z]{2,4}", t) and t not in TITLE_STOPWORDS and t not in cands:
            cands.append(t)
    if not (style or code or cat_word):
        return None
    return {"title": raw, "style": style, "team_code": code, "category": CATEGORY_WORDS.get(cat_word, ""),
            "candidates": cands}


def find_schematic(pages, extra=()):
    """Busca en el texto de las hojas (línea por línea y en pares de líneas) el título 'Schematic'."""
    cands = []
    for p in pages:
        texts = [ln["text"] for ln in p["lines"]]
        cands += texts
        cands += [texts[i] + " " + texts[i + 1] for i in range(len(texts) - 1)]
    cands += [e for e in extra if e]
    best = None
    for t in cands:
        r = parse_schematic(t)
        if not r:
            continue
        score = (bool(r["style"]), bool(r["team_code"]), bool(r["category"]))
        if best is None or score > best[0]:
            best = (score, r)
        if all(score):
            break
    return best[1] if best else None


FITZ_LOCK = threading.RLock()
SESSIONS = OrderedDict()
SESSIONS_LOCK = threading.Lock()


def clean_filename(text, maxlen=80):
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", text or "")
    text = re.sub(r"_+", "_", re.sub(r"\s+", "_", text.strip())).strip("._-")
    return text[:maxlen] or "sin_nombre"


def parse_piece_name(raw):
    s = re.sub(r"[\r\n]+", " ", raw or "").strip()
    s = re.sub(r"^Piece\s+Name\s*:\s*", "", s, flags=re.IGNORECASE)
    return DIM_RE.sub("", s).strip()


def translate_piece(clean):
    key = " ".join(clean.upper().split())
    if key in _DICT_UPPER:
        return _DICT_UPPER[key]
    side = re.match(r"^([LR])\s+(.+)$", key)
    if side and side.group(2) in _DICT_UPPER:
        base = _DICT_UPPER[side.group(2)]
        return ("Left " if side.group(1) == "L" else "Right ") + base[:1].lower() + base[1:]
    return _TOKEN_RE.sub(
        lambda m: _DICT_UPPER.get(" ".join(m.group(1).upper().split()), m.group(1)), clean
    )


def _lum(c):
    c = c if len(c) == 3 else (c[0],) * 3
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def layer_content_stats(drawings):
    stats = {}
    for d in drawings:
        name = d.get("layer") or ""
        st = stats.setdefault(name, {"art_fill": False, "n": 0})
        st["n"] += 1
        fill = d.get("fill")
        if d.get("type") in ("f", "fs") and fill:
            r = d["rect"]
            lum = _lum(fill)
            colored = max(fill) - min(fill) > 0.12
            if lum < 0.97 and (r.width * r.height >= MIN_ART_FILL_AREA or colored):
                st["art_fill"] = True
    return stats


def classify_layer(name, stats=None):
    n = (name or "").strip()
    low = n.lower()
    if SIZE_LAYER_RE.match(n) or any(k in low for k in PATTERN_KEYWORDS):
        return "pattern"
    if any(k in low for k in SPEC_KEYWORDS):
        return "spec"
    if re.match(r"^art\b", low) or any(k in low for k in ART_KEYWORDS):
        return "art"
    if stats and stats.get(n, {}).get("art_fill"):
        return "art"
    return "spec"


def text_lines(page):
    out = []
    data = page.get_text("dict", sort=True)
    for bi, b in enumerate(data.get("blocks", [])):
        if b.get("type") != 0:
            continue
        brect = fitz.Rect(b["bbox"])
        for l in b.get("lines", []):
            t = "".join(s["text"] for s in l.get("spans", [])).strip()
            if t:
                out.append({"text": t, "rect": fitz.Rect(l["bbox"]), "block": bi, "brect": brect})
    return out


SIZE_RANGE_RE = re.compile(r"\b(?:x{0,3}[slm]|[2-9]x[sl])\s*-\s*(?:x{0,3}[slm]|[2-9]x[sl])\b", re.IGNORECASE)
MEASURE_TEXT_RE = re.compile(r"^\s*[\d.,/ ]+\s*(?:mm|cm|in|inch(?:es)?|pulg|\"|\u201d|\u2033)\s*$", re.IGNORECASE)


def _value_for(lines, i, rx):
    cur = lines[i]
    m = rx.search(cur["text"])
    val = m.group(1).strip()
    used = [cur["rect"]]
    if not val:
        cy = (cur["rect"].y0 + cur["rect"].y1) / 2
        same_row = [
            l for j, l in enumerate(lines)
            if j != i and abs((l["rect"].y0 + l["rect"].y1) / 2 - cy) < max(cur["rect"].height, 6) * 0.8
            and l["rect"].x0 >= cur["rect"].x1 - 2
        ]
        cand = min(same_row, key=lambda l: l["rect"].x0) if same_row else None
        if cand is None:
            below = [
                l for j, l in enumerate(lines)
                if j != i and l["rect"].y0 >= cur["rect"].y1 - 1
                and l["rect"].y0 - cur["rect"].y1 < cur["rect"].height * 1.5
                and l["rect"].x0 < cur["rect"].x1 and l["rect"].x1 > cur["rect"].x0
            ]
            cand = min(below, key=lambda l: l["rect"].y0) if below else None
        if cand is not None:
            val = cand["text"].strip()
            used.append(cand["rect"])
    if re.search(r"\bName\s*:", val, re.IGNORECASE):
        return "", used
    return val, used


def _strip_noise(txt):
    t = re.sub(r"\bSizes?\s*:\s*\d{1,3}(?:(?:\s*[,;/]\s*|\s+)\d{1,3})*(?![\w.])", " ", txt, flags=re.IGNORECASE)   # Size: 40,44,48,52
    t = re.sub(r"\bSize\s*:\s*[\w\-/]+", " ", t, flags=re.IGNORECASE)
    t = SIZE_RANGE_RE.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def _neighbor_rects(lines, i):
    cur = lines[i]
    h = max(cur["rect"].height, 6)
    return [l["rect"] for j, l in enumerate(lines)
            if j != i and l["block"] == cur["block"] and _distance(cur["rect"], l["rect"]) <= 1.5 * h]


def _neighbor_lines(lines, i):
    cur = lines[i]
    h = max(cur["rect"].height, 6)
    return [l for j, l in enumerate(lines)
            if j != i and l["block"] == cur["block"] and _distance(cur["rect"], l["rect"]) <= 1.5 * h]


def read_labels(page):
    lines = text_lines(page)
    style, style_rects, pieces = None, [], []
    for i, ln in enumerate(lines):
        txt = ln["text"]
        ms = STYLE_RE.search(txt)
        if ms:
            val, used = _value_for(lines, i, STYLE_RE)
            style_rects += used + _neighbor_rects(lines, i)
            if val and style is None:
                style = val
            continue
        raw, used, orig = None, [ln["rect"]], None
        if PIECE_RE.search(txt):
            raw, used = _value_for(lines, i, PIECE_RE)
            orig = raw
        elif DIM_RE.search(txt):
            raw = _strip_noise(txt)
            orig = txt            # _strip_noise quita las tallas del nombre: se conserva el texto original para leerlas
            if not re.search(r"[A-Za-z]", DIM_RE.sub("", raw)):
                raw = None
        if raw:
            rect = fitz.Rect(used[0])
            for u in used[1:]:
                rect |= u
            dup = any(p["raw"] == raw and _distance(p["rect"], rect) < 5 for p in pieces)
            if not dup:
                near = []
                for nl in _neighbor_lines(lines, i):
                    sp = parse_pure_size_line(nl["text"])
                    if sp and sp not in near:
                        near.append(sp)
                pieces.append({"raw": raw, "rect": rect, "remove": used + _neighbor_rects(lines, i),
                               "orig": orig, "near_sizes": near[0] if len(near) == 1 else None})
    return style, pieces, lines, style_rects


def remove_text(page, rects):
    n = 0
    for r in rects:
        r = fitz.Rect(r)
        if r.is_empty:
            continue
        try:
            page.add_redact_annot(r, fill=False, cross_out=False)
        except TypeError:
            page.add_redact_annot(r)
        n += 1
    if not n:
        return
    try:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
    except (TypeError, AttributeError):
        try:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        except TypeError:
            page.apply_redactions()


def _clusters(page):
    try:
        return list(page.cluster_drawings(x_tolerance=CLUSTER_TOL, y_tolerance=CLUSTER_TOL))
    except Exception as exc:
        log.warning("cluster_drawings falló: %s", exc)
        return []


def piece_regions(clusters, page_rect, max_fraction=MAX_REGION_FRACTION, min_fraction=0.0):
    area = page_rect.width * page_rect.height
    return [
        r for r in clusters
        if r.width > 2 and r.height > 2
        and min_fraction * area <= r.width * r.height < max_fraction * area
    ]


def art_union(page, clusters):
    rects = piece_regions(clusters, page.rect, max_fraction=0.95)
    try:
        rects += [fitz.Rect(i["bbox"]) for i in page.get_image_info() if i.get("bbox")]
    except Exception:
        pass
    rects = [r for r in rects if not r.is_empty]
    if not rects:
        return None
    u = fitz.Rect(rects[0])
    for r in rects[1:]:
        u |= r
    return u


def _distance(a, b):
    dx = max(b.x0 - a.x1, 0, a.x0 - b.x1)
    dy = max(b.y0 - a.y1, 0, a.y0 - b.y1)
    return math.hypot(dx, dy)


def regions_for_label(label_rect, regions):
    if not regions:
        return []
    inside = [r for r in regions if _distance(label_rect, r) == 0]
    if inside:
        biggest = max(r.width * r.height for r in inside)
        return sorted([r for r in inside if r.width * r.height >= 0.5 * biggest], key=lambda r: r.x0)
    return [min(regions, key=lambda r: _distance(label_rect, r))]


def _x_overlap(a, b):
    return max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))


def assign_labels(labels, regions, page_rect):
    max_gap = max(300.0, 0.08 * page_rect.height)
    res = []
    for L in labels:
        below = []
        for r in regions:
            if _x_overlap(L, r) < 0.3 * L.width or r.y1 > L.y0 + 0.5 * L.height:
                continue
            gap = max(0.0, L.y0 - r.y1)
            if gap <= max_gap:
                below.append((gap, r))
        if below:
            g0 = min(g for g, _ in below)
            tg = sorted([r for g, r in below if g <= g0 + 0.25 * max(g0, 50)], key=lambda r: r.x0)
            res.append({"targets": tg, "kind": "below", "gap": g0, "dropped": False})
            continue
        t = regions_for_label(L, regions)
        inside = bool(t) and _distance(L, t[0]) == 0
        res.append({"targets": t, "kind": "inside" if inside else "near",
                    "gap": 0.0 if (inside or not t) else _distance(L, t[0]), "dropped": False})
    key = lambda r: tuple(round(v) for v in r)
    claims = {}
    for i, x in enumerate(res):
        for r in x["targets"]:
            claims.setdefault(key(r), []).append(i)
    for k, idxs in claims.items():
        if len(idxs) < 2:
            continue
        below_i = [i for i in idxs if res[i]["kind"] == "below"]
        keep = min(below_i, key=lambda i: res[i]["gap"]) if below_i else idxs[0]
        for i in idxs:
            if i != keep:
                res[i]["targets"] = [r for r in res[i]["targets"] if key(r) != k]
                res[i]["dropped"] = True
    return res


# ---------------------------------------------------------------- piezas dobles y por talla (v3.2.3)
_SIDE_RE = re.compile(r"(?<![A-Za-z0-9])(?:L|R|LT|RT|LFT|RGT|RGHT|LEFT|RIGHT|RIGTH|IZQ|IZQUIERDA|IZQUIERDO|DER|DERECHA|DERECHO)(?![A-Za-z0-9])", re.IGNORECASE)
# familias que siempre vienen en pareja (izquierda/derecha); para ellas no se exige que las dos piezas midan parecido
_PAIRED_RE = re.compile(r"(?<![A-Za-z0-9])(?:SLV|SLEEVES?|MANGAS?|SHLDRS?|SHDL|SHOULDERS?|HOMBROS?)(?![A-Za-z0-9])", re.IGNORECASE)
_SHOULDER_RE = re.compile(r"(?<![A-Za-z0-9])(?:SHLDRS?|SHDL|SHOULDERS?|HOMBROS?)(?![A-Za-z0-9])", re.IGNORECASE)


def has_side(name):
    return bool(_SIDE_RE.search(name or ""))


def is_paired_family(name):
    return bool(_PAIRED_RE.search(name or ""))


def sided_default_name(side, base):
    """Nombre en inglés de una pieza con lado asignado. Hombros: 'Shoulder Left'/'Shoulder Right' (como los nombra el usuario);
    el resto, lado primero ('Left sleeve', 'Left yoke piece'), usando el diccionario cuando lo reconoce."""
    word = "Left" if side == "L" else "Right"
    if _SHOULDER_RE.search(base or ""):
        return f"Shoulder {word}"
    t = translate_piece(f"{side} {base}")
    if t.startswith(("Left ", "Right ")):
        return t
    b = translate_piece(base)
    return f"{word} " + (b.title() if b.isupper() else b[:1].lower() + b[1:])


def _sides_ok(a, b, family):
    a, b = sorted((a, b), key=lambda r: r.x0 + r.x1)
    if _x_overlap(a, b) > 0.5 * min(a.width, b.width):
        return False, "no están una al lado de la otra"
    if not family:
        lo, hi = sorted((a.width * a.height, b.width * b.height))
        if lo < 0.5 * hi:
            return False, "no tienen tamaño parecido"
    return True, ""


def _per_target_sizes(targets, lines, regions, used):
    """Una etiqueta con varias piezas, cada una con su propio texto de talla (S-M, L-XL, 2-3XL...) cerca.
    Devuelve [(tallas, [índices de línea])] alineado con targets, o None si falta alguna, hay ambigüedad o se repiten."""
    key = lambda r: tuple(round(v) for v in r)
    per = {}
    for li, ln in enumerate(lines):
        if li in used:
            continue
        sz = parse_pure_size_line(ln["text"])
        if not sz:
            continue
        owner = min(regions or targets, key=lambda r: _distance(ln["rect"], r))      # la región más cercana de TODA la hoja
        hit = [i for i, t in enumerate(targets) if key(t) == key(owner)]
        if not hit:
            continue
        t = targets[hit[0]]
        if _distance(ln["rect"], t) <= max(40.0, 0.2 * max(t.width, t.height)):
            per.setdefault(hit[0], []).append((li, sz))
    if len(per) != len(targets):
        return None
    out = []
    for i in range(len(targets)):
        if len({tuple(sz) for _, sz in per[i]}) != 1:
            return None
        out.append((per[i][0][1], [li for li, _ in per[i]]))
    if len({tuple(sz) for sz, _ in out}) != len(out):
        return None
    return out


def plan_label(base, label_sizes, near_sizes, side_pref, targets, lines, regions, used):
    """Decide cómo se nombra cada región de una etiqueta. Devuelve (specs, motivo, líneas_usadas):
    specs = [{'side': 'L'|'R'|None, 'sizes': [...], 'part': k, 'parts': n}] alineado con targets; motivo != '' si hubo que avisar.
    Las tallas NUNCA se incorporan al nombre: viajan en 'sizes' hasta la columna SIZE de Costos y del Excel."""
    n = len(targets)
    shared = label_sizes or near_sizes or []
    if n == 1:
        return [{"side": side_pref, "sizes": shared, "part": 1, "parts": 1}], "", []
    reason = "ya tiene lado" if side_pref else ""
    if not label_sizes and not side_pref:
        per = _per_target_sizes(targets, lines, regions, used)
        if per:                                              # una etiqueta, una talla propia por pieza: nombres numerados, tallas en 'sizes'
            return ([{"side": None, "sizes": sz, "part": k, "parts": n} for k, (sz, _) in enumerate(per, 1)], "", [li for _, ls in per for li in ls])
    if n == 2 and not side_pref:
        if has_side(base):
            reason = "el nombre ya indica el lado"
        else:
            ok, why = _sides_ok(targets[0], targets[1], is_paired_family(base))
            if ok:                                           # pareja sin lado: izquierda de la hoja = Left, derecha = Right
                order = sorted(range(2), key=lambda i: targets[i].x0 + targets[i].x1)
                side = {order[0]: "L", order[1]: "R"}
                return [{"side": side[i], "sizes": shared, "part": 1, "parts": 1} for i in range(2)], "", []
            reason = why
    elif n > 2:
        reason = "no se pudieron distinguir por talla"
    return [{"side": None, "sizes": shared, "part": k, "parts": n} for k in range(1, n + 1)], reason or "no se pudo asignar lado ni talla", []


def _split_name_sizes(name, orig):
    """('COLLAR S-M', ...) -> ('COLLAR', ['S','M']): las tallas salen del nombre y se guardan aparte; si el nombre fuera solo la talla se conserva."""
    r = parse_size_spec(name, lone=True)
    base, sizes = (remove_size_text(name, r["spans"]), set(r["sizes"])) if r else (name, set())
    if orig and orig != name:
        r2 = parse_size_spec(orig, lone=True)
        if r2:
            sizes |= set(r2["sizes"])
    if not re.search(r"[A-Za-z0-9]", base or ""):
        return name, []
    return base, order_sizes(sizes)


def legacy_window(label_rect):
    return fitz.Rect(
        label_rect.x0 - LEGACY_LEFT_RIGHT, label_rect.y0 - LEGACY_ABOVE,
        label_rect.x1 + LEGACY_LEFT_RIGHT, label_rect.y1 + LEGACY_BELOW,
    )


def _r(rect):
    return [round(float(v), 2) for v in rect]


def visible_bounds(page, clip):
    if clip.is_empty or clip.width < 0.5 or clip.height < 0.5:
        return None
    zoom = TRIM_PROBE_DPI / 72
    px = clip.width * clip.height * zoom * zoom
    if px > TRIM_PROBE_MAX_PIXELS:
        zoom *= math.sqrt(TRIM_PROBE_MAX_PIXELS / px)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=True)
    img = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
    bb = img.getchannel("A").getbbox()
    if not bb:
        return None
    sx, sy = pix.width / clip.width, pix.height / clip.height
    pad_x, pad_y = 1 / sx + TRIM_PAD_PT, 1 / sy + TRIM_PAD_PT
    return fitz.Rect(
        clip.x0 + bb[0] / sx - pad_x, clip.y0 + bb[1] / sy - pad_y,
        clip.x0 + bb[2] / sx + pad_x, clip.y0 + bb[3] / sy + pad_y,
    ) & clip


def contar_colores_reales(img_bytes, tolerancia=16, porcentaje_minimo=0.001):
    """Cuenta los colores reales ignorando artefactos y antialiasing."""
    if Image is None:
        return 0
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    total_pixeles = img.width * img.height
    umbral = total_pixeles * porcentaje_minimo
    conteo = {}
    for r, g, b in img.getdata():
        clave = ((r // tolerancia) * tolerancia, (g // tolerancia) * tolerancia, (b // tolerancia) * tolerancia)
        conteo[clave] = conteo.get(clave, 0) + 1
    return sum(1 for freq in conteo.values() if freq >= umbral)


def render_png(page, clip, dpi, alpha, gray, flat_colors=True):
    eff = float(dpi)
    px = (clip.width * eff / 72) * (clip.height * eff / 72)
    if px > MAX_PIXELS:
        eff = eff * math.sqrt(MAX_PIXELS / px) * 0.98
    zoom = eff / 72

    # Desactiva el antialiasing para evitar tonos intermedios en los bordes
    if flat_colors:
        try:
            fitz.TOOLS.set_aa_level(0)
        except Exception:
            pass

    try:
        pix = page.get_pixmap(
            matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=alpha,
            colorspace=fitz.csGRAY if gray else fitz.csRGB,
        )
    finally:
        if flat_colors:
            try:
                fitz.TOOLS.set_aa_level(8)
            except Exception:
                pass

    pix.set_dpi(int(round(eff)), int(round(eff)))
    return pix.tobytes("png"), pix.width, pix.height, int(round(eff))

def _dpi_suffix(requested, effective):
    """'' si se respetó el DPI pedido; '_<DPI>DPI' si render_png lo redujo (límite MAX_PIXELS)."""
    return "" if effective >= requested else f"_{effective}DPI"


def _dpi_label(requested, log):
    """'300' si nada se redujo; 'min-pedido' (p. ej. '588-600') si hubo piezas reducidas."""
    lows = [e["effective"] for e in log if e["effective"] < e["requested"]]
    return str(requested) if not lows else f"{min(lows)}-{requested}"


def _dpi_summary(log, requested):
    """Resumen de un conjunto renderizado con un mismo DPI pedido: cuántos se redujeron y el DPI mínimo real."""
    lows = [e["effective"] for e in log if e["effective"] < e["requested"]]
    return {"requested": requested, "reduced": len(lows), "min": min(lows) if lows else None}


def render_thumb(page, clip, max_side=260):
    zoom = min(3.0, max_side / max(clip.width, clip.height, 1))
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=True)
    return pix.tobytes("png")


def render_sheet(page, max_side):
    r = page.rect
    zoom = min(4.0, max_side / max(r.width, r.height, 1))
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return pix.tobytes("png")


def analyze_pdf(pdf_bytes, filename):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if doc.needs_pass:
            raise ValueError("El PDF está protegido con contraseña.")
        if doc.page_count == 0:
            raise ValueError("El PDF no tiene páginas.")
        warnings = []

        try:
            cfgs = doc.layer_ui_configs() or []
        except Exception:
            cfgs = []
        stats = {}
        for pg in doc:
            for k, v in layer_content_stats(pg.get_drawings()).items():
                st = stats.setdefault(k, {"art_fill": False, "n": 0})
                st["art_fill"] |= v["art_fill"]
                st["n"] += v["n"]
        layers = []
        for l in cfgs:
            name = (l.get("text") or "").strip()
            if not re.search(r"\w", name):
                continue
            layers.append({"number": l["number"], "name": name,
                           "group": classify_layer(name, stats), "default_on": bool(l.get("on"))})
        log.info("Capas: %s", [(l["name"], l["group"]) for l in layers])

        pages, style_name = [], None
        for pno in range(doc.page_count):
            page = doc[pno]
            if page.rotation:
                page.set_rotation(0)
            style, pieces, lines, style_rects = read_labels(page)
            style_name = style_name or style
            clusters = _clusters(page)
            pages.append({
                "pno": pno, "rect": fitz.Rect(page.rect), "pieces": pieces, "lines": lines,
                "style_rects": style_rects, "clusters": clusters, "union": art_union(page, clusters),
            })
        fn_info = parse_pdf_filename(filename)
        try:
            meta = doc.metadata or {}
        except Exception:
            meta = {}
        sch = find_schematic(pages, [meta.get("title", ""), meta.get("subject", "")]) or {}
        # Estilo: nombre del archivo > Schematic > 'Style Name' interno > nombre del archivo completo
        fs, ss = fn_info["style"], sch.get("style", "")
        if fs and ss and fs != ss and ss in fs:
            chosen_style = ss                      # el nombre trae basura pegada: manda el Schematic
        else:
            chosen_style = fs or ss or style_name or Path(filename).stem
        style_clean = clean_filename(chosen_style)
        if not (fs or ss or style_name):
            warnings.append("No se encontró el estilo (ni 'Style Name:' ni Schematic ni nombre del PDF): se usó el nombre del archivo.")
        # Equipo y categoría: el Schematic manda (casi nunca viene el código en el nombre del PDF)
        team_code = sch.get("team_code") or fn_info["team_code"]
        team_name = TEAM_CODES.get(team_code, "")
        file_tokens = re.split(r"[^A-Z0-9]+", Path(filename).stem.upper())
        category = sch.get("category") or CATEGORY_WORDS.get(next((t for t in file_tokens if t in CATEGORY_WORDS), ""), "")
        team_cands = [c for c in (sch.get("candidates", []) + fn_info["team_candidates"]) if c not in TITLE_STOPWORDS]
        team_cands = list(dict.fromkeys(team_cands))[:6]
        sizes, sizes_src = detect_sizes([l["name"] for l in layers],
                                        [ln["text"] for p in pages for ln in p["lines"]])
        if sch.get("team_code") and fn_info["team_code"] and sch["team_code"] != fn_info["team_code"]:
            warnings.append(f"El nombre del PDF dice {fn_info['team_code']} pero el Schematic dice {sch['team_code']}: se usó el Schematic.")
        if fs and ss and fs not in ss and ss not in fs:
            warnings.append(f"El estilo del nombre del PDF ({fs}) no coincide con el del Schematic ({ss}): se usó el del nombre.")
        if not sch:
            warnings.append("No se encontró el título 'Schematic' como texto en el PDF (si está convertido a curvas no se puede leer).")
        if not team_code:
            warnings.append("No se detectó el equipo (ni en el Schematic ni en el nombre del PDF): escríbelo en 'Datos para Costos'.")
        if not category:
            warnings.append("No se detectó la categoría (GAME / ELITE / LIMITED): elígela en 'Datos para Costos'.")
        if not sizes:
            warnings.append("No se detectaron tallas en el PDF: Costos usará las que tenga marcadas.")
        total_labels = sum(len(p["pieces"]) for p in pages)

        out = []

        extra_remove = {}                      # texto de talla usado para nombrar piezas: se borra del render como las etiquetas

        def add_piece(pd, code, rect, label, part=1, parts=1, default_name=None, sizes=None, variant=""):
            rect = fitz.Rect(rect) & pd["rect"]
            d = {
                "id": f"p{len(out) + 1:02d}", "page": pd["pno"] + 1, "code": code,
                "default_name": default_name or translate_piece(code), "rect": _r(rect),
                "label": _r(label) if label is not None else None, "part": part, "parts": parts,
            }
            if sizes:
                d["sizes"] = list(sizes)                 # tallas que comprende esta pieza (solo si se detectaron): van a la columna SIZE
                d["sizes_label"] = size_label(sizes)     # forma compacta para mostrarla: S-L, XL-5XL
            if variant:
                d["variant"] = variant                   # 'side': Left/Right asignado por el programa
            out.append(d)

        if total_labels:
            mode = "A: etiquetas Piece Name"
            for pd in pages:
                pieces = pd["pieces"]
                if not pieces:
                    continue
                parsed = [parse_piece_name(p["raw"]) for p in pieces]
                bases, lsizes = [], []
                for p, name in zip(pieces, parsed):
                    b, sz = _split_name_sizes(name, p.get("orig"))
                    bases.append(b)
                    lsizes.append(sz)
                # Dos etiquetas iguales de una familia en pareja (mangas, hombros) sin lado: izquierda de la hoja = Left, derecha = Right
                side_pref = [None] * len(pieces)
                groups = {}
                for i, b in enumerate(bases):
                    if is_paired_family(b) and not has_side(b):
                        groups.setdefault(" ".join(b.upper().split()), []).append(i)
                for key, idxs in groups.items():
                    if len(idxs) != 2:
                        continue
                    idxs.sort(key=lambda i: pieces[i]["rect"].x0 + pieces[i]["rect"].x1)
                    cx = lambda i: (pieces[i]["rect"].x0 + pieces[i]["rect"].x1) / 2
                    if key != "SLV" and abs(cx(idxs[1]) - cx(idxs[0])) < 30:
                        continue
                    side_pref[idxs[0]], side_pref[idxs[1]] = "L", "R"
                single = len(pieces) == 1
                regions = [] if single else piece_regions(pd["clusters"], pd["rect"])
                assigned = [] if single else assign_labels([p["rect"] for p in pieces], regions, pd["rect"])
                used_lines = set()
                for n_i, (p, clean) in enumerate(zip(pieces, bases)):
                    label = p["rect"]
                    if single:
                        targets = [pd["union"] or legacy_window(label)]
                    else:
                        a_i = assigned[n_i]
                        targets = a_i["targets"]
                        if a_i["dropped"] and not targets:
                            warnings.append(f"Etiqueta repetida '{clean}' en la hoja: se ignoró.")
                            continue
                        if not targets:
                            targets = [legacy_window(label)]
                            warnings.append(f"Pieza '{clean}': sin trazos detectables, ventana fija.")
                    specs, reason, claimed = plan_label(clean, lsizes[n_i], p.get("near_sizes"), side_pref[n_i],
                                                        targets, pd["lines"], regions, used_lines)
                    for li in claimed:
                        used_lines.add(li)
                        extra_remove.setdefault(pd["pno"], []).append(fitz.Rect(pd["lines"][li]["rect"]))
                    if len(targets) > 1 and reason:
                        warnings.append(f"'{clean}': una etiqueta para {len(targets)} piezas ({reason}); se numeraron.")
                    for t, sp in zip(targets, specs):
                        code = " ".join(x for x in (sp["side"], clean) if x)           # la talla no forma parte del nombre
                        add_piece(pd, code, t, label, sp["part"], sp["parts"],
                                  default_name=sided_default_name(sp["side"], clean) if sp["side"] else None,
                                  sizes=sp["sizes"], variant="side" if sp["side"] else "")
        elif doc.page_count > 1:
            mode = "B: una pieza por página"
            warnings.append("No hay 'Piece Name:'; se trató cada página como una pieza.")
            for pd in pages:
                name = None
                for ln in pd["lines"]:
                    if not STYLE_RE.search(ln["text"]):
                        name = parse_piece_name(ln["text"])
                        if name:
                            break
                add_piece(pd, name or f"Pagina_{pd['pno'] + 1}", pd["union"] or pd["rect"], None)
        else:
            pd = pages[0]
            regions = piece_regions(pd["clusters"], pd["rect"], min_fraction=MIN_UNNAMED_FRACTION)
            regions.sort(key=lambda r: (round(r.y0 / 50), r.x0))
            if regions:
                mode = "C: grupos de trazos sin nombre"
                warnings.append("No se encontró texto 'Piece Name:'.")
                for i, r in enumerate(regions, 1):
                    add_piece(pd, f"Pieza_{i:02d}", r, None)
            else:
                mode = "D: hoja completa"
                warnings.append("No se detectaron piezas; se usa la hoja completa.")
                add_piece(pd, "Pagina_Completa", pd["rect"], None)

        remove = {}
        for pd in pages:
            rects = list(pd["style_rects"])
            for p in pd["pieces"]:
                rects += p["remove"]
            rects += [l["rect"] for l in pd["lines"] if MEASURE_TEXT_RE.match(l["text"])]
            rects += extra_remove.get(pd["pno"], [])
            if rects:
                remove[pd["pno"]] = [_r(r) for r in rects]

        public = {
            "filename": filename, "style_raw": style_name, "style": style_clean, "mode": mode,
            "pages": [{"page": p["pno"] + 1, "w": round(p["rect"].width, 2), "h": round(p["rect"].height, 2)}
                      for p in pages],
            "layers": layers, "pieces": out, "warnings": warnings,
            "dictionary": PIECE_TRANSLATIONS, "trim_available": Image is not None,
            "team_code": team_code, "team_name": team_name,
            "team_candidates": team_cands, "team_catalog": TEAM_CODES,
            "category": category, "schematic": sch.get("title", ""),
            "sizes": sizes, "sizes_source": sizes_src,
        }
        return public, {"remove": remove}
    finally:
        doc.close()


def inspect_pdf(pdf_bytes, filename="documento.pdf"):
    """Diagnóstico (--inspect): el mismo análisis que usa la interfaz, sin los catálogos estáticos."""
    public, _internal = analyze_pdf(pdf_bytes, filename)
    return {k: v for k, v in public.items() if k not in ("dictionary", "team_catalog")}


def _hidden_art_paths(doc):
    """Formas RELLENAS dentro de capas de talla (S...5XL). En algunas plantillas ahí viven las franjas de las mangas."""
    found = []
    for pno in range(doc.page_count):
        pg = doc[pno]
        if pg.rotation:
            pg.set_rotation(0)
        for d in pg.get_drawings():
            lay = (d.get("layer") or "").strip()
            fill = d.get("fill")
            if fill is None or len(fill) != 3 or not normalize_size(lay):
                continue
            if min(fill) >= 0.97:              # relleno blanco: no es arte
                continue
            found.append((pno, d))
    return found


def inject_hidden_art(data, apply=True):
    """Copia esas formas rellenas a la capa de arte para que 'Solo piezas' las vea. Devuelve (pdf, info)."""
    info = {"count": 0, "layers": [], "applied": False, "requested": apply}
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        if doc.needs_pass or doc.page_count == 0:
            return data, info
        found = _hidden_art_paths(doc)
        info["count"] = len(found)
        info["layers"] = sorted({d["layer"] for _, d in found})
        if not found or not apply:
            return data, info
        try:
            ocgs = doc.get_ocgs() or {}
        except Exception:
            ocgs = {}
        arts = [(x, o) for x, o in ocgs.items() if classify_layer(o.get("name", "")) == "art"]
        target = None
        for pref in (lambda o: o.get("on") and "screen" in o.get("name", "").lower(),
                     lambda o: o.get("on"), lambda o: True):
            target = next((x for x, o in arts if pref(o)), None)
            if target:
                break
        if not target:
            return data, info
        by_page = {}
        for pno, d in found:
            by_page.setdefault(pno, []).append(d)
        for pno, paths in by_page.items():
            shape = doc[pno].new_shape()
            for d in paths:
                for it in d["items"]:
                    if it[0] == "l":
                        shape.draw_line(it[1], it[2])
                    elif it[0] == "c":
                        shape.draw_bezier(it[1], it[2], it[3], it[4])
                    elif it[0] == "re":
                        shape.draw_rect(it[1])
                    elif it[0] == "qu":
                        shape.draw_quad(it[1])
                op = d.get("fill_opacity")
                shape.finish(width=0, color=None, fill=d["fill"], even_odd=bool(d.get("even_odd")),
                             closePath=bool(d.get("closePath", True)), fill_opacity=1 if op is None else op, oc=target)
            shape.commit()
        info["applied"] = True
        return doc.tobytes(garbage=0, deflate=True), info
    finally:
        doc.close()


def new_session(pdf_bytes, filename):
    public, internal = analyze_pdf(pdf_bytes, filename)
    doc_id = uuid.uuid4().hex
    now = time.time()
    with SESSIONS_LOCK:
        for k in [k for k, v in SESSIONS.items() if now - v["ts"] > SESSION_TTL]:
            del SESSIONS[k]
        while len(SESSIONS) >= MAX_SESSIONS:
            SESSIONS.popitem(last=False)
        SESSIONS[doc_id] = {"pdf": pdf_bytes, "analysis": public, "remove": internal["remove"],
                            "ts": now, "clips": {}, "cache": OrderedDict()}
    public = dict(public, doc_id=doc_id)
    return public


def get_session(doc_id):
    with SESSIONS_LOCK:
        s = SESSIONS.get(doc_id)
        if not s:
            return None
        now = time.time()
        if now - s["ts"] > SESSION_TTL:
            del SESSIONS[doc_id]          # vencida: se libera y se trata como inexistente
            return None
        s["ts"] = now
        SESSIONS.move_to_end(doc_id)
        return s


def cache_get(sess, key):
    with SESSIONS_LOCK:
        v = sess["cache"].get(key)
        if v is not None:
            sess["cache"].move_to_end(key)
        return v


def cache_put(sess, key, value):
    with SESSIONS_LOCK:
        sess["cache"][key] = value
        while len(sess["cache"]) > CACHE_MAX:
            sess["cache"].popitem(last=False)


def parse_opts(args):
    layers = args.get("layers")
    layers_on = None
    if layers is not None:
        layers_on = {int(x) for x in layers.split(",") if x.strip().lstrip("-").isdigit()}
    try:
        dpi = int(args.get("dpi", DEFAULT_DPI))
    except ValueError:
        dpi = DEFAULT_DPI
    return {
        "layers_on": layers_on,
        "layers_key": "default" if layers is None else ",".join(map(str, sorted(layers_on))),
        "show_text": args.get("text", "0") == "1",
        "trim": args.get("trim", "1") == "1" and Image is not None,
        "dpi": max(MIN_DPI, min(MAX_DPI, dpi)),
        "alpha": args.get("bg", "transparent") != "white",
        "gray": args.get("color", "rgb") == "gray",
    }


def open_doc(sess, o):
    doc = fitz.open(stream=sess["pdf"], filetype="pdf")
    for pno in range(doc.page_count):
        pg = doc[pno]
        if pg.rotation:
            pg.set_rotation(0)
    if o["layers_on"] is not None:
        for l in sess["analysis"]["layers"]:
            doc.set_layer_ui_config(l["number"], 0 if l["number"] in o["layers_on"] else 2)
    if not o["show_text"]:
        for pno, rects in sess["remove"].items():
            remove_text(doc.load_page(pno), [fitz.Rect(r) for r in rects])
    return doc


def get_clips(sess, doc, o):
    key = (o["layers_key"], o["show_text"], o["trim"])
    with SESSIONS_LOCK:
        hit = sess["clips"].get(key)
    if hit is not None:
        return hit
    clips = {}
    for pc in sess["analysis"]["pieces"]:
        page = doc.load_page(pc["page"] - 1)
        base = fitz.Rect(pc["rect"])
        if o["show_text"] and pc["label"]:
            base |= fitz.Rect(pc["label"])
        base = base & page.rect
        if base.is_empty:
            clips[pc["id"]] = None
        elif o["trim"]:
            t = visible_bounds(page, base)
            clips[pc["id"]] = _r(t) if t is not None and not t.is_empty else None
        else:
            clips[pc["id"]] = _r(fitz.Rect(base.x0 - PAD_PT, base.y0 - PAD_PT,
                                           base.x1 + PAD_PT, base.y1 + PAD_PT) & page.rect)
    with SESSIONS_LOCK:
        if len(sess["clips"]) > 12:
            sess["clips"].clear()
        sess["clips"][key] = clips
    return clips


def api_error(msg, code=400):
    return jsonify(success=False, error=msg), code


def _session_or_error(doc_id):
    s = get_session(doc_id)
    return (s, None) if s else (None, api_error("La sesión expiró. Vuelve a subir el PDF.", 404))


@app.errorhandler(413)
def too_large(_e):
    return api_error(f"Archivo demasiado grande (máx. {MAX_UPLOAD_MB} MB).", 413)


@app.route("/")
def index():
    return Response(HTML_TEMPLATE.replace("__VERSION__", VERSION), mimetype="text/html")


@app.route("/version")
def version():
    return jsonify(version=VERSION, pid=os.getpid())


@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return api_error("No se recibió ningún archivo.")
    data = f.read()
    if not data.startswith(b"%PDF"):
        return api_error("El archivo no parece un PDF válido.")
    hidden = {"count": 0, "layers": [], "applied": False, "requested": False}
    try:
        with FITZ_LOCK:
            try:
                data, hidden = inject_hidden_art(data, request.form.get("hidden_art", "1") == "1")
            except Exception:
                log.exception("No se pudo revisar el arte dentro de las capas de talla")
            public = new_session(data, f.filename)
        if hidden["count"]:
            lay = ", ".join(hidden["layers"])
            if hidden["applied"]:
                public["warnings"].append(f"Se tomaron como arte {hidden['count']} forma(s) rellena(s) que estaban dentro de la capa de talla {lay} (p. ej. franjas de mangas).")
            elif hidden["requested"]:
                public["warnings"].append(f"Hay {hidden['count']} forma(s) rellena(s) dentro de la capa de talla {lay} (probable arte) pero el PDF no tiene capa de arte donde ponerlas.")
            else:
                public["warnings"].append(f"Hay {hidden['count']} forma(s) rellena(s) dentro de la capa de talla {lay} (probable arte, p. ej. franjas de mangas). Activa 'Arte en capas de talla' y vuelve a cargar el PDF.")
        public["hidden_art"] = hidden
    except ValueError as exc:
        return api_error(str(exc))
    except Exception as exc:
        log.exception("Error analizando el PDF")
        return api_error(f"Error interno: {exc}", 500)
    return jsonify(success=True, **public)


@app.route("/api/sheet/<doc_id>")
def api_sheet(doc_id):
    sess, err = _session_or_error(doc_id)
    if err:
        return err
    o = parse_opts(request.args)
    try:
        page_no = int(request.args.get("page", 1))
        max_side = int(request.args.get("max", 1800))
    except (TypeError, ValueError):
        return api_error("Los parámetros 'page' y 'max' deben ser números enteros.", 400)
    page_no = max(1, page_no)
    max_side = max(400, min(4000, max_side))
    key = ("sheet", page_no, max_side, o["layers_key"], o["show_text"])
    png = cache_get(sess, key)
    if png is None:
        with FITZ_LOCK:
            doc = open_doc(sess, o)
            try:
                png = render_sheet(doc.load_page(min(page_no, doc.page_count) - 1), max_side)
            finally:
                doc.close()
        cache_put(sess, key, png)
    return send_file(io.BytesIO(png), mimetype="image/png", max_age=0)


@app.route("/api/pieces/<doc_id>")
def api_pieces(doc_id):
    sess, err = _session_or_error(doc_id)
    if err:
        return err
    o = parse_opts(request.args)
    with FITZ_LOCK:
        doc = open_doc(sess, o)
        try:
            clips = get_clips(sess, doc, o)
        finally:
            doc.close()
    warnings = []
    if request.args.get("trim", "1") == "1" and Image is None:
        warnings.append("Pillow no está instalado.")
    empty = [p["id"] for p in sess["analysis"]["pieces"] if clips.get(p["id"]) is None]
    if empty:
        warnings.append(f"{len(empty)} pieza(s) sin contenido visible.")
    return jsonify(success=True, warnings=warnings,
                   pieces=[{"id": p["id"], "clip": clips.get(p["id"])} for p in sess["analysis"]["pieces"]])


@app.route("/api/piece/<doc_id>/<pid>.png")
def api_piece(doc_id, pid):
    sess, err = _session_or_error(doc_id)
    if err:
        return err
    piece = next((p for p in sess["analysis"]["pieces"] if p["id"] == pid), None)
    if piece is None:
        return api_error("Pieza no encontrada.", 404)
    o = parse_opts(request.args)
    preview = request.args.get("preview") == "1"
    key = ("thumb", pid, o["layers_key"], o["show_text"], o["trim"])
    if preview:
        png = cache_get(sess, key)
        if png is not None:
            return send_file(io.BytesIO(png), mimetype="image/png", max_age=60)
    eff_dpi = None
    with FITZ_LOCK:
        doc = open_doc(sess, o)
        try:
            clip_l = get_clips(sess, doc, o).get(pid)
            if clip_l is None:
                return api_error("Esta pieza no tiene contenido visible.", 404)
            clip = fitz.Rect(clip_l)
            page = doc.load_page(piece["page"] - 1)
            if preview:
                png = render_thumb(page, clip)
            else:
                png, _w, _h, eff_dpi = render_png(page, clip, o["dpi"], o["alpha"], o["gray"])
        finally:
            doc.close()
    if preview:
        cache_put(sess, key, png)
        return send_file(io.BytesIO(png), mimetype="image/png", max_age=60)
    name = clean_filename(request.args.get("name", f"{sess['analysis']['style']}_{piece['code']}"))
    tag = _dpi_suffix(o["dpi"], eff_dpi)
    if name.lower().endswith(".png"):
        fname = name[:-4] + tag + name[-4:]
    else:
        fname = name + tag + ".png"
    resp = send_file(io.BytesIO(png), mimetype="image/png", as_attachment=True, download_name=fname)
    resp.headers["X-Requested-DPI"] = str(o["dpi"])
    resp.headers["X-Effective-DPI"] = str(eff_dpi)
    resp.headers["X-File-Name"] = quote(fname)
    return resp


def _render_set(sess, o, names, skip, folder="", suffix=""):
    """Renderiza todas las piezas no ignoradas con las opciones `o`; devuelve [(ruta_en_zip, png)]."""
    used, files, skipped, dpi_log = {}, [], [], []
    with FITZ_LOCK:
        doc = open_doc(sess, o)
        try:
            clips = get_clips(sess, doc, o)
            for pc in sess["analysis"]["pieces"]:
                if pc["id"] in skip:
                    continue
                clip_l = clips.get(pc["id"])
                if clip_l is None:
                    skipped.append(pc["code"])
                    continue
                page = doc.load_page(pc["page"] - 1)
                png, _w, _h, eff_dpi = render_png(page, fitz.Rect(clip_l), o["dpi"], o["alpha"], o["gray"])
                base = clean_filename(re.sub(r"\.png$", "", str(names.get(pc["id"]) or ""), flags=re.I)
                                      or f"{sess['analysis']['style']}_{pc['default_name']}") + suffix \
                    + _dpi_suffix(o["dpi"], eff_dpi)
                n = used.get(base, 0) + 1
                used[base] = n
                fname = f"{base}.png" if n == 1 else f"{base}_{n}.png"
                files.append((folder + fname, png))
                dpi_log.append({"file": fname, "requested": o["dpi"], "effective": eff_dpi})
        finally:
            doc.close()
    return files, skipped, dpi_log


@app.route("/api/zip/<doc_id>")
def api_zip(doc_id):
    sess, err = _session_or_error(doc_id)
    if err:
        return err
    o = parse_opts(request.args)
    mode = request.args.get("mode", "art")           # art | ref | both
    if mode not in ("art", "ref", "both"):
        mode = "art"
    try:
        names = json.loads(request.args.get("names", "{}"))
    except ValueError:
        names = {}
    try:
        skip = {str(x) for x in json.loads(request.args.get("skip", "[]"))}
    except (ValueError, TypeError):
        skip = set()

    files, art_summary, ref_summary, art_label = [], None, None, str(o["dpi"])
    if mode in ("art", "both"):
        got, _, art_log = _render_set(sess, o, names, skip, "")
        art_label = _dpi_label(o["dpi"], art_log)
        art_summary = _dpi_summary(art_log, o["dpi"])
        folder = f"Arte_PNG_{art_label}DPI/" if mode == "both" else ""
        files += [(folder + fname, data) for fname, data in got]
    if mode in ("ref", "both"):
        # Referencia: arte + patrón + textos tal como se ve el PDF, fondo blanco, en su propia carpeta.
        ref_args = {"text": "1", "trim": "1", "bg": "white", "color": "rgb", "dpi": request.args.get("refdpi", "150")}
        if request.args.get("reflayers") is not None:
            ref_args["layers"] = request.args.get("reflayers")
        ref_o = parse_opts(ref_args)
        got, _, ref_log = _render_set(sess, ref_o, names, skip, REF_FOLDER + "/", "_REF")
        ref_summary = _dpi_summary(ref_log, ref_o["dpi"])
        files += got
    if not files:
        return api_error("No hay piezas con contenido visible para exportar.")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for fname, data in files:
            zf.writestr(fname, data)
    default = {"art": f"{sess['analysis']['style']}_Piezas_PNG_{art_label}DPI",
               "ref": f"{sess['analysis']['style']}_Referencias_con_patron",
               "both": f"{sess['analysis']['style']}_Arte_y_Referencias"}[mode]
    zip_arg = request.args.get("zipname")
    zname = clean_filename(default if zip_arg is None else zip_arg)
    if zip_arg is not None and mode == "art" and art_label != str(o["dpi"]):
        # el nombre sugerido por la interfaz trae el DPI pedido: se sustituye por el real (última aparición)
        head, sep, tail = zname.rpartition(f"{o['dpi']}DPI")
        if sep:
            zname = f"{head}{art_label}DPI{tail}"
    zfile = zname if zname.lower().endswith(".zip") else zname + ".zip"
    resp = send_file(io.BytesIO(buf.getvalue()), mimetype="application/zip", as_attachment=True, download_name=zfile)
    resp.headers["X-File-Name"] = quote(zfile)
    # Resúmenes separados: arte y referencias se renderizan con DPI pedidos distintos (dpi / refdpi).
    total_reduced = 0
    for tag, summ in (("Art", art_summary), ("Ref", ref_summary)):
        if summ is None:
            continue
        resp.headers[f"X-DPI-{tag}-Requested"] = str(summ["requested"])
        resp.headers[f"X-DPI-{tag}-Reduced-Count"] = str(summ["reduced"])
        if summ["min"] is not None:
            resp.headers[f"X-DPI-{tag}-Min"] = str(summ["min"])
        total_reduced += summ["reduced"]
    resp.headers["X-DPI-Reduced-Count"] = str(total_reduced)
    return resp


@app.route("/api/close/<doc_id>", methods=["POST"])
def api_close(doc_id):
    """Botón Limpiar: libera el PDF de la memoria del servidor."""
    with SESSIONS_LOCK:
        SESSIONS.pop(doc_id, None)
    return jsonify({"success": True})


@app.route("/costos")
def costos():
    return Response(COSTOS_HTML.replace("__EXCEL_TEMPLATE_B64__", EXCEL_TEMPLATE_B64), mimetype="text/html")


# Interfaz web optimizada: Fondo gris industrial/carbón oscuro + acentos vibrantes en rojo vivo
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TEGRA Pre-Press Suite - __VERSION__</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: { extend: {
                colors: {
                    brand: { 50: '#fef2f2', 500: '#ef4444', 600: '#dc2626', 700: '#b91c1c', accent: '#ef4444' },
                    darkbg: '#121316', darkcard: '#1a1c23', darkborder: '#2d3139'
                },
                fontFamily: { sans: ['Inter', 'sans-serif'], mono: ['JetBrains Mono', 'monospace'] }
            } }
        }
    </script>
    <style>
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #121316; }
        ::-webkit-scrollbar-thumb { background: #3f4450; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #ef4444; }
        .checkered-pattern {
            background-color: #16181d;
            background-image: linear-gradient(45deg, #121316 25%, transparent 25%), linear-gradient(-45deg, #121316 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #121316 75%), linear-gradient(-45deg, transparent 75%, #121316 75%);
            background-size: 20px 20px;
            background-position: 0 0, 0 10px, 10px -10px, -10px 0px;
        }
        .checkered-light {
            background-color: #2d3139;
            background-image: linear-gradient(45deg, #22252c 25%, transparent 25%), linear-gradient(-45deg, #22252c 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #22252c 75%), linear-gradient(-45deg, transparent 75%, #22252c 75%);
            background-size: 14px 14px;
            background-position: 0 0, 0 7px, 7px -7px, -7px 0px;
        }
    </style>
</head>
<body class="bg-darkbg text-slate-100 font-sans min-h-screen flex flex-col antialiased selection:bg-red-500 selection:text-white">

    <header class="border-b border-darkborder bg-darkcard/95 backdrop-blur sticky top-0 z-50 px-6 py-3 flex items-center justify-between shadow-md">
        <div class="flex items-center space-x-3">
            <img id="brandLogo" src="https://www.tegraglobal.com/careers/public/images/logo.png" alt="TEGRA" class="h-9 w-auto"
                 onerror="this.classList.add('hidden');document.getElementById('brandFallback').classList.remove('hidden')">
            <div id="brandFallback" class="hidden bg-red-600/20 border border-red-500/40 p-2 rounded-lg text-red-500"><i class="fa-solid fa-shirt text-xl"></i></div>
            <div>
                <h1 class="font-bold text-lg leading-none text-white tracking-wide">TEGRA <span class="text-xs font-normal text-red-400">Pre-Press Suite</span></h1>
                <p class="text-xs text-zinc-400 mt-1">Extractor &amp; Separador Vectorial · __VERSION__</p>
            </div>
        </div>
        <nav class="flex items-center gap-1 bg-darkbg border border-darkborder rounded-lg p-1 text-xs font-semibold">
            <button id="tabExtractor" class="px-3 py-1.5 rounded-md bg-red-600 text-white">1 · Extractor</button>
            <button id="tabCostos" class="px-3 py-1.5 rounded-md text-zinc-300 hover:bg-zinc-800">2 · Costos <span id="costBadge" class="hidden ml-1 font-mono text-[10px] bg-zinc-900 border border-zinc-700 rounded-full px-1.5 py-0.5">0</span></button>
        </nav>
        <div id="extractorTools" class="flex items-center space-x-4">
            <div class="bg-darkbg border border-darkborder rounded-lg px-3 py-1.5 flex items-center space-x-2 text-xs">
                <span class="text-zinc-400"><i class="fa-solid fa-gauge-high mr-1 text-red-500"></i> DPI Salida:</span>
                <select id="dpiSelect" class="bg-transparent font-semibold text-red-400 focus:outline-none cursor-pointer">
                    <option value="72">72 DPI (Web)</option>
                    <option value="150">150 DPI (Medio)</option>
                    <option value="300" selected>300 DPI (Impresión HD)</option>
                    <option value="600">600 DPI (Ultra Max)</option>
                </select>
            </div>
            <label class="flex items-center gap-1.5 text-[11px] text-zinc-400 cursor-pointer select-none" title="Algunas plantillas ponen arte relleno (p. ej. las franjas de las mangas) dentro de la capa de talla 5XL. Activado: se toma como arte. Aplica al cargar el PDF.">
                <input type="checkbox" id="chkHiddenArt" checked class="w-3.5 h-3.5 rounded bg-zinc-900 border-zinc-700 text-red-600 focus:ring-red-500"> Arte en capas de talla
            </label>
            <button id="clearBtn" class="bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 text-slate-100 text-xs px-3 py-2 rounded-lg font-semibold transition flex items-center gap-2">
                <i class="fa-solid fa-broom text-red-400"></i> Limpiar
            </button>
            <label class="bg-red-600 hover:bg-red-500 text-white text-xs px-4 py-2 rounded-lg font-semibold transition cursor-pointer flex items-center gap-2 shadow-lg shadow-red-600/30">
                <i class="fa-solid fa-upload"></i> Subir PDF
                <input type="file" id="fileInput" accept=".pdf,application/pdf" class="hidden">
            </label>
        </div>
    </header>

    <div id="viewExtractor" class="flex-1 flex overflow-hidden">

        <!-- Izquierda: ficha, filtros, mapeo -->
        <aside class="w-80 border-r border-darkborder bg-darkcard flex flex-col justify-between overflow-y-auto">
            <div class="p-4 space-y-6">

                <div class="bg-darkbg/80 rounded-xl p-4 border border-darkborder shadow-inner">
                    <h3 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3 flex items-center justify-between">
                        <span>Ficha Técnica Detectada</span>
                        <i class="fa-solid fa-circle-info text-red-500"></i>
                    </h3>
                    <div class="space-y-2 text-sm">
                        <div class="flex justify-between gap-3">
                            <span class="text-zinc-400 text-xs shrink-0">Estilo (Style):</span>
                            <span id="detectedStyle" class="font-mono text-xs font-bold text-red-400 text-right break-all">—</span>
                        </div>
                        <div class="flex justify-between">
                            <span class="text-zinc-400 text-xs">Piezas halladas:</span>
                            <span id="detectedCount" class="font-mono text-xs font-bold text-emerald-400">—</span>
                        </div>
                        <div class="flex justify-between items-center">
                            <span class="text-zinc-400 text-xs">Modo Filtro:</span>
                            <span id="filterModeBadge" class="text-xs text-red-300 font-medium bg-red-950/60 border border-red-900/50 px-2 py-0.5 rounded">Arte Aislado</span>
                        </div>
                        <div class="flex justify-between gap-3">
                            <span class="text-zinc-400 text-xs shrink-0">Detección:</span>
                            <span id="detectedMode" class="text-[11px] text-zinc-300 text-right">—</span>
                        </div>
                    </div>
                    <div class="mt-3 pt-3 border-t border-darkborder space-y-2">
                        <h4 class="text-[10px] uppercase tracking-wider text-zinc-500">Datos para Costos</h4>
                        <div class="flex items-center gap-2">
                            <span class="text-zinc-400 text-xs shrink-0 w-12">Equipo:</span>
                            <input id="teamCode" list="teamCandidates" maxlength="6" placeholder="BUF" class="w-16 bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs font-mono text-red-300 focus:border-red-500 focus:outline-none">
                            <input id="teamName" placeholder="Nombre del equipo" class="flex-1 min-w-0 bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs text-slate-200 focus:border-red-500 focus:outline-none">
                        </div>
                        <datalist id="teamCandidates"></datalist>
                        <div id="teamHint" class="hidden text-[10px] text-amber-300"></div>
                        <div class="flex items-center gap-2">
                            <span class="text-zinc-400 text-xs shrink-0 w-12">Categ.:</span>
                            <select id="catSelect" class="flex-1 min-w-0 bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs text-slate-200 focus:border-red-500 focus:outline-none">
                                <option value="">— elegir —</option><option>NFL Game</option><option>NFL Elite</option><option>NFL Limited</option><option>NCAA</option><option>Football</option>
                            </select>
                        </div>
                        <div id="schematicInfo" class="text-[10px] text-zinc-500 break-words"></div>
                        <div class="flex items-start gap-2">
                            <span class="text-zinc-400 text-xs shrink-0 w-12 pt-0.5">Tallas:</span>
                            <div class="min-w-0">
                                <div id="sizeChips" class="flex flex-wrap gap-1"></div>
                                <div id="sizeSource" class="text-[10px] text-zinc-500 mt-1"></div>
                            </div>
                        </div>
                    </div>
                    <div id="warningsBox" class="hidden mt-3 pt-3 border-t border-darkborder space-y-1 text-[11px] text-amber-300"></div>
                </div>

                <div>
                    <h3 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">Vista de la hoja (solo para mirar)</h3>
                    <div class="space-y-2">
                        <label class="flex items-center justify-between p-2.5 rounded-lg border border-darkborder bg-darkbg/40 cursor-pointer hover:bg-darkbg/80 transition">
                            <div class="flex items-center space-x-3">
                                <input type="checkbox" id="toggleArtwork" checked class="w-4 h-4 rounded text-red-600 focus:ring-red-500 bg-darkbg border-zinc-700">
                                <span class="text-sm font-medium text-slate-200">Arte Gráfico (Vectores)</span>
                            </div>
                            <span class="w-2.5 h-2.5 rounded-full bg-red-500"></span>
                        </label>
                        <label class="flex items-center justify-between p-2.5 rounded-lg border border-darkborder bg-darkbg/40 cursor-pointer hover:bg-darkbg/80 transition">
                            <div class="flex items-center space-x-3">
                                <input type="checkbox" id="togglePatterns" class="w-4 h-4 rounded text-red-600 focus:ring-red-500 bg-darkbg border-zinc-700">
                                <span class="text-sm font-medium text-zinc-400">Líneas de Patrón / Tallas</span>
                            </div>
                            <span class="w-2.5 h-2.5 rounded-full bg-zinc-600 opacity-60"></span>
                        </label>
                        <label class="flex items-center justify-between p-2.5 rounded-lg border border-darkborder bg-darkbg/40 cursor-pointer hover:bg-darkbg/80 transition">
                            <div class="flex items-center space-x-3">
                                <input type="checkbox" id="toggleSpecText" class="w-4 h-4 rounded text-red-600 focus:ring-red-500 bg-darkbg border-zinc-700">
                                <span class="text-sm font-medium text-zinc-400">Textos de Especificación</span>
                            </div>
                            <span class="w-2.5 h-2.5 rounded-full bg-amber-500 opacity-60"></span>
                        </label>
                    </div>

                    <details class="mt-3 group">
                        <summary class="text-[11px] text-red-400 cursor-pointer hover:underline select-none">Capas del PDF <span id="layerCount" class="text-zinc-500"></span></summary>
                        <div id="layerList" class="mt-2 bg-darkbg/40 border border-darkborder rounded-xl p-3 space-y-1 text-xs max-h-56 overflow-y-auto"></div>
                    </details>
                </div>

                <div>
                    <h3 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-1">Capas por destino</h3>
                    <p class="text-[10px] text-zinc-500 mb-2">Los filtros de arriba solo cambian cómo ves la hoja. Aquí eliges qué lleva cada imagen.</p>
                    <div class="space-y-2">
                        <div class="flex items-center justify-between gap-2 p-2.5 rounded-lg border border-darkborder bg-darkbg/40 text-sm">
                            <span class="font-medium text-zinc-300 leading-tight">Recortes<br><span class="text-[10px] text-zinc-500 font-normal">tarjetas y ZIP</span></span>
                            <select id="profCrop" class="bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-red-500 max-w-[150px]">
                                <option value="art" selected>Solo arte</option>
                                <option value="art_pattern">Arte + líneas de patrón</option>
                                <option value="art_pattern_body">Arte + patrón + color de prenda</option>
                                <option value="view">Igual que la vista de la hoja</option>
                            </select>
                        </div>
                        <div class="flex items-center justify-between gap-2 p-2.5 rounded-lg border border-darkborder bg-darkbg/40 text-sm">
                            <span class="font-medium text-zinc-300 leading-tight">Enviar a Costos<br><span class="text-[10px] text-zinc-500 font-normal">imagen que se mide</span></span>
                            <select id="profCost" class="bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-red-500 max-w-[150px]">
                                <option value="art" selected>Solo arte (recomendado)</option>
                                <option value="art_pattern">Arte + líneas de patrón</option>
                                <option value="art_pattern_body">Arte + patrón + color de prenda</option>
                                <option value="crop">Igual que los recortes</option>
                            </select>
                        </div>
                        <div id="profCostHint" class="hidden text-[10px] text-amber-300">Ojo: las líneas de patrón cuentan como tinta en Costos y el área será la del patrón, no la del arte.</div>
                        <div class="flex items-center justify-between gap-2 p-2.5 rounded-lg border border-darkborder bg-darkbg/40 text-sm">
                            <span class="font-medium text-zinc-300 leading-tight">Referencia<br><span class="text-[10px] text-zinc-500 font-normal">imagen del Excel</span></span>
                            <select id="profRef" class="bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-red-500 max-w-[150px]">
                                <option value="art_pattern_body" selected>Arte + patrón + color de prenda</option>
                                <option value="art_pattern">Arte + líneas de patrón</option>
                                <option value="art">Solo arte</option>
                            </select>
                        </div>
                    </div>
                </div>

                <div>
                    <h3 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">Opciones de Exportación</h3>
                    <div class="space-y-2">
                        <label class="flex items-center justify-between p-2.5 rounded-lg border border-darkborder bg-darkbg/40 cursor-pointer hover:bg-darkbg/80 transition">
                            <div class="flex items-center space-x-3">
                                <input type="checkbox" id="toggleTrim" checked class="w-4 h-4 rounded text-red-600 focus:ring-red-500 bg-darkbg border-zinc-700">
                                <span class="text-sm font-medium text-slate-200">Ajustar tamaño al arte</span>
                            </div>
                            <i class="fa-solid fa-crop-simple text-xs text-red-400"></i>
                        </label>
                        <div class="flex items-center justify-between p-2.5 rounded-lg border border-darkborder bg-darkbg/40 text-sm">
                            <span class="font-medium text-zinc-300">Fondo</span>
                            <select id="bgSelect" class="bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-red-500">
                                <option value="transparent" selected>Transparente</option>
                                <option value="white">Blanco</option>
                            </select>
                        </div>
                    </div>
                </div>

                <div>
                    <div class="flex justify-between items-center mb-2">
                        <h3 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Mapeo de Nombres</h3>
                        <button id="resetMappingBtn" class="text-[10px] text-red-400 hover:underline">Restablecer</button>
                    </div>
                    <div class="bg-darkbg/40 border border-darkborder rounded-xl p-3 space-y-2 text-xs font-mono max-h-56 overflow-y-auto" id="mappingList"></div>
                    <div class="flex items-center gap-2 mt-2">
                        <input id="newMapCode" placeholder="Código" class="w-24 bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs text-slate-200 focus:border-red-500 focus:outline-none">
                        <input id="newMapName" placeholder="Nombre" class="flex-1 min-w-0 bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs text-slate-200 focus:border-red-500 focus:outline-none">
                        <button id="addMapBtn" class="bg-zinc-800 hover:bg-zinc-700 text-slate-100 rounded px-2 py-1 text-xs"><i class="fa-solid fa-plus text-red-400"></i></button>
                    </div>
                </div>
            </div>

            <div class="p-4 border-t border-darkborder bg-darkbg/60 space-y-2">
                <button id="sendCostBtn" disabled class="w-full bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-2.5 px-4 rounded-lg text-sm transition shadow-lg shadow-emerald-600/20 flex items-center justify-center gap-2">
                    <i class="fa-solid fa-calculator"></i>
                    <span id="sendCostLabel">Enviar a Costos</span>
                </button>
                <label class="flex items-center gap-1.5 text-[11px] text-zinc-400 cursor-pointer select-none">
                    <input type="checkbox" id="chkSendRefs" checked class="w-3.5 h-3.5 rounded bg-zinc-900 border-zinc-700 text-red-600 focus:ring-red-500">
                    Enviar también la referencia con patrón (para pegarla en el Excel)
                </label>
                <button id="downloadAllZipBtn" disabled class="w-full bg-red-600 hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-2.5 px-4 rounded-lg text-sm transition shadow-lg shadow-red-600/20 flex items-center justify-center gap-2">
                    <i class="fa-solid fa-file-zipper"></i>
                    <span id="zipBtnLabel">Exportar Todo (.ZIP a 300 DPI)</span>
                </button>
                <button id="refZipBtn" disabled class="w-full bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 disabled:cursor-not-allowed text-slate-100 border border-zinc-700 font-semibold py-2 px-4 rounded-lg text-sm transition flex items-center justify-center gap-2">
                    <i class="fa-solid fa-layer-group text-red-400"></i>
                    <span>Referencias con patrón (.ZIP)</span>
                </button>
                <div class="flex items-center justify-between gap-2 text-[11px] text-zinc-400">
                    <label class="flex items-center gap-1.5 cursor-pointer select-none">
                        <input type="checkbox" id="chkBoth" class="w-3.5 h-3.5 rounded bg-zinc-900 border-zinc-700 text-red-600 focus:ring-red-500">
                        Incluirlas en el ZIP (carpeta aparte)
                    </label>
                    <select id="refDpiSelect" class="bg-zinc-900 border border-zinc-700 rounded px-1.5 py-0.5 text-[11px] text-slate-200 focus:outline-none focus:border-red-500">
                        <option value="100">100 DPI</option>
                        <option value="150" selected>150 DPI</option>
                        <option value="300">300 DPI</option>
                    </select>
                </div>
            </div>
        </aside>

        <!-- Centro: hoja -->
        <main class="flex-1 flex flex-col bg-[#0d0e11] relative overflow-hidden">
            <div class="border-b border-darkborder bg-darkcard/50 px-4 py-2 flex items-center justify-between text-xs">
                <div class="flex items-center space-x-3">
                    <span class="text-zinc-400"><i class="fa-solid fa-eye mr-1 text-red-500"></i> Modo Vista:</span>
                    <button id="viewAllBtn" class="px-2.5 py-1 rounded bg-zinc-800 text-zinc-300 hover:bg-zinc-700">Hoja Completa</button>
                    <button id="viewIsolatedBtn" class="px-2.5 py-1 rounded bg-red-600 text-white font-semibold">Piezas Aisladas</button>
                    <select id="pageSelect" class="hidden bg-zinc-900 border border-zinc-700 rounded px-2 py-1 text-xs text-slate-200 focus:border-red-500"></select>
                </div>
                <div id="fileInfoLabel" class="font-mono text-zinc-400">Archivo: <span class="text-zinc-500">ninguno</span></div>
            </div>

            <div class="flex-1 relative overflow-auto checkered-pattern flex items-center justify-center p-8" id="viewportContainer">
                <div id="emptyState" class="text-center space-y-4 max-w-md">
                    <div class="text-5xl text-zinc-700"><i class="fa-solid fa-file-pdf"></i></div>
                    <p class="text-zinc-300 font-semibold">Arrastra aquí tu PDF de patrones</p>
                    <p class="text-xs text-zinc-500">o usa el botón “Subir PDF”. Se detectan las piezas, se lee su nombre y se exporta un PNG por pieza.</p>
                </div>
                <div id="canvasWrap" class="hidden relative shadow-2xl rounded-lg border border-zinc-700 overflow-hidden bg-white">
                    <canvas id="mainCanvas" class="block cursor-crosshair" style="max-width:100%;height:auto"></canvas>
                </div>
                <div id="loaderOverlay" class="absolute inset-0 bg-darkbg/85 backdrop-blur-sm flex flex-col items-center justify-center hidden z-20">
                    <div class="w-12 h-12 border-4 border-red-500 border-t-transparent rounded-full animate-spin mb-3"></div>
                    <p id="loaderText" class="text-sm font-medium text-zinc-200">Procesando vectores...</p>
                </div>
            </div>
        </main>

        <!-- Derecha: piezas -->
        <aside class="w-96 border-l border-darkborder bg-darkcard flex flex-col overflow-y-auto">
            <div class="p-4 border-b border-darkborder flex items-center justify-between">
                <h3 class="font-bold text-sm text-slate-200 flex items-center gap-2">
                    <i class="fa-solid fa-shapes text-red-500"></i> Piezas Extraídas
                </h3>
                <span class="text-xs bg-zinc-900 border border-zinc-700 text-red-400 px-2 py-0.5 rounded-full font-mono" id="pieceBadgeCount">0</span>
            </div>
            <div class="flex-1 p-4 space-y-4" id="piecesContainer">
                <p class="text-xs text-zinc-500">Sube un PDF para ver las piezas.</p>
            </div>
        </aside>
    </div>

    <div id="viewCostos" class="hidden" style="height:calc(100vh - 69px)">
        <iframe id="costosFrame" src="/costos?embed=1" class="w-full h-full border-0" style="background:#1a1a1a"></iframe>
    </div>

    <div id="toast" class="fixed bottom-4 right-4 bg-zinc-900 border border-zinc-700 text-slate-100 text-xs px-4 py-3 rounded-lg shadow-xl opacity-0 transform translate-y-4 transition-all duration-300 pointer-events-none z-50 flex items-center gap-3 max-w-sm">
        <i id="toastIcon" class="fa-solid fa-circle-check text-emerald-400 text-base"></i>
        <span id="toastMessage">Operación realizada</span>
    </div>

    <script>
        const $ = id => document.getElementById(id);
        const GROUPS = [
            { key: 'art', label: 'Arte', dot: 'bg-red-500' },
            { key: 'pattern', label: 'Patrón / Tallas', dot: 'bg-zinc-500' },
            { key: 'spec', label: 'Especificación', dot: 'bg-amber-500' },
        ];

        const state = {
            dpi: 300, docId: null, fileName: '', styleRaw: '', style: '', mode: '',
            pages: [], page: 1, layers: [], pieces: [], clips: {}, activePiece: null,
            showSpecText: false, viewMode: 'isolated', sheetImg: null, sheetScale: 1,
            defaultMap: {}, map: {}, trimAvailable: true,
            skipped: new Set(), noRef: new Set(), pieceNames: {}, category: '', schematic: '', sending: false, teamCode: '', teamName: '', teamCatalog: {}, userTeams: {}, sizesDetected: [], sizesSel: new Set(),
        };

        const canvas = $('mainCanvas');
        const ctx = canvas.getContext('2d');

        const normCode = c => (c || '').toUpperCase().replace(/\s+/g, ' ').trim();
        const cleanName = s => (s || '').replace(/[\\/:*?"<>|]+/g, '-').replace(/\s+/g, '_').replace(/_+/g, '_').replace(/^[._-]+|[._-]+$/g, '') || 'sin_nombre';
        const translated = p => state.map[normCode(p.code)] || p.default_name || p.code;
        // Nombre corregido a mano en la tarjeta de ESA pieza (manda sobre el mapeo por código)
        const customName = p => ((state.pieceNames && state.pieceNames[p.id]) || '').trim();
        const autoLabel = p => translated(p) + (p.parts > 1 ? ` (${p.part}/${p.parts})` : '');
        const pieceTitle = p => customName(p) || autoLabel(p);
        function baseName(p) {
            const c = customName(p);
            if (c) return `${state.style}_${cleanName(c)}`;
            return `${state.style}_${cleanName(translated(p))}` + (p.parts > 1 ? `_${p.part}` : '');
        }
        function fileNames() {
            const used = {}, out = {};
            state.pieces.forEach(p => {
                const b = baseName(p);
                used[b] = (used[b] || 0) + 1;
                out[p.id] = used[b] === 1 ? `${b}.png` : `${b}_${used[b]}.png`;
            });
            return out;
        }

        function layersParam() {
            return state.layers.filter(l => l.on).map(l => l.number).join(',');
        }
        function baseQuery() {
            const q = new URLSearchParams();
            if (state.layers.length) q.set('layers', layersParam());
            q.set('text', state.showSpecText ? '1' : '0');
            q.set('trim', $('toggleTrim').checked ? '1' : '0');
            return q;
        }
        // ---- Capas por destino: cada salida elige sus capas, independiente de la vista de la hoja ----
        const isBodyLayer = l => /body\s*background/i.test(l.name || '');
        function profileNums(prof) {
            let ls = state.layers.filter(l => l.group === 'art' && l.on);
            if (!ls.length) ls = state.layers.filter(l => l.group === 'art');
            if (prof !== 'art') {
                const pats = state.layers.filter(l => l.group === 'pattern' && !isBodyLayer(l));
                const dflt = pats.filter(l => l.default_on);
                ls = ls.concat(dflt.length ? dflt : pats);
            }
            if (prof === 'art_pattern_body') ls = ls.concat(state.layers.filter(isBodyLayer));
            if (!ls.length) ls = state.layers.filter(l => l.on);
            return ls.map(l => l.number).join(',');
        }
        function profileQuery(prof, text) {
            const q = new URLSearchParams();
            if (state.layers.length) q.set('layers', profileNums(prof));
            q.set('text', text ? '1' : '0');
            q.set('trim', $('toggleTrim').checked ? '1' : '0');
            return q;
        }
        function cropQuery() {
            const prof = $('profCrop').value;
            return prof === 'view' ? baseQuery() : profileQuery(prof, false);
        }
        function exportQuery() {
            const q = cropQuery();
            q.set('dpi', state.dpi);
            q.set('bg', $('bgSelect').value);
            return q;
        }
        async function getJSON(url) {
            const r = await fetch(url);
            let d; try { d = await r.json(); } catch { d = { success: false, error: 'Respuesta inválida del servidor.' }; }
            if (!d.success) throw new Error(d.error || 'Error del servidor');
            return d;
        }
        function loadImage(url) {
            return new Promise((resolve, reject) => {
                const img = new Image();
                img.onload = () => resolve(img);
                img.onerror = () => reject(new Error('No se pudo renderizar la hoja'));
                img.src = url;
            });
        }

        async function uploadFile(file) {
            if (!file) return;
            if (!/\.pdf$/i.test(file.name)) { showToast('Solo se admiten archivos PDF.', 'error'); return; }
            showLoader(`Analizando vectores de ${file.name}...`);
            const fd = new FormData(); fd.append('file', file); fd.append('hidden_art', $('chkHiddenArt').checked ? '1' : '0');
            try {
                const res = await fetch('/api/upload', { method: 'POST', body: fd });
                let data; try { data = await res.json(); } catch { data = { success: false, error: 'Respuesta inválida.' }; }
                if (!data.success) throw new Error(data.error);

                Object.assign(state, {
                    docId: data.doc_id, fileName: data.filename, styleRaw: data.style_raw || data.style,
                    style: data.style, mode: data.mode, pages: data.pages, page: 1, pieces: data.pieces,
                    clips: {}, activePiece: null, trimAvailable: data.trim_available,
                    defaultMap: Object.fromEntries(Object.entries(data.dictionary).map(([k, v]) => [normCode(k), v])),
                });
                state.map = { ...state.defaultMap };
                state.layers = data.layers.map(l => ({ ...l, on: l.default_on }));
                state.skipped = new Set(); state.noRef = new Set(); state.pieceNames = {};
                initCostData(data);
                $('toggleArtwork').checked = true; $('togglePatterns').checked = false; $('toggleSpecText').checked = false;
                state.showSpecText = false;
                applyGroup('art', true); applyGroup('pattern', false); applyGroup('spec', false);
                if (!state.trimAvailable) { $('toggleTrim').checked = false; $('toggleTrim').disabled = true; }

                $('fileInfoLabel').innerHTML = `Archivo: <span class="text-red-400 font-semibold"></span>`;
                $('fileInfoLabel').querySelector('span').textContent = data.filename;
                $('detectedStyle').textContent = state.styleRaw;
                $('detectedCount').textContent = `${data.pieces.length} Piezas`;
                $('detectedMode').textContent = data.mode;
                $('pieceBadgeCount').textContent = data.pieces.length;
                $('emptyState').classList.add('hidden');
                $('downloadAllZipBtn').disabled = false; $('refZipBtn').disabled = false; $('sendCostBtn').disabled = false;

                const ps = $('pageSelect');
                ps.innerHTML = data.pages.map(p => `<option value="${p.page}">Página ${p.page}</option>`).join('');
                ps.classList.toggle('hidden', data.pages.length < 2);

                showWarnings(data.warnings);
                setViewMode('isolated', false);
                initMappingUI(); renderLayerList(); updateModeBadge();
                await refreshAll();
                showToast(`${data.pieces.length} piezas detectadas`);
            } catch (err) {
                hideLoader();
                showToast(err.message, 'error');
            }
        }

        let refreshSeq = 0, refreshTimer = null;
        function scheduleRefresh() { clearTimeout(refreshTimer); refreshTimer = setTimeout(refreshAll, 250); }

        async function refreshAll() {
            if (!state.docId) return;
            const seq = ++refreshSeq;
            showLoader('Actualizando vista...');
            try {
                const q = cropQuery();
                const sheetQ = new URLSearchParams(baseQuery()); sheetQ.set('page', state.page); sheetQ.set('max', 2000);
                const [pcs, img] = await Promise.all([
                    getJSON(`/api/pieces/${state.docId}?${q}`),
                    loadImage(`/api/sheet/${state.docId}?${sheetQ}`),
                ]);
                if (seq !== refreshSeq) return;
                state.clips = Object.fromEntries(pcs.pieces.map(p => [p.id, p.clip]));
                state.sheetImg = img;
                const pg = state.pages.find(p => p.page === state.page) || state.pages[0];
                state.sheetScale = img.naturalWidth / pg.w;
                canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;
                $('canvasWrap').classList.remove('hidden');
                renderCanvas();
                renderPiecesList(q);
                if (pcs.warnings.length) showToast(pcs.warnings[0], 'error');
                hideLoader();
            } catch (err) {
                if (seq === refreshSeq) { hideLoader(); showToast(err.message, 'error'); }
            }
        }

        function boxOf(p) { return state.clips[p.id] || p.rect; }

        function renderCanvas() {
            if (!state.sheetImg) return;
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.drawImage(state.sheetImg, 0, 0);
            const s = state.sheetScale;
            state.pieces.filter(p => p.page === state.page).forEach(p => {
                const b = boxOf(p), active = state.activePiece === p.id, empty = !state.clips[p.id];
                const x = b[0] * s, y = b[1] * s, w = (b[2] - b[0]) * s, h = (b[3] - b[1]) * s;
                ctx.save();
                ctx.setLineDash([8, 6]);
                ctx.lineWidth = active ? 3 : 1.5;
                ctx.strokeStyle = active ? '#ef4444' : ((empty || state.skipped.has(p.id)) ? 'rgba(161,161,170,0.7)' : 'rgba(239,68,68,0.55)');
                ctx.strokeRect(x, y, w, h);
                ctx.setLineDash([]);
                const label = (state.skipped.has(p.id) ? '✕ ' : '') + (customName(p) || (translated(p) + (p.parts > 1 ? ` ${p.part}` : '')));
                ctx.font = '600 13px Inter, sans-serif';
                const tw = ctx.measureText(label).width + 12;
                const ly = y - 22 >= 0 ? y - 22 : y + 2;
                ctx.fillStyle = active ? '#dc2626' : 'rgba(26,28,35,0.95)';
                ctx.fillRect(x, ly, tw, 20);
                ctx.fillStyle = '#fff';
                ctx.fillText(label, x + 6, ly + 14);
                ctx.restore();
            });
        }

        canvas.addEventListener('click', e => {
            const r = canvas.getBoundingClientRect();
            const x = (e.clientX - r.left) * canvas.width / r.width, y = (e.clientY - r.top) * canvas.height / r.height;
            const s = state.sheetScale;
            const hits = state.pieces.filter(p => p.page === state.page).filter(p => {
                const b = boxOf(p); return x >= b[0] * s && x <= b[2] * s && y >= b[1] * s && y <= b[3] * s;
            }).sort((a, b) => (boxOf(a)[2] - boxOf(a)[0]) * (boxOf(a)[3] - boxOf(a)[1]) - (boxOf(b)[2] - boxOf(b)[0]) * (boxOf(b)[3] - boxOf(b)[1]));
            if (hits.length) selectPiece(hits[0].id, true);
        });

        function selectPiece(id, scroll) {
            state.activePiece = id;
            renderCanvas(); highlightActive();
            if (scroll) { const c = $('card-' + id); if (c) c.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
        }

        function renderPiecesList(q) {
            const box = $('piecesContainer');
            box.innerHTML = '';
            const thumbQ = new URLSearchParams(q); thumbQ.set('preview', '1');
            state.pieces.forEach(p => {
                const card = document.createElement('div');
                card.id = 'card-' + p.id;
                card.dataset.pid = p.id;
                card.className = 'p-3 rounded-xl border transition cursor-pointer flex flex-col justify-between bg-darkbg/50 border-darkborder hover:border-red-500/50';
                const empty = !state.clips[p.id];
                card.innerHTML = `
                    <div class="flex items-start justify-between mb-2 gap-2">
                        <div class="min-w-0">
                            <span class="card-code text-[10px] font-mono text-red-400 bg-red-950/60 border border-red-900/40 px-1.5 py-0.5 rounded"></span>
                            <span class="card-tallas hidden text-[10px] font-mono text-amber-300 bg-amber-950/50 border border-amber-900/40 px-1.5 py-0.5 rounded ml-1"></span>
                            <input type="text" spellcheck="false" class="card-title w-full bg-transparent border border-transparent hover:border-zinc-700 focus:border-red-500 focus:bg-zinc-900 rounded px-1 -mx-1 mt-1 font-bold text-sm text-slate-100 focus:outline-none" title="Clic para corregir el nombre de esta pieza (Enter guarda, Esc cancela, vacío = automático)">
                        </div>
                        <span class="card-size text-xs text-zinc-400 font-mono shrink-0"></span>
                    </div>
                    <div class="checkered-light rounded mb-2 h-28 flex items-center justify-center overflow-hidden">
                        ${empty ? '<span class="text-[11px] text-zinc-400 bg-zinc-900 px-2 py-1 rounded">Sin contenido visible</span>'
                                : `<img loading="lazy" class="max-h-full max-w-full object-contain" alt="">`}
                    </div>
                    <div class="bg-zinc-900 border border-zinc-800 rounded p-2 mb-3 text-[11px] font-mono text-zinc-300 truncate">
                        <i class="fa-regular fa-file-image mr-1 text-red-500"></i><span class="card-file"></span>
                    </div>
                    <button class="dl-btn flex-1 bg-red-600/20 hover:bg-red-600/40 text-red-300 border border-red-500/30 font-medium py-1.5 px-3 rounded-lg text-xs transition flex items-center justify-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed" ${empty ? 'disabled' : ''}>
                        <i class="fa-solid fa-download"></i><span class="dl-label"></span>
                    </button>
                    <label class="flex items-center gap-2 mt-2 text-[11px] text-zinc-400 cursor-pointer select-none"><input type="checkbox" class="skip-cb w-3.5 h-3.5 rounded bg-zinc-900 border-zinc-700 text-red-600 focus:ring-red-500"> Ignorar (no va a Costos ni al ZIP)</label>
                    <label class="flex items-center gap-2 mt-1 text-[11px] text-zinc-400 cursor-pointer select-none"><input type="checkbox" checked class="ref-cb w-3.5 h-3.5 rounded bg-zinc-900 border-zinc-700 text-red-600 focus:ring-red-500"> Referencia con patrón en el Excel</label>`;
                const img = card.querySelector('img');
                if (img) img.src = `/api/piece/${state.docId}/${p.id}.png?${thumbQ}`;
                card.querySelector('.dl-btn').addEventListener('click', () => downloadPiece(p.id));
                const ti = card.querySelector('.card-title');
                ti.addEventListener('click', e => e.stopPropagation());
                ti.addEventListener('keydown', e => {
                    if (e.key === 'Enter') ti.blur();
                    if (e.key === 'Escape') { ti.value = pieceTitle(p); ti.blur(); }
                });
                ti.addEventListener('change', () => {
                    const v = ti.value.trim();
                    if (!v || v === autoLabel(p)) delete state.pieceNames[p.id]; else state.pieceNames[p.id] = v;
                    ti.value = pieceTitle(p);
                    updateCardTexts(); renderCanvas();
                    showToast(customName(p) ? `Nombre de la pieza: ${customName(p)}` : `Nombre automático: ${autoLabel(p)}`);
                });
                const sk = card.querySelector('.skip-cb');
                sk.checked = state.skipped.has(p.id);
                card.classList.toggle('opacity-40', sk.checked);
                sk.addEventListener('change', () => {
                    if (sk.checked) state.skipped.add(p.id); else state.skipped.delete(p.id);
                    card.classList.toggle('opacity-40', sk.checked);
                    updateSendLabel(); renderCanvas();
                });
                const rf = card.querySelector('.ref-cb');
                rf.checked = !state.noRef.has(p.id);
                rf.addEventListener('change', () => { if (rf.checked) state.noRef.delete(p.id); else state.noRef.add(p.id); });
                card.addEventListener('click', e => { if (!e.target.closest('button')) selectPiece(p.id, false); });
                box.appendChild(card);
            });
            updateCardTexts(); highlightActive();
        }

        function updateCardTexts() {
            const names = fileNames();
            state.pieces.forEach(p => {
                const card = $('card-' + p.id); if (!card) return;
                card.querySelector('.card-code').textContent = `Código: ${p.code}`;
                const tg = card.querySelector('.card-tallas');
                if (p.sizes_label) { tg.textContent = `Tallas: ${p.sizes_label}`; tg.title = `Esta pieza comprende las tallas ${p.sizes.join(', ')} (columna SIZE en Costos y Excel)`; tg.classList.remove('hidden'); }
                const ti = card.querySelector('.card-title');
                if (document.activeElement !== ti) ti.value = pieceTitle(p);
                ti.classList.toggle('text-amber-300', !!customName(p));
                card.querySelector('.card-file').textContent = names[p.id];
                const c = state.clips[p.id];
                card.querySelector('.card-size').textContent = c
                    ? `${Math.round((c[2] - c[0]) * state.dpi / 72)}x${Math.round((c[3] - c[1]) * state.dpi / 72)}px` : '—';
                card.querySelector('.dl-label').textContent = `PNG (${state.dpi} DPI)`;
            });
            $('zipBtnLabel').textContent = `Exportar Todo (.ZIP a ${state.dpi} DPI)`;
            updateSendLabel();
        }

        function highlightActive() {
            document.querySelectorAll('#piecesContainer > [data-pid]').forEach(c => {
                const on = c.dataset.pid === state.activePiece;
                c.classList.toggle('bg-red-950/30', on); c.classList.toggle('border-red-500', on); c.classList.toggle('shadow-md', on);
                c.classList.toggle('bg-darkbg/50', !on); c.classList.toggle('border-darkborder', !on);
            });
        }

        async function downloadPiece(id) {
            const name = fileNames()[id];
            const q = exportQuery(); q.set('name', name);
            showToast(`Exportando ${name}...`);
            try {
                const res = await fetch(`/api/piece/${state.docId}/${id}.png?${q}`);
                if (!res.ok) {
                    let msg = 'No se pudo exportar la pieza';
                    try { msg = (await res.json()).error || msg; } catch {}
                    throw new Error(msg);
                }
                const blob = await res.blob();
                const fn = res.headers.get('X-File-Name');
                const finalName = fn ? decodeURIComponent(fn) : name;
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob); a.download = finalName;
                document.body.appendChild(a); a.click(); a.remove();
                setTimeout(() => URL.revokeObjectURL(a.href), 10000);
                const eff = parseInt(res.headers.get('X-Effective-DPI') || '0', 10);
                const req = parseInt(res.headers.get('X-Requested-DPI') || '0', 10);
                if (eff && req && eff < req) {
                    const msg = `${finalName}: se exportó a ${eff} DPI (pedido: ${req} DPI) porque la pieza supera el límite de píxeles.`;
                    appendWarning(msg); showToast(msg, 'error');
                }
            } catch (err) { showToast(err.message, 'error'); }
        }

        function refLayersParam() {
            // Referencia del Excel: sus propias capas (por defecto arte + patrón + color de prenda)
            if (!state.layers.length) return null;
            return profileNums($('profRef').value);
        }
        function costQuery() {
            // Imagen que Costos mide (tinta, píxeles, pulgadas): 300 DPI y fondo transparente.
            const sel = $('profCost').value;
            const prof = sel === 'crop' ? $('profCrop').value : sel;
            const q = prof === 'view' ? baseQuery() : profileQuery(prof, false);
            q.set('trim', state.trimAvailable ? '1' : '0');
            q.set('dpi', '300'); q.set('bg', 'transparent');
            return q;
        }

        function refQuery() {
            // Referencia para el Excel: arte + patrón + textos, fondo blanco (Costos la reduce a tamaño de referencia)
            const q = new URLSearchParams();
            const rl = refLayersParam(); if (rl !== null) q.set('layers', rl);
            q.set('text', '1'); q.set('trim', state.trimAvailable ? '1' : '0'); q.set('dpi', '150'); q.set('bg', 'white');
            return q;
        }

        async function exportZip(mode) {
            if (!state.docId) return;
            if (state.pieces.length - state.skipped.size <= 0) { showToast('Todas las piezas están ignoradas.', 'error'); return; }
            const what = mode === 'ref' ? 'referencias con patrón' : mode === 'both' ? 'arte + referencias' : `ZIP a ${state.dpi} DPI`;
            showLoader(`Generando ${what}...`);
            try {
                const q = exportQuery();
                q.set('names', JSON.stringify(fileNames()));
                q.set('skip', JSON.stringify(Array.from(state.skipped)));
                q.set('mode', mode);
                if (mode !== 'art') {
                    q.set('refdpi', $('refDpiSelect').value);
                    const rl = refLayersParam();
                    if (rl !== null) q.set('reflayers', rl);
                }
                const zipName = mode === 'ref' ? `${state.style}_Referencias_con_patron.zip`
                    : mode === 'both' ? `${state.style}_Arte_y_Referencias.zip`
                    : `${state.style}_Piezas_PNG_${state.dpi}DPI.zip`;
                q.set('zipname', zipName);
                const res = await fetch(`/api/zip/${state.docId}?${q}`);
                if (!res.ok) {
                    let msg = 'No se pudo generar el ZIP';
                    try { msg = (await res.json()).error || msg; } catch {}
                    throw new Error(msg);
                }
                const blob = await res.blob();
                const fn = res.headers.get('X-File-Name');
                const finalZipName = fn ? decodeURIComponent(fn) : zipName;
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob); a.download = finalZipName;
                document.body.appendChild(a); a.click(); a.remove();
                setTimeout(() => URL.revokeObjectURL(a.href), 10000);
                hideLoader();
                const nRed = parseInt(res.headers.get('X-DPI-Reduced-Count') || '0', 10);
                if (nRed > 0) {
                    const partes = [];
                    for (const [k, lbl] of [['Art', 'arte'], ['Ref', 'referencias']]) {
                        const n = parseInt(res.headers.get(`X-DPI-${k}-Reduced-Count`) || '0', 10);
                        if (n > 0) partes.push(`${n} de ${lbl} (mínimo ${res.headers.get(`X-DPI-${k}-Min`)} DPI, pedido ${res.headers.get(`X-DPI-${k}-Requested`)} DPI)`);
                    }
                    const msg = `${nRed} archivo(s) del ZIP se generaron con menos DPI del pedido: ${partes.join('; ')}. Superan el límite de píxeles y llevan el sufijo _<DPI>DPI en el nombre.`;
                    appendWarning(msg);
                    showToast(`ZIP descargado (${(blob.size / 1048576).toFixed(1)} MB). ⚠ ${msg}`, 'error');
                } else {
                    showToast(`ZIP descargado (${(blob.size / 1048576).toFixed(1)} MB)`);
                }
            } catch (err) { hideLoader(); showToast(err.message, 'error'); }
        }
        const exportAllZip = () => exportZip($('chkBoth').checked ? 'both' : 'art');
        const exportRefZip = () => exportZip('ref');

        function applyGroup(group, checked) {
            const ls = state.layers.filter(l => l.group === group);
            const anyDefault = ls.some(l => l.default_on);
            ls.forEach(l => { l.on = checked ? (anyDefault ? l.default_on : true) : false; });
        }
        function syncToggles() {
            const set = (group, el) => {
                const ls = state.layers.filter(l => l.group === group);
                if (ls.length) el.checked = ls.some(l => l.on);
            };
            set('art', $('toggleArtwork')); set('pattern', $('togglePatterns')); set('spec', $('toggleSpecText'));
            state.showSpecText = $('toggleSpecText').checked;
            updateModeBadge();
        }
        function updateModeBadge() {
            const a = $('toggleArtwork').checked, p = $('togglePatterns').checked, t = $('toggleSpecText').checked;
            $('filterModeBadge').textContent = (a && !p && !t) ? 'Arte Aislado' : (a && p && t) ? 'Hoja Completa' : 'Personalizado';
        }
        function renderLayerList() {
            const box = $('layerList'); box.innerHTML = '';
            $('layerCount').textContent = state.layers.length ? `(${state.layers.length})` : '(sin capas)';
            if (!state.layers.length) { box.innerHTML = '<p class="text-zinc-500">Este PDF no tiene capas.</p>'; return; }
            GROUPS.forEach(g => {
                const ls = state.layers.filter(l => l.group === g.key);
                if (!ls.length) return;
                const h = document.createElement('div');
                h.className = 'flex items-center gap-2 text-[10px] uppercase tracking-wider text-zinc-500 mt-2 first:mt-0';
                h.innerHTML = `<span class="w-2 h-2 rounded-full ${g.dot}"></span>${g.label}`;
                box.appendChild(h);
                ls.forEach(l => {
                    const row = document.createElement('label');
                    row.className = 'flex items-center gap-2 text-zinc-300 cursor-pointer';
                    row.innerHTML = `<input type="checkbox" class="w-3.5 h-3.5 rounded bg-zinc-900 border-zinc-700 text-red-600 focus:ring-red-500"><span class="truncate"></span>`;
                    const cb = row.querySelector('input'); cb.checked = l.on;
                    row.querySelector('span').textContent = l.name + (l.default_on ? '' : '  (apagada)');
                    cb.addEventListener('change', () => { l.on = cb.checked; syncToggles(); scheduleRefresh(); });
                    box.appendChild(row);
                });
            });
        }
        function setViewMode(mode, refresh = true) {
            state.viewMode = mode;
            const all = mode === 'all';
            $('viewAllBtn').className = all ? 'px-2.5 py-1 rounded bg-red-600 text-white font-semibold' : 'px-2.5 py-1 rounded bg-zinc-800 text-zinc-300 hover:bg-zinc-700';
            $('viewIsolatedBtn').className = !all ? 'px-2.5 py-1 rounded bg-red-600 text-white font-semibold' : 'px-2.5 py-1 rounded bg-zinc-800 text-zinc-300 hover:bg-zinc-700';
            if (!refresh) return;
            applyGroup('art', true); applyGroup('pattern', all); applyGroup('spec', all);
            $('toggleArtwork').checked = true; $('togglePatterns').checked = all; $('toggleSpecText').checked = all;
            state.showSpecText = all;
            renderLayerList(); updateModeBadge(); scheduleRefresh();
        }

        function initMappingUI() {
            const list = $('mappingList'); list.innerHTML = '';
            const detected = [...new Set(state.pieces.map(p => normCode(p.code)))];
            const head = txt => {
                const h = document.createElement('div');
                h.className = 'text-[10px] uppercase tracking-wider text-zinc-500 font-sans';
                h.textContent = txt; list.appendChild(h);
            };
            const addRow = (code, value) => {
                const item = document.createElement('div');
                item.className = 'flex items-center justify-between gap-2 bg-zinc-900/80 p-2 rounded border border-zinc-800';
                item.innerHTML = `<span class="text-red-400 font-bold truncate"></span>
                    <i class="fa-solid fa-arrow-right text-[10px] text-zinc-600"></i>
                    <input type="text" class="map-input bg-zinc-800 border border-zinc-700 rounded px-2 py-0.5 text-xs text-slate-200 w-32 focus:border-red-500 focus:outline-none">`;
                item.querySelector('span').textContent = code;
                const inp = item.querySelector('input'); inp.value = value;
                inp.addEventListener('change', () => {
                    const v = inp.value.trim();
                    if (v) state.map[code] = v;
                    else if (state.defaultMap[code]) state.map[code] = state.defaultMap[code];
                    else delete state.map[code];
                    inp.value = state.map[code] || (state.pieces.find(p => normCode(p.code) === code) || {}).default_name || '';
                    updateCardTexts(); renderCanvas();
                    showToast(`Mapeo actualizado: ${code} → ${inp.value}`);
                });
                list.appendChild(item);
            };
            if (detected.length) {
                head('En este PDF');
                detected.forEach(code => {
                    const p0 = state.pieces.find(p => normCode(p.code) === code);
                    addRow(code, state.map[code] || p0.default_name || code);
                });
                head('Diccionario');
            }
            Object.entries(state.map).filter(([code]) => !detected.includes(code)).forEach(([code, value]) => addRow(code, value));
        }

        function showWarnings(ws) {
            const box = $('warningsBox'); box.innerHTML = '';
            (ws || []).forEach(w => { const d = document.createElement('div'); d.textContent = '⚠ ' + w; box.appendChild(d); });
            box.classList.toggle('hidden', !(ws && ws.length));
        }
        function appendWarning(msg) {
            const box = $('warningsBox');
            if (Array.from(box.children).some(c => c.textContent === '⚠ ' + msg)) return;
            const d = document.createElement('div'); d.textContent = '⚠ ' + msg; box.appendChild(d);
            box.classList.remove('hidden');
        }
        function showLoader(msg) { $('loaderText').textContent = msg; $('loaderOverlay').classList.remove('hidden'); }
        function hideLoader() { $('loaderOverlay').classList.add('hidden'); }
        let toastTimer = null;
        function showToast(msg, type = 'ok') {
            const t = $('toast');
            $('toastMessage').textContent = msg;
            $('toastIcon').className = type === 'error' ? 'fa-solid fa-circle-exclamation text-rose-400 text-base' : 'fa-solid fa-circle-check text-emerald-400 text-base';
            t.classList.remove('opacity-0', 'translate-y-4'); t.classList.add('opacity-100', 'translate-y-0');
            clearTimeout(toastTimer);
            toastTimer = setTimeout(() => { t.classList.remove('opacity-100', 'translate-y-0'); t.classList.add('opacity-0', 'translate-y-4'); }, type === 'error' ? 5000 : 3000);
        }

        $('fileInput').addEventListener('change', async e => { const f = e.target.files[0]; e.target.value = ''; await uploadFile(f); });
        $('dpiSelect').addEventListener('change', e => { state.dpi = parseInt(e.target.value, 10); updateCardTexts(); showToast(`Calidad de exportación: ${state.dpi} DPI`); });
        $('toggleArtwork').addEventListener('change', e => { applyGroup('art', e.target.checked); renderLayerList(); updateModeBadge(); scheduleRefresh(); });
        $('togglePatterns').addEventListener('change', e => { applyGroup('pattern', e.target.checked); renderLayerList(); updateModeBadge(); scheduleRefresh(); });
        $('toggleSpecText').addEventListener('change', e => { state.showSpecText = e.target.checked; applyGroup('spec', e.target.checked); renderLayerList(); updateModeBadge(); scheduleRefresh(); });
        $('toggleTrim').addEventListener('change', scheduleRefresh);
        const PROF_KEY = 'tegra_profiles_v1', PROF_IDS = ['profCrop', 'profCost', 'profRef'];
        try {
            const saved = JSON.parse(localStorage.getItem(PROF_KEY) || '{}');
            PROF_IDS.forEach(id => { if (saved[id] && $(id).querySelector(`option[value="${saved[id]}"]`)) $(id).value = saved[id]; });
        } catch {}
        const profHint = () => { const sel = $('profCost').value; $('profCostHint').classList.toggle('hidden', (sel === 'crop' ? $('profCrop').value : sel) === 'art'); };
        profHint();
        PROF_IDS.forEach(id => $(id).addEventListener('change', () => {
            try { localStorage.setItem(PROF_KEY, JSON.stringify(Object.fromEntries(PROF_IDS.map(i => [i, $(i).value])))); } catch {}
            profHint();
            if (id === 'profCrop' && state.docId) scheduleRefresh();
            showToast('Capas actualizadas: ' + $(id).selectedOptions[0].textContent);
        }));
        $('bgSelect').addEventListener('change', () => showToast('Fondo: ' + ($('bgSelect').value === 'white' ? 'blanco' : 'transparente')));
        $('viewAllBtn').addEventListener('click', () => state.docId && setViewMode('all'));
        $('viewIsolatedBtn').addEventListener('click', () => state.docId && setViewMode('isolated'));
        $('pageSelect').addEventListener('change', e => { state.page = parseInt(e.target.value, 10); refreshAll(); });
        $('downloadAllZipBtn').addEventListener('click', exportAllZip);
        $('resetMappingBtn').addEventListener('click', () => { state.map = { ...state.defaultMap }; initMappingUI(); updateCardTexts(); renderCanvas(); showToast('Diccionario restablecido'); });
        $('addMapBtn').addEventListener('click', () => {
            const code = normCode($('newMapCode').value), name = $('newMapName').value.trim();
            if (!code || !name) { showToast('Escribe el código y el nombre.', 'error'); return; }
            state.map[code] = name; $('newMapCode').value = ''; $('newMapName').value = '';
            initMappingUI(); updateCardTexts(); renderCanvas(); showToast(`Agregado: ${code} → ${name}`);
        });

        // ================= Integración con el Sistema de Costos =================
        const SIZE_ORDER = ['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL'];
        // Letras (XS..5XL) y, después, las tallas numéricas (40, 44, 48...) detectadas en el PDF o propias de alguna pieza.
        const isNumSize = s => /^\d+$/.test(String(s));
        function allSizes() {
            const nums = new Set();
            [...(state.sizesDetected || []), ...(state.sizesSel || []), ...((state.pieces || []).flatMap(p => p.sizes || []))].forEach(s => { if (isNumSize(s)) nums.add(String(s)); });
            return SIZE_ORDER.concat([...nums].sort((a, b) => a - b));
        }
        const USER_TEAMS_KEY = 'tegra_team_catalog_v1';
        const loadUserTeams = () => { try { return JSON.parse(localStorage.getItem(USER_TEAMS_KEY) || '{}'); } catch { return {}; } };
        const saveUserTeams = () => { try { localStorage.setItem(USER_TEAMS_KEY, JSON.stringify(state.userTeams)); } catch {} };
        const teamLookup = code => { const c = (code || '').toUpperCase().trim(); return state.userTeams[c] || state.teamCatalog[c] || ''; };
        const pieceLabel = p => customName(p) || (translated(p) + (p.parts > 1 ? ' ' + p.part : ''));

        function initCostData(data) {
            state.userTeams = loadUserTeams();
            state.teamCatalog = data.team_catalog || {};
            state.teamCode = (data.team_code || '').toUpperCase();
            state.teamName = state.teamCode ? (teamLookup(state.teamCode) || data.team_name || '') : '';
            $('teamCode').value = state.teamCode;
            $('teamName').value = state.teamName;
            state.category = data.category || ''; $('catSelect').value = state.category;
            state.schematic = data.schematic || '';
            $('schematicInfo').textContent = state.schematic ? 'Schematic: ' + state.schematic : 'No se encontró el título "Schematic" como texto en el PDF.';
            $('teamCandidates').innerHTML = (data.team_candidates || []).map(c => `<option value="${c}"></option>`).join('');
            const hint = $('teamHint');
            if (!state.teamCode) {
                const c = data.team_candidates || [];
                hint.textContent = 'No se encontró el equipo (ni en el Schematic ni en el nombre del PDF).' + (c.length ? ' Posibles códigos: ' + c.join(', ') + '.' : '') + ' Escríbelo para que Costos lo use.';
            }
            hint.classList.toggle('hidden', !!state.teamCode);
            state.sizesDetected = data.sizes || [];
            state.sizesSel = new Set(state.sizesDetected);
            renderSizeChips(data.sizes_source);
            updateSendLabel();
        }

        function renderSizeChips(source) {
            const box = $('sizeChips'); box.innerHTML = '';
            allSizes().forEach(s => {
                const b = document.createElement('button');
                b.type = 'button'; b.textContent = s;
                const paint = () => { b.className = 'px-1.5 py-0.5 rounded border text-[10px] font-mono transition ' +
                    (state.sizesSel.has(s) ? 'bg-red-600/30 border-red-500 text-red-200' : 'bg-zinc-900 border-zinc-700 text-zinc-500'); };
                paint();
                b.addEventListener('click', () => { if (state.sizesSel.has(s)) state.sizesSel.delete(s); else state.sizesSel.add(s); paint(); });
                box.appendChild(b);
            });
            $('sizeSource').textContent = state.sizesDetected.length ? `Detectadas en ${source}.` : 'No se detectaron: Costos usará las que tenga marcadas.';
        }

        function updateSendLabel() {
            const n = state.pieces.length - state.skipped.size;
            $('sendCostLabel').textContent = state.docId ? `Enviar a Costos (${n} pieza${n === 1 ? '' : 's'})` : 'Enviar a Costos';
        }

        $('teamCode').addEventListener('input', e => {
            const c = e.target.value.toUpperCase().trim();
            e.target.value = c; state.teamCode = c;
            const n = teamLookup(c);
            if (n) { state.teamName = n; $('teamName').value = n; }
        });
        $('catSelect').addEventListener('change', e => { state.category = e.target.value; });
        $('teamName').addEventListener('input', e => { state.teamName = e.target.value.trim(); });
        $('teamName').addEventListener('change', () => {
            if (state.teamCode && state.teamName && teamLookup(state.teamCode) !== state.teamName) {
                state.userTeams[state.teamCode] = state.teamName; saveUserTeams();
                showToast(`Guardado en tu catálogo: ${state.teamCode} → ${state.teamName}`);
            }
        });

        function setTab(tab) {
            const cost = tab === 'costos';
            $('viewExtractor').classList.toggle('hidden', cost);
            $('viewCostos').classList.toggle('hidden', !cost);
            $('extractorTools').classList.toggle('hidden', cost);
            $('tabExtractor').className = 'px-3 py-1.5 rounded-md ' + (cost ? 'text-zinc-300 hover:bg-zinc-800' : 'bg-red-600 text-white');
            $('tabCostos').className = 'px-3 py-1.5 rounded-md ' + (cost ? 'bg-red-600 text-white' : 'text-zinc-300 hover:bg-zinc-800');
        }
        async function waitCostos() {
            const fr = $('costosFrame');
            for (let i = 0; i < 100; i++) {
                const w = fr.contentWindow;
                if (w && typeof w.recibirDesdeExtractor === 'function' && w.__costosListo) return w;
                await new Promise(r => setTimeout(r, 100));
            }
            throw new Error('El módulo de Costos no terminó de cargar (usa librerías por internet: revisa tu conexión).');
        }

        async function sendToCosts() {
            if (!state.docId) return;
            const activas = state.pieces.filter(p => !state.skipped.has(p.id));
            const items = activas.filter(p => state.clips[p.id]);
            if (!items.length) { showToast('No hay piezas con contenido para enviar.', 'error'); return; }
            const sinContenido = activas.length - items.length;
            const names = fileNames();
            const q = costQuery().toString();
            const sendRefs = $('chkSendRefs').checked, rq = refQuery().toString();
            const sel = allSizes().filter(s => state.sizesSel.has(s));
            // Talla propia de la pieza (la del bloque de su etiqueta), limitada a las tallas seleccionadas arriba; sin talla propia, se usa la lista global.
            const tallasDe = p => { const own = p.sizes || []; if (!own.length || !sel.length) return own; const f = own.filter(s => sel.includes(s)); return f.length ? f : own; };
            const payload = {
                origen: state.docId, pdf: state.fileName, style: state.style,
                teamName: state.teamName || state.teamCode || '', category: state.category,
                sizes: sel,
                pieces: items.map(p => ({ id: p.id, placement: pieceLabel(p), file: names[p.id], sizes: tallasDe(p),
                                          url: `/api/piece/${state.docId}/${p.id}.png?${q}`,
                                          refUrl: (sendRefs && !state.noRef.has(p.id)) ? `/api/piece/${state.docId}/${p.id}.png?${rq}` : '' })),
            };
            setTab('costos');
            state.sending = true;
            try {
                const w = await waitCostos();
                const r = await w.recibirDesdeExtractor(payload);
                const b = $('costBadge'); b.textContent = r.total; b.classList.toggle('hidden', !r.total);
                if (!payload.teamName) showToast('Ojo: no hay equipo, la columna NAME quedó vacía (puedes escribirla en Costos).', 'error');
                else if (!payload.category) showToast('Ojo: no hay categoría (GAME / ELITE / LIMITED); elígela en Costos.', 'error');
                else if (sinContenido) showToast(`${sinContenido} pieza(s) sin contenido visible no se enviaron.`, 'error');
            } catch (err) { showToast(err.message, 'error'); }
            finally { state.sending = false; }
        }

        $('tabExtractor').addEventListener('click', () => setTab('extractor'));
        $('tabCostos').addEventListener('click', () => setTab('costos'));
        $('sendCostBtn').addEventListener('click', sendToCosts);
        $('refZipBtn').addEventListener('click', exportRefZip);

        // ================= Limpiar: deja el extractor listo para el siguiente trabajo =================
        function clearExtractor() {
            if (state.sending) { showToast('Espera: todavía se están enviando piezas a Costos.', 'error'); return; }
            if (!state.docId) { showToast('No hay ningún PDF cargado.'); return; }
            const old = state.docId;
            fetch(`/api/close/${old}`, { method: 'POST' }).catch(() => {});
            refreshSeq++; clearTimeout(refreshTimer); hideLoader();
            Object.assign(state, {
                docId: null, fileName: '', styleRaw: '', style: '', mode: '', pages: [], page: 1, layers: [], pieces: [],
                clips: {}, activePiece: null, showSpecText: false, sheetImg: null, defaultMap: {}, map: {},
                skipped: new Set(), noRef: new Set(), pieceNames: {}, category: '', schematic: '', teamCode: '', teamName: '',
                sizesDetected: [], sizesSel: new Set(),
            });
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            $('canvasWrap').classList.add('hidden');
            $('emptyState').classList.remove('hidden');
            $('fileInput').value = '';
            $('fileInfoLabel').innerHTML = 'Archivo: <span class="text-zinc-500">ninguno</span>';
            $('detectedStyle').textContent = '—'; $('detectedCount').textContent = '—'; $('detectedMode').textContent = '—';
            $('pieceBadgeCount').textContent = '0';
            $('piecesContainer').innerHTML = '<p class="text-xs text-zinc-500">Sube un PDF para ver las piezas.</p>';
            $('layerList').innerHTML = '<p class="text-zinc-500">Sube un PDF para ver sus capas.</p>'; $('layerCount').textContent = '';
            $('mappingList').innerHTML = '';
            $('warningsBox').innerHTML = ''; $('warningsBox').classList.add('hidden');
            $('teamCode').value = ''; $('teamName').value = ''; $('teamCandidates').innerHTML = '';
            $('teamHint').classList.add('hidden'); $('catSelect').value = ''; $('schematicInfo').textContent = '';
            renderSizeChips(''); $('sizeSource').textContent = '';
            $('pageSelect').innerHTML = ''; $('pageSelect').classList.add('hidden');
            $('toggleArtwork').checked = true; $('togglePatterns').checked = false; $('toggleSpecText').checked = false;
            setViewMode('isolated', false); updateModeBadge();
            ['downloadAllZipBtn', 'refZipBtn', 'sendCostBtn'].forEach(id => { $(id).disabled = true; });
            updateSendLabel();
            showToast('Listo para el siguiente trabajo. Lo ya enviado a Costos se conserva.');
        }
        $('clearBtn').addEventListener('click', clearExtractor);

        const vp = $('viewportContainer');
        ['dragover', 'dragenter'].forEach(ev => vp.addEventListener(ev, e => { e.preventDefault(); vp.classList.add('ring-2', 'ring-red-500'); }));
        ['dragleave', 'drop'].forEach(ev => vp.addEventListener(ev, e => { e.preventDefault(); vp.classList.remove('ring-2', 'ring-red-500'); }));
        vp.addEventListener('drop', e => { const f = e.dataTransfer.files[0]; if (f) uploadFile(f); });
    </script>
</body>
</html>
"""


COSTOS_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tegra - Sistema de Costos Serigrafía</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #1a1a1a;
            min-height: 100vh;
            padding: 20px;
        }
          
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: #2d2d2d;
            border-radius: 15px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.3);
            overflow: hidden;
            border: 1px solid #444;
        }
        
        .header {
            background: #000;
            color: white;
            padding: 20px 25px;
            text-align: center;
            border-bottom: 3px solid #dd1c12;
        }
        
        .header-content {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 20px;
        }
        
        .logo {
            height: 50px;
            width: auto;
        }
        
        .header h1 {
            font-size: 24px;
            font-weight: 600;
            color: #dd1c12;
        }
        
        .content {
            padding: 25px;
            background: #2d2d2d;
        }
        
        .section {
            background: #3a3a3a;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            border-left: 4px solid #dd1c12;
            color: white;
        }
        
        .section-title {
            font-weight: 600;
            color: #dd1c12;
            margin-bottom: 15px;
            font-size: 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        
        .config-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 10px;
        }
        
        .config-group {
            margin-bottom: 10px;
        }
        
        .config-label {
            font-size: 12px;
            font-weight: 600;
            color: #dd1c12;
            margin-bottom: 5px;
            display: block;
        }
        
        .config-input, .config-select {
            width: 100%;
            padding: 8px;
            border: 1px solid #555;
            border-radius: 5px;
            font-size: 12px;
            background: #2d2d2d;
            color: white;
        }
        
        .config-input:focus, .config-select:focus {
            border-color: #dd1c12;
            outline: none;
        }
        
        .tallas-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));
            gap: 8px;
            margin-top: 5px;
        }
        
        .talla-option {
            display: flex;
            align-items: center;
            gap: 5px;
        }
        
        .talla-checkbox {
            margin: 0;
        }
        
        .talla-label {
            font-size: 11px;
            color: #ccc;
        }
        
        .drop-zone {
            border: 3px dashed #dd1c12;
            border-radius: 10px;
            padding: 40px;
            text-align: center;
            background: #2d2d2d;
            cursor: pointer;
            transition: all 0.3s;
            margin-bottom: 20px;
            color: white;
        }
        
        .drop-zone:hover {
            background: #363636;
            border-color: #ff4444;
        }
        
        .drop-zone.active {
            background: #363636;
            border-color: #ff4444;
        }
        
        .file-input {
            display: none;
        }
        
        .thumbnails-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }
        
        .thumbnail-card {
            background: #3a3a3a;
            border-radius: 10px;
            padding: 15px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
            border: 2px solid #555;
            transition: transform 0.3s;
            color: white;
        }
        
        .thumbnail-card:hover {
            transform: translateY(-5px);
            border-color: #dd1c12;
        }
        
        .thumbnail-img-container {
            width: 100%;
            height: 150px;
            overflow: hidden;
            border-radius: 5px;
            margin-bottom: 10px;
            background: #2d2d2d;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .thumbnail-img {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
        }
        
        .thumbnail-info {
            font-size: 11px;
        }
        
        .info-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 3px;
            padding: 2px 0;
        }
        
        .info-label {
            font-weight: 600;
            color: #dd1c12;
            flex: 1;
        }
        
        .info-value {
            color: #ccc;
            text-align: right;
            flex: 1;
        }
        
        .badge-container {
            display: flex;
            flex-wrap: wrap;
            gap: 5px;
            margin-top: 8px;
        }
        
        .badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 10px;
            font-size: 10px;
            font-weight: 600;
        }
        
        .badge-colors {
            background: #dd1c12;
            color: white;
        }
        
        .badge-placement {
            background: #dd1c12;
            color: white;
        }
        
        .badge-complexity {
            background: #dd1c12;
            color: white;
        }
        
        .badge-tallas {
            background: #333;
            color: #dd1c12;
            border: 1px solid #dd1c12;
        }
        

        .aviso { font-size: 11px; font-weight: 600; padding: 5px 8px; border-radius: 6px; margin-bottom: 6px; }
        .aviso-error { background: #7a1410; color: #fff; border: 1px solid #dd1c12; }
        .aviso-warn { background: #4a3b00; color: #ffd761; border: 1px solid #8a6d00; }
        .mini-input, .mini-select { background: #2d2d2d; color: #fff; border: 1px solid #555; border-radius: 4px;
            font-size: 11px; padding: 3px 5px; flex: 1; min-width: 0; text-align: right; }
        .mini-input:focus, .mini-select:focus { border-color: #dd1c12; outline: none; }
        .mini-input.vacio { border-color: #dd1c12; background: #3b1816; }
        .efectos-box { margin-top: 10px; padding-top: 8px; border-top: 1px dashed #555; }
        .efectos-titulo { font-size: 10px; color: #dd1c12; font-weight: 700; margin-bottom: 5px; text-transform: uppercase; }
        .chips { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 6px; }
        .chip { background: #2d2d2d; color: #ccc; border: 1px solid #666; border-radius: 12px; padding: 3px 9px;
            font-size: 10px; font-weight: 600; cursor: pointer; }
        .chip:hover { border-color: #dd1c12; }
        .chip.active { background: #dd1c12; border-color: #dd1c12; color: #fff; }
        .comentario-preview { font-size: 10px; color: #ccc; margin-top: 6px; }
        .comentario-preview b { color: #fff; }
        .hint { font-size: 10px; color: #999; margin-top: 4px; }

        .controls {
            display: flex;
            gap: 15px;
            justify-content: center;
            margin-top: 25px;
            flex-wrap: wrap;
        }
        
        .btn {
            background: #dd1c12;
            color: white;
            border: none;
            padding: 12px 25px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.3s;
            min-width: 160px;
        }
        
        .btn:hover {
            background: #ff4444;
        }
        
        .btn-accent {
            background: #333;
            color: #dd1c12;
            border: 1px solid #dd1c12;
        }
        
        .btn-accent:hover {
            background: #444;
        }
        
        .btn-success {
            background: #dd1c12;
            color: white;
        }
        
        .btn-success:hover {
            background: #ff4444;
        }
        
        .alert {
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 15px;
            font-size: 14px;
            transition: all 0.3s;
        }
        
        .alert-success {
            background: #2d2d2d;
            color: #dd1c12;
            border: 1px solid #dd1c12;
        }
        
        .alert-error {
            background: #2d2d2d;
            color: #ff6b6b;
            border: 1px solid #ff6b6b;
        }
        
        .progress-bar {
            width: 100%;
            height: 20px;
            background: #2d2d2d;
            border-radius: 10px;
            margin: 10px 0;
            overflow: hidden;
            border: 1px solid #555;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #dd1c12, #ff4444);
            transition: width 0.3s;
            width: 0%;
        }
        
        .stats {
            display: flex;
            justify-content: space-around;
            background: #000;
            color: #dd1c12;
            padding: 10px;
            border-radius: 8px;
            margin-top: 10px;
            font-size: 12px;
            border: 1px solid #dd1c12;
        }
        
        .stat-item {
            text-align: center;
        }
        
        .stat-value {
            font-size: 16px;
            font-weight: bold;
        }

        .color-correction {
            background: #2d2d2d;
            padding: 10px;
            border-radius: 8px;
            margin-top: 10px;
            border: 1px solid #555;
        }

        .correction-option {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 5px;
            color: white;
            font-size: 12px;
        }

        .tallas-section {
            background: #2d2d2d;
            padding: 15px;
            border-radius: 8px;
            margin-top: 10px;
            border: 1px solid #555;
        }

        .tallas-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }

        .select-all-btn {
            background: #333;
            color: #dd1c12;
            border: 1px solid #dd1c12;
            padding: 5px 10px;
            border-radius: 5px;
            font-size: 11px;
            cursor: pointer;
        }

        .select-all-btn:hover {
            background: #444;
        }

        #alertContainer {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1000;
            max-width: 400px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-content">
                <img src="https://www.tegraglobal.com/careers/public/images/logo.png" alt="Tegra Logo" class="logo" onerror="this.style.display='none';document.getElementById('logoFallback').style.display='block'">
                <span id="logoFallback" style="display:none;color:#fff;font-weight:700;letter-spacing:3px;font-size:22px">TEGRA</span>
                <h1>SISTEMA DE COSTOS SERIGRAFÍA</h1>
            </div>
        </div>
        
        <div class="content">
            <!-- Configuración del Proyecto -->
            <div class="section">
                <div class="section-title">
                    <span>CONFIGURACIÓN DEL PROYECTO</span>
                    <span id="projectStats">0 imágenes</span>
                </div>
                <div class="config-grid">
                    <div class="config-group">
                        <label class="config-label">COSTUMER:</label>
                        <select id="customerSelect" class="config-select">
                            <option value="">Seleccionar...</option>
                            <option value="Nike">Nike</option>
                            <option value="Fanatics" selected>Fanatics</option>
                            <option value="Nike NBA">Nike NBA</option>
                            <option value="GFS">GFS</option>
                            <option value="NCAA">NCAA</option>
                            <option value="Tegra Brand">Tegra Brand</option>
                            <option value="__OTRO__">Otro (colocar nombre)</option>
                        </select>
                        <input type="text" id="customerOtro" class="config-input" placeholder="Nombre del cliente" style="display:none; margin-top:6px;">
                    </div>
                    <div class="config-group">
                        <label class="config-label">CATEGORY:</label>
                        <select id="categorySelect" class="config-select">
                            <option value="">Seleccionar...</option>
                            <option value="NFL Elite">NFL Elite</option>
                            <option value="NFL Limited">NFL Limited</option>
				<option value="NFL Game">NFL Game</option>
                            <option value="NCAA">NCAA</option>
                            <option value="Football">Football</option>
                        </select>
                    </div>
                    <div class="config-group">
                        <label class="config-label">COMMENTS (tipo de tinta):</label>
                        <select id="commentsInput" class="config-select">
                            <option value="HSWB" selected>HSWB</option>
                            <option value="Plastisol">Plastisol</option>
                            <option value="Silicone">Silicone</option>
                        </select>
                        <div class="hint">Los efectos (Metálico, Base Puff, H.D, Pearl Flex…) se marcan en cada pieza.</div>
                    </div>
                </div>
            </div>

            <!-- Selección de Tallas -->
            <div class="section tallas-section">
                <div class="tallas-header">
                    <div class="section-title">SELECCIÓN DE TALLAS (XS - 5XL)</div>
                    <button class="select-all-btn" onclick="seleccionarTodasTallas()">SELECCIONAR TODAS</button>
                </div>
                <div class="tallas-grid" id="tallasGrid">
                    <!-- Las tallas se generarán dinámicamente -->
                </div>
            </div>

            </div>

            <!-- Carga de Imágenes -->
            <div class="section">
                <div class="section-title">CARGA DE IMÁGENES POR LOTE</div>
                
                <div class="drop-zone" id="dropZone">
                    <div style="font-size: 18px; margin-bottom: 10px;">📁 ARRASTRA AQUÍ TUS IMÁGENES PNG</div>
                    <div style="font-size: 12px; color: #ccc;">
                        Formatos: PNG con fondo transparente • 300 DPI recomendado
                    </div>
                    <input type="file" id="fileInput" class="file-input" multiple accept=".png">
                </div>
                
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill"></div>
                </div>
                
                <div id="fileCounter" style="text-align: center; font-size: 14px; color: #ccc;">
                    No hay archivos seleccionados
                </div>
            </div>
            
            <!-- Resultados -->
            <div class="section">
                <div class="section-title">RESULTADOS PROCESADOS</div>
                <div class="thumbnails-grid" id="thumbnailsGrid"></div>
            </div>
            
            <datalist id="placementsList"></datalist>
            <div id="alertContainer"></div>
            
            <!-- Controles -->
            <div class="controls">
                <label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#ddd;cursor:pointer"><input type="checkbox" id="chkRefsExcel" checked> Incluir imágenes de referencia en el Excel</label>
                <button class="btn" onclick="descargarPlantilla()">
                    📋 DESCARGAR PLANTILLA
                </button>
                <button class="btn btn-success" onclick="descargarExcelConDatos()">
                    ⬇️ DESCARGAR EXCEL CON DATOS
                </button>
                <button class="btn btn-accent" onclick="procesarLote()">
                    🔍 VERIFICAR CÁLCULOS
                </button>
                <button class="btn" onclick="limpiarLote()">
                    🗑️ LIMPIAR TODO
                </button>
            </div>
        </div>
    </div>

    <!-- Incluir SheetJS para exportación a Excel -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js"></script>

    <script>
        let imagenesProcesadas = [];
        let tallasSeleccionadas = new Set(['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL']);
        const TALLAS_LETRAS = ['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL'];
        let tallasNumericas = new Set();       // tallas numéricas (40, 44, 48...) recibidas del extractor: se muestran junto a las de letras
        const tallasVisibles = () => TALLAS_LETRAS.concat(Array.from(tallasNumericas).sort((a, b) => a - b));
        
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const thumbnailsGrid = document.getElementById('thumbnailsGrid');
        const alertContainer = document.getElementById('alertContainer');
        const progressFill = document.getElementById('progressFill');
        const fileCounter = document.getElementById('fileCounter');
        const projectStats = document.getElementById('projectStats');
        const tallasGrid = document.getElementById('tallasGrid');
        
        // ========== BASE64 DEL EXCEL ==========
        const excelTemplateBase64 = "__EXCEL_TEMPLATE_B64__";
        
        // ========== INICIALIZACIÓN ==========
        function inicializarTallas() {
            const tallas = tallasVisibles();
            tallasGrid.innerHTML = '';
            
            tallas.forEach(talla => {
                const div = document.createElement('div');
                div.className = 'talla-option';
                div.innerHTML = `
                    <input type="checkbox" id="talla-${talla}" class="talla-checkbox" 
                           ${tallasSeleccionadas.has(talla) ? 'checked' : ''}
                           onchange="actualizarTalla('${talla}', this.checked)">
                    <label for="talla-${talla}" class="talla-label">${talla}</label>
                `;
                tallasGrid.appendChild(div);
            });
        }
        
        function actualizarTalla(talla, seleccionada) {
            if (seleccionada) {
                tallasSeleccionadas.add(talla);
            } else {
                tallasSeleccionadas.delete(talla);
            }
            actualizarEstadisticas();
        }
        
        function seleccionarTodasTallas() {
            const tallas = tallasVisibles();
            const todasSeleccionadas = tallas.every(t => tallasSeleccionadas.has(t));
            
            if (todasSeleccionadas) {
                tallasSeleccionadas.clear();
                tallas.forEach(talla => {
                    document.getElementById(`talla-${talla}`).checked = false;
                });
                mostrarAlerta('Todas las tallas deseleccionadas', 'success');
            } else {
                tallas.forEach(talla => {
                    tallasSeleccionadas.add(talla);
                    document.getElementById(`talla-${talla}`).checked = true;
                });
                mostrarAlerta('Todas las tallas seleccionadas', 'success');
            }
            
            actualizarEstadisticas();
        }
        
        // ========== MANEJO DE ARCHIVOS ==========
        dropZone.addEventListener('click', () => fileInput.click());
        
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('active');
        });
        
        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('active');
        });
        
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('active');
            const files = e.dataTransfer.files;
            procesarArchivos(files);
        });
        
        fileInput.addEventListener('change', (e) => {
            procesarArchivos(e.target.files);
        });
        
        // ========== LECTURA DE NOMBRE DE ARCHIVO ==========
        const CODIGOS_NOMBRE = {
            'OH': 'Ohio', 'TX': 'Texas', 'TEX': 'Texas', 'CAL': 'California', 'CA': 'California',
            'FLA': 'Florida', 'FL': 'Florida', 'NC': 'North Carolina', 'SC': 'South Carolina',
            'GA': 'Georgia', 'GEO': 'Georgia Bulldogs', 'ALA': 'Alabama', 'AL': 'Alabama',
            'MS': 'Mississippi', 'TN': 'Tennessee', 'KY': 'Kentucky', 'VA': 'Virginia',
            'PA': 'Pennsylvania', 'NY': 'New York', 'NJ': 'New Jersey', 'MI': 'Michigan',
            'IL': 'Illinois', 'IN': 'Indiana', 'WI': 'Wisconsin', 'MN': 'Minnesota', 'IA': 'Iowa',
            'MO': 'Missouri', 'AR': 'Arkansas', 'LA': 'Louisiana', 'OK': 'Oklahoma', 'KS': 'Kansas',
            'NE': 'Nebraska', 'CO': 'Colorado', 'UT': 'Utah', 'AZ': 'Arizona', 'NV': 'Nevada',
            'NM': 'New Mexico', 'ID': 'Idaho', 'MT': 'Montana', 'WY': 'Wyoming', 'WA': 'Washington',
            'OR': 'Oregon',
            'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens',
            'BUF': 'Buffalo Bills', 'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears',
            'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns', 'DAL': 'Dallas Cowboys',
            'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GBP': 'Green Bay Packers',
            'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAG': 'Jacksonville Jaguars',
            'KCC': 'Kansas City Chiefs', 'LAC': 'Los Angeles Chargers', 'LVR': 'Las Vegas Raiders',
            'MIA': 'Miami Dolphins', 'MIN': 'Minnesota Vikings', 'NEP': 'New England Patriots',
            'NOS': 'New Orleans Saints', 'NYG': 'New York Giants', 'NYJ': 'New York Jets',
            'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers', 'RAM': 'Los Angeles Rams',
            'SEA': 'Seattle Seahawks', 'SF9': 'San Francisco 49ers', 'TBB': 'Tampa Bay Buccaneers',
            'TEN': 'Titans', 'WAS': 'Washington Commanders'
        };

        // Variantes y errores de tipeo comunes -> palabra estándar
        const SINONIMOS = {
            'RIGTH': 'RIGHT', 'RGHT': 'RIGHT', 'RGT': 'RIGHT', 'RT': 'RIGHT', 'DER': 'RIGHT', 'DERECHA': 'RIGHT',
            'LFT': 'LEFT', 'LT': 'LEFT', 'IZQ': 'LEFT', 'IZQUIERDA': 'LEFT',
            'BK': 'BACK', 'ESPALDA': 'BACK', 'POSTERIOR': 'BACK',
            'FT': 'FRONT', 'FRT': 'FRONT', 'FRENTE': 'FRONT',
            'SLV': 'SLEEVE', 'SLEEVES': 'SLEEVE', 'MANGA': 'SLEEVE',
            'SHOULDERS': 'SHOULDER', 'SHLDR': 'SHOULDER', 'HOMBRO': 'SHOULDER',
            'CUELLO': 'NECK', 'NK': 'NECK', 'PECHO': 'CHEST', 'NKB': 'NECKBAND'
        };

        // Palabras que describen la pieza o la prenda, nunca el NAME
        const PALABRAS_NO_NAME = new Set([
            'FRONT', 'BACK', 'SLEEVE', 'LEFT', 'RIGHT', 'L', 'R', 'COLLAR', 'NECK', 'NECKBAND', 'BAND',
            'INNER', 'INSIDE', 'CHEST', 'SHOULDER', 'TV', 'NUMBER', 'NUM', 'JSY', 'JERSEY', 'CROP',
            'TOP', 'BOTTOM', 'PANTS', 'SHORT', 'SHORTS', 'NUMBERS'
        ]);
        const TALLAS_VALIDAS = new Set(['XS', 'S', 'M', 'L', 'XL', '2XL', '3XL', '4XL', '5XL']);

        function detectarPlacement(tk) {
            const t = new Set(tk);
            const izq = t.has('LEFT'), der = t.has('RIGHT');
            if (tk.some(x => /^TV(R|L|RIGHT|LEFT|NUM|NUMBER)?$/.test(x))) {
                if (der || tk.includes('TVR') || tk.includes('TVRIGHT')) return 'TV RIGHT';
                if (izq || tk.includes('TVL') || tk.includes('TVLEFT')) return 'TV LEFT';
                return 'TV NUMBER';
            }
            if (t.has('INNER') && t.has('NECK')) return 'INNER NECK';
            if (t.has('NECKBAND') || (t.has('NECK') && t.has('BAND'))) return 'NECK BAND';
            if (t.has('INSIDE') && t.has('NECK')) return 'INNER NECK';
            if (t.has('INSIDE') && t.has('BACK')) return 'INSIDE BACK';
            if (t.has('SLEEVE')) return 'SLEEVE';            // izquierda y derecha: ambas "SLEEVE"
            if (t.has('SHOULDER')) return izq ? 'LEFT SHOULDER' : der ? 'RIGHT SHOULDER' : 'SHOULDER';
            if (t.has('BACK')) return 'BACK';
            if (t.has('FRONT')) return 'FRONT';
            if (t.has('COLLAR')) return 'COLLAR';
            if (t.has('NECK')) return 'NECK';
            if (t.has('CHEST')) return 'CHEST';
            if (izq || der) return 'SLEEVE';
            return 'FRONT';
        }

        function parsearNombreArchivo(nombreArchivo, tallasPorDefecto) {
            const avisos = [];
            const limpio = nombreArchivo.replace(/\.[^/.]+$/, '').toUpperCase();

            // STYLE: código con guiones que contenga al menos un número (ej. NFCT-08AR-NGB-JPX)
            let style = '';
            let resto = limpio;
            const reStyle = /[A-Z0-9]{2,5}(?:-[A-Z0-9]{1,5}){2,4}/g;
            let m;
            while ((m = reStyle.exec(limpio)) !== null) {
                if (/\d/.test(m[0])) {
                    style = m[0];
                    resto = limpio.slice(0, m.index) + ' ' + limpio.slice(m.index + m[0].length);
                    break;
                }
            }
            if (!style) avisos.push('STYLE no detectado');

            // Tokens del resto del nombre (sin el style), con variantes normalizadas
            const crudos = resto.split(/[\s_.\-]+/).filter(Boolean);
            const hayContextoLado = crudos.some(x => ['SLV', 'SLEEVE', 'SLEEVES', 'TV', 'SHOULDER', 'SHOULDERS'].includes(x));
            const tokens = crudos.map(x => {
                if (hayContextoLado && x === 'L') return 'LEFT';
                if (hayContextoLado && x === 'R') return 'RIGHT';
                return SINONIMOS[x] || x;
            });

            // NAME: primera palabra que no sea pieza/prenda/talla/número
            let code = '';
            for (let i = 0; i < crudos.length; i++) {
                const c = crudos[i];
                if (PALABRAS_NO_NAME.has(tokens[i]) || PALABRAS_NO_NAME.has(c) || SINONIMOS[c]) continue;
                if (TALLAS_VALIDAS.has(c) || /^\d+$/.test(c) || /^V\d+$/.test(c)) continue;
                code = c;
                break;
            }
            if (!code) avisos.push('NAME no detectado');
            const nameExport = CODIGOS_NOMBRE[code] || code;

            // PLACEMENT
            const placement = detectarPlacement(tokens);

            // TALLAS: solo si el nombre las trae explícitas
            const tallasEnNombre = [];
            crudos.forEach((x, i) => {
                const esLado = hayContextoLado && (x === 'L' || x === 'R');
                if (!esLado && TALLAS_VALIDAS.has(x) && !tallasEnNombre.includes(x)) tallasEnNombre.push(x);
            });
            const tallas = tallasEnNombre.length ? tallasEnNombre.join('-') : Array.from(tallasPorDefecto).join('-');

            return { style, code, name: code, nameExport, placement, tallas, avisos };
        }

        // ========== DETECCIÓN DE RESOLUCIÓN (DPI declarado en el PNG) ==========
        function leerDPIdePNG(buf) {
            try {
                const b = new Uint8Array(buf);
                const firma = [137, 80, 78, 71, 13, 10, 26, 10];
                if (b.length < 33 || firma.some((v, i) => b[i] !== v)) return null;
                const dv = new DataView(buf);
                let i = 8;
                while (i + 8 <= b.length) {
                    const largo = dv.getUint32(i);
                    const tipo = String.fromCharCode(b[i + 4], b[i + 5], b[i + 6], b[i + 7]);
                    if (tipo === 'pHYs') {
                        const x = dv.getUint32(i + 8), y = dv.getUint32(i + 12), unidad = b[i + 16];
                        if (unidad !== 1) return null;           // sin unidad física = DPI desconocido
                        return { x: x * 0.0254, y: y * 0.0254 };
                    }
                    if (tipo === 'IDAT' || tipo === 'IEND') return null;
                    i += 12 + largo;
                }
            } catch (e) { /* archivo ilegible: se trata como sin DPI */ }
            return null;
        }

        // ========== DPI REAL PARA LAS DIMENSIONES FÍSICAS ==========
        // Ancho/alto/área se calculan con el DPI declarado en el PNG (en las exportaciones del extractor es el
        // DPI EFECTIVO, no el pedido). Si falta o no es válido se estima con 300 y se marca como estimado.
        const DPI_PREDETERMINADO = 300;
        const DPI_MIN_VALIDO = 10, DPI_MAX_VALIDO = 20000;
        function resolverDPI(dpiInfo) {
            const valido = v => typeof v === 'number' && isFinite(v) && v >= DPI_MIN_VALIDO && v <= DPI_MAX_VALIDO;
            if (dpiInfo && valido(dpiInfo.x) && valido(dpiInfo.y)) {
                return { x: dpiInfo.x, y: dpiInfo.y, estimado: false, motivo: '' };
            }
            return { x: DPI_PREDETERMINADO, y: DPI_PREDETERMINADO, estimado: true,
                     motivo: dpiInfo ? 'DPI inválido en los metadatos del PNG' : 'el PNG no declara DPI' };
        }
        // Constancia en el Excel: solo para piezas con DPI estimado (columna COMMENTS); vacío si el DPI es válido.
        function avisoDPIExcel(m) {
            return m.dpiEstimado ? 'DPI ESTIMADO: dimensiones estimadas a ' + DPI_PREDETERMINADO + ' DPI (PNG sin DPI válido)' : '';
        }
        function textoDPI(x, y) {
            const f = v => Math.abs(v - Math.round(v)) < 0.05 ? String(Math.round(v)) : v.toFixed(1);
            return (Math.abs(x - y) < 0.5 ? f(x) : f(x) + '×' + f(y)) + ' DPI';
        }

        const DPI_ESPERADO = 300;
        function evaluarResolucion(dpi) {
            if (!dpi) return { nivel: 'warn', texto: 'Sin DPI declarado (se asume ' + DPI_ESPERADO + ')' };
            const x = Math.round(dpi.x), y = Math.round(dpi.y);
            if (Math.abs(dpi.x - DPI_ESPERADO) <= 1 && Math.abs(dpi.y - DPI_ESPERADO) <= 1) return { nivel: 'ok', texto: DPI_ESPERADO + ' DPI' };
            const txt = x === y ? x + ' DPI' : x + '×' + y + ' DPI';
            return { nivel: 'error', texto: 'Resolución incorrecta: ' + txt + ' (se requieren ' + DPI_ESPERADO + ')' };
        }

        // ========== CLIENTE, TINTA Y EFECTOS ==========
        function obtenerCliente() {
            const v = document.getElementById('customerSelect').value;
            if (v === '__OTRO__') return document.getElementById('customerOtro').value.trim();
            return v;
        }
        document.getElementById('customerSelect').addEventListener('change', function () {
            const otro = document.getElementById('customerOtro');
            otro.style.display = this.value === '__OTRO__' ? 'block' : 'none';
            if (this.value === '__OTRO__') otro.focus();
        });

        const EFECTOS_LISTA = [
            ['METALLIC', 'Metálico'], ['BASE PUFF', 'Base Puff'], ['HD', 'H.D'], ['PEARL FLEX', 'Pearl Flex']
        ];
        const PLACEMENTS_LISTA = ['FRONT', 'BACK', 'SLEEVE', 'COLLAR', 'NECK', 'INNER NECK', 'NECK BAND', 'CHEST',
            'SHOULDER', 'LEFT SHOULDER', 'RIGHT SHOULDER', 'INSIDE BACK', 'TV NUMBER', 'TV LEFT', 'TV RIGHT'];

        function comentarioPieza(m) {
            const tinta = document.getElementById('commentsInput').value;
            const partes = [tinta].concat(m.efectos || []);
            if (m.efectoOtro && m.efectoOtro.trim()) partes.push(m.efectoOtro.trim().toUpperCase());
            const base = partes.filter(Boolean).join(' + ');
            const aviso = avisoDPIExcel(m);
            return aviso ? (base ? base + ' | ' + aviso : aviso) : base;
        }

        const tarjetasRegistro = [];
        function actualizarPreviews() {
            tarjetasRegistro.forEach(t => {
                if (t.el.isConnected) t.el.innerHTML = 'COMMENTS: <b>' + _h(comentarioPieza(t.m)) + '</b>';
            });
        }
        document.getElementById('commentsInput').addEventListener('change', actualizarPreviews);

        function _h(s) {
            return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }
        let advertenciasLote = [];
        let advertenciasDPIEstimado = [];
        function avisarDPIEstimado() {
            if (!advertenciasDPIEstimado.length) return;
            mostrarAlerta('⚠️ Sin DPI válido en el PNG: las medidas se ESTIMARON a ' + DPI_PREDETERMINADO + ' DPI (pueden no ser las reales) en: ' + advertenciasDPIEstimado.join(', '), 'error');
            advertenciasDPIEstimado = [];
        }

        function procesarArchivos(files) {
            const archivosPNG = Array.from(files).filter(file => 
                file.type === 'image/png' || file.name.toLowerCase().endsWith('.png')
            );
            
            if (archivosPNG.length === 0) {
                mostrarAlerta('Por favor selecciona archivos PNG válidos', 'error');
                return;
            }
            
            fileCounter.textContent = `Procesando ${archivosPNG.length} archivo(s)...`;
            progressFill.style.width = '0%';
            
            let procesados = 0;
            const total = archivosPNG.length;
            
            archivosPNG.forEach((file, index) => {
                const dpiPromise = file.arrayBuffer().then(leerDPIdePNG).catch(() => null);
                const reader = new FileReader();
                
                reader.onload = function(e) {
                    const img = new Image();
                    img.onload = async function() {
                        const dpiInfo = await dpiPromise;
                        procesarImagen(img, file, dpiInfo);
                        procesados++;
                        
                        // Actualizar progreso
                        const progreso = (procesados / total) * 100;
                        progressFill.style.width = `${progreso}%`;
                        
                        if (procesados === total) {
                            fileCounter.textContent = `${total} archivo(s) procesado(s) correctamente`;
                            if (advertenciasLote.length) {
                                mostrarAlerta('⛔ Resolución incorrecta (se requieren ' + DPI_ESPERADO + ' DPI) en: ' + advertenciasLote.join(', '), 'error');
                                advertenciasLote = [];
                            } else {
                                mostrarAlerta(`✅ ${total} imagen(es) procesada(s) con éxito`, 'success');
                            }
                            avisarDPIEstimado();
                        }
                    };
                    img.src = e.target.result;
                };
                
                reader.readAsDataURL(file);
            });
        }
        
        function procesarImagen(img, file, dpiInfo, forzado) {
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            
            canvas.width = img.width;
            canvas.height = img.height;
            ctx.drawImage(img, 0, 0);
            
            const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
            const data = imageData.data;
            
           // ========== MÉTODO - COMO PHOTOSHOP ==========
// === DETECCIÓN DE COLORES OPTIMIZADA ===
const coloresUnicos = new Set();
let pixelsInk = 0;

// Ajusta el nivel de tolerancia (16 = bastante tolerante, 8 = más preciso)
const TOLERANCIA = 24; // diferencia máxima entre colores (0-255)
const PALETA = [];

// Función que agrupa colores similares según distancia RGB
function getApproxColorKey(r, g, b, palette, tolerance = 24) {
    for (const [pr, pg, pb] of palette) {
        const dist = Math.sqrt((r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2);
        if (dist < tolerance) return `${pr},${pg},${pb}`;
    }
    palette.push([r, g, b]);
    return `${r},${g},${b}`;
}

// Procesar datos RGBA
for (let i = 0; i < data.length; i += 4) {
    const r = data[i];
    const g = data[i + 1];
    const b = data[i + 2];
    const a = data[i + 3];

    if (a > 10) { // excluir transparencia
        pixelsInk++;
        const colorKey = getApproxColorKey(r, g, b, PALETA, TOLERANCIA);
        coloresUnicos.add(colorKey);
    }
}

// Cálculos de cobertura
const pixelsTotal = img.width * img.height;
const pixelsFabric = pixelsTotal - pixelsInk;

// === LÍNEA CRÍTICA QUE FALTA ===
let numColores = coloresUnicos.size;

// Dimensiones en pulgadas con el DPI real del PNG (estimado a 300 solo si falta o es inválido)
const dpiRes = resolverDPI(dpiInfo);
const anchoPulgadas = (img.width / dpiRes.x).toFixed(2);
const altoPulgadas = (img.height / dpiRes.y).toFixed(2);
const areaPulgadas = (parseFloat(anchoPulgadas) * parseFloat(altoPulgadas)).toFixed(2);

// Clasificación de complejidad
let complejidad = 'LOW';
if (numColores > 3) complejidad = 'HIGH';
else if (numColores > 1) complejidad = 'MED';

// === RESULTADOS ===
console.log({
    numColores,
    complejidad,
    anchoPulgadas,
    altoPulgadas,
    areaPulgadas,
    pixelsInk,
    pixelsFabric
});

// ========== EXTRACCIÓN DE STYLE, NAME Y PLACEMENT ==========
            const info = forzado
                ? { style: forzado.style, code: forzado.teamName, nameExport: forzado.teamName, placement: forzado.placement,
                    tallas: forzado.tallas, avisos: [] }
                : parsearNombreArchivo(file.name, tallasSeleccionadas);
            const style = info.style;
            const nameDisplay = info.code;
            const nameExport = info.nameExport;
            const placement = info.placement;
            const tallasStr = info.tallas;
            let resolucion = evaluarResolucion(dpiInfo);
            if (dpiRes.estimado) {
                resolucion = { nivel: 'warn', texto: 'DPI no válido (' + dpiRes.motivo + '): medidas ESTIMADAS a ' + DPI_PREDETERMINADO + ' DPI' };
                advertenciasDPIEstimado.push(file.name);
            }
            if (resolucion.nivel === 'error') advertenciasLote.push(file.name);
            
            // CREAR METADATOS
            const metadatos = {
                nombre: file.name,
                origen: forzado ? forzado.origen : null,
                refSrc: forzado ? (forzado.refSrc || null) : null,
                incluirRef: true,
                categoria: forzado ? (forzado.categoria || '') : '',
                style: style,
                name: nameDisplay,
                nameExport: nameExport,
                placement: placement,
                ancho: anchoPulgadas,
                alto: altoPulgadas,
                area: areaPulgadas,
                dpiX: dpiRes.x,
                dpiY: dpiRes.y,
                dpiEstimado: dpiRes.estimado,
                dpiTexto: textoDPI(dpiRes.x, dpiRes.y) + (dpiRes.estimado ? ' (estimado)' : ''),
                colores: numColores,
                complejidad: complejidad,
                pixelsTotal: pixelsTotal,
                pixelsInk: pixelsInk,
                pixelsFabric: pixelsFabric,
                tallas: tallasStr,
                src: img.src,
                avisos: info.avisos,
                resolucion: resolucion,
                efectos: [],
                efectoOtro: '',
                porcentajePintado: pixelsTotal > 0 ? ((pixelsInk / pixelsTotal) * 100).toFixed(1) : '0',
                porcentajeFabric: pixelsTotal > 0 ? ((pixelsFabric / pixelsTotal) * 100).toFixed(1) : '0'
            };
            
            imagenesProcesadas.push({ metadatos });
            actualizarEstadisticas();
            generarMiniatura(metadatos, img.src);
        }
        
        function generarMiniatura(metadatos, dataURL) {
            const card = document.createElement('div');
            card.className = 'thumbnail-card';
            const res = metadatos.resolucion;
            const resHtml = res.nivel === 'ok' ? '' :
                '<div class="aviso ' + (res.nivel === 'error' ? 'aviso-error' : 'aviso-warn') + '">' +
                (res.nivel === 'error' ? '⛔ ' : '⚠ ') + _h(res.texto) + '</div>';
            const avisosHtml = metadatos.avisos.map(a => '<div class="aviso aviso-warn">⚠ ' + _h(a) + '</div>').join('');
            const opciones = PLACEMENTS_LISTA.includes(metadatos.placement) ? PLACEMENTS_LISTA : PLACEMENTS_LISTA.concat([metadatos.placement]);
            const optHtml = opciones.map(p => '<option value="' + _h(p) + '"' + (p === metadatos.placement ? ' selected' : '') + '>' + _h(p) + '</option>').join('');
            const chipsHtml = EFECTOS_LISTA.map(e => '<button type="button" class="chip" data-ef="' + e[0] + '">' + e[1] + '</button>').join('');
            const refHtml = metadatos.refSrc ? '<div class="efectos-box"><label style="display:flex;align-items:center;gap:6px;font-size:11px;color:#ccc;cursor:pointer"><input type="checkbox" class="chk-ref" checked> Referencia con patrón en el Excel</label><img src="' + metadatos.refSrc + '" alt="referencia" style="display:block;max-width:100%;max-height:90px;margin-top:6px;border:1px solid #555;border-radius:4px;background:#fff"></div>' : '';

            card.innerHTML = `
                ${resHtml}${avisosHtml}
                <div class="thumbnail-img-container">
                    <img src="${dataURL}" alt="${_h(metadatos.nombre)}" class="thumbnail-img">
                </div>
                <div class="thumbnail-info">
                    <div class="info-row">
                        <span class="info-label">Archivo:</span>
                        <span class="info-value">${_h(metadatos.nombre)}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Style:</span>
                        <span class="info-value">${_h(metadatos.style)}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Name:</span>
                        <input type="text" class="mini-input in-name${metadatos.nameExport ? '' : ' vacio'}" value="${_h(metadatos.nameExport)}" placeholder="escribe el NAME">
                    </div>
                    <div class="info-row">
                        <span class="info-label">Placement:</span>
                        <input type="text" class="mini-input sel-placement" list="placementsList" value="${_h(metadatos.placement)}" placeholder="PLACEMENT">
                    </div>
                    <div class="info-row">
                        <span class="info-label">Tamaño:</span>
                        <span class="info-value">${metadatos.ancho}" × ${metadatos.alto}"</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Área:</span>
                        <span class="info-value">${metadatos.area} in²</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">DPI usado:</span>
                        <span class="info-value dpi-usado"${metadatos.dpiEstimado ? ' style="color:#fbbf24"' : ''}>${_h(metadatos.dpiTexto)}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Colores:</span>
                        <span class="info-value">${metadatos.colores}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Píxeles Tinta:</span>
                        <span class="info-value">${metadatos.pixelsInk.toLocaleString()}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">Píxeles Tela:</span>
                        <span class="info-value">${metadatos.pixelsFabric.toLocaleString()}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">% Cobertura:</span>
                        <span class="info-value">${metadatos.porcentajePintado}%</span>
                    </div>
                </div>
                <div class="efectos-box">
                    <div class="efectos-titulo">Efectos especiales de esta pieza</div>
                    <div class="chips">${chipsHtml}</div>
                    <input type="text" class="mini-input in-otro" style="width:100%; text-align:left;" placeholder="Otro efecto o brillo (opcional)">
                    <div class="comentario-preview"></div>
                </div>
                ${refHtml}
                <div class="badge-container">
                    <div class="badge badge-colors">${metadatos.colores} COLORES</div>
                    <div class="badge badge-placement">${_h(metadatos.placement)}</div>
                    <div class="badge badge-complexity">${metadatos.complejidad}</div>
                    <div class="badge badge-tallas">${metadatos.tallas}</div>
                </div>
            `;

            const preview = card.querySelector('.comentario-preview');
            const badgePl = card.querySelector('.badge-placement');
            tarjetasRegistro.push({ m: metadatos, el: preview });
            preview.innerHTML = 'COMMENTS: <b>' + _h(comentarioPieza(metadatos)) + '</b>';

            card.querySelector('.in-name').addEventListener('input', function () {
                metadatos.nameExport = this.value.trim();
                metadatos.name = this.value.trim();
                this.classList.toggle('vacio', !this.value.trim());
            });
            card.querySelector('.sel-placement').addEventListener('input', function () {
                metadatos.placement = this.value;
                badgePl.textContent = this.value;
            });
            card.querySelectorAll('.chip').forEach(btn => {
                btn.addEventListener('click', function () {
                    const ef = this.dataset.ef;
                    const i = metadatos.efectos.indexOf(ef);
                    if (i >= 0) metadatos.efectos.splice(i, 1); else metadatos.efectos.push(ef);
                    this.classList.toggle('active', i < 0);
                    preview.innerHTML = 'COMMENTS: <b>' + _h(comentarioPieza(metadatos)) + '</b>';
                });
            });
            card.querySelector('.in-otro').addEventListener('input', function () {
                metadatos.efectoOtro = this.value;
                preview.innerHTML = 'COMMENTS: <b>' + _h(comentarioPieza(metadatos)) + '</b>';
            });

            const chkRef = card.querySelector('.chk-ref');
            if (chkRef) chkRef.addEventListener('change', function () { metadatos.incluirRef = this.checked; });
            metadatos.cardEl = card;
            thumbnailsGrid.appendChild(card);
        }
        
        function actualizarEstadisticas() {
            const totalImagenes = imagenesProcesadas.length;
            const totalTallas = tallasSeleccionadas.size;
            const totalColores = imagenesProcesadas.reduce((sum, img) => sum + img.metadatos.colores, 0);
            
            projectStats.textContent = `${totalImagenes} imágenes | ${totalTallas} tallas | ${totalColores} colores total`;
        }
        
        // ========== FUNCIONES DE EXPORTACIÓN ==========
        function procesarLote() {
            if (imagenesProcesadas.length === 0) {
                mostrarAlerta('No hay imágenes para procesar', 'error');
                return;
            }
            
            const customer = obtenerCliente();
            const category = document.getElementById('categorySelect').value;
            
            if (!customer || !category) {
                mostrarAlerta('Por favor completa COSTUMER y CATEGORY antes de procesar', 'error');
                return;
            }
            
            if (tallasSeleccionadas.size === 0) {
                mostrarAlerta('Por favor selecciona al menos una talla', 'error');
                return;
            }
            
            mostrarAlerta(`✅ ${imagenesProcesadas.length} imágenes listas - Tallas: ${Array.from(tallasSeleccionadas).join('-')}`, 'success');
        }
        
        // ========== LLENAR LA PLANTILLA REAL (estilos + fórmulas) ==========
        // Edita directamente el XML del .xlsx: no pierde formato, filtros ni comentarios.
        function _xmlEsc(t) {
            return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        function _serialExcel(fecha) {
            // fecha LOCAL (no UTC) -> número de serie de Excel
            return Math.round((Date.UTC(fecha.getFullYear(), fecha.getMonth(), fecha.getDate()) - Date.UTC(1899, 11, 30)) / 86400000);
        }

        async function llenarPlantillaExcel(templateB64, filas, fecha) {
            const zip = await JSZip.loadAsync(templateB64, { base64: true });
            const sheetPath = 'xl/worksheets/sheet1.xml';
            let xml = await zip.file(sheetPath).async('string');

            const COLS = ['A','B','C','D','E','F','G','H','I','J','K','L','M','N','O','P','Q','R','S','T','U','V','W'];

            // Estilo de cada columna = el de la fila 5 de la plantilla (igual que una fila ya llena)
            const fila5 = xml.match(/<row r="5"[^>]*>([\s\S]*?)<\/row>/)[1];
            const estilo = {};
            COLS.forEach(c => {
                const m = fila5.match(new RegExp('<c r="' + c + '5"[^>]*?\\bs="(\\d+)"'));
                estilo[c] = m ? m[1] : '0';
            });

            const serial = _serialExcel(fecha || new Date());
            const txt = (c, r, v) => {
                if (v === undefined || v === null || v === '') return '<c r="' + c + r + '" s="' + estilo[c] + '"/>';
                return '<c r="' + c + r + '" s="' + estilo[c] + '" t="inlineStr"><is><t xml:space="preserve">' + _xmlEsc(v) + '</t></is></c>';
            };
            const num = (c, r, v) => {
                if (typeof v !== 'number' || !isFinite(v)) return '<c r="' + c + r + '" s="' + estilo[c] + '"/>';
                return '<c r="' + c + r + '" s="' + estilo[c] + '"><v>' + v + '</v></c>';
            };
            const fx = (c, r, formula, cache) =>
                '<c r="' + c + r + '" s="' + estilo[c] + '"><f>' + formula + '</f><v>' + cache + '</v></c>';

            filas.forEach((d, i) => {
                const r = 5 + i;
                const G = d.ancho, H = d.alto, K = d.pxFabric, L = d.pxInk;
                const I = H * G, J = K + L;
                const N = J ? K / J : 0, O = J ? L / J : 0, P = I * O;

                const celdas =
                    txt('A', r, d.size) + txt('B', r, d.customer) + txt('C', r, d.category) +
                    txt('D', r, d.style) + txt('E', r, d.name) + txt('F', r, d.placement) +
                    num('G', r, G) + num('H', r, H) +
                    fx('I', r, '+H' + r + '*G' + r, I) +
                    fx('J', r, 'K' + r + '+L' + r, J) +
                    num('K', r, K) + num('L', r, L) +
                    num('M', r, 1) +
                    fx('N', r, 'IFERROR(K' + r + '/J' + r + ',0)', N) +
                    fx('O', r, 'IFERROR(L' + r + '/J' + r + ',0)', O) +
                    fx('P', r, 'IFERROR(I' + r + '*O' + r + ',0)', P) +
                    num('Q', r, serial) + txt('R', r, d.comments) +
                    txt('S', r, '') + txt('T', r, '') + txt('U', r, '') +
                    txt('V', r, d.complejidad) + num('W', r, d.colores);

                const reFila = new RegExp('(<row r="' + r + '"[^>]*>)[\\s\\S]*?(</row>)');
                if (reFila.test(xml)) {
                    xml = xml.replace(reFila, (m, abre, cierra) => abre + celdas + cierra);
                } else {
                    xml = xml.replace('</sheetData>',
                        '<row r="' + r + '" spans="1:23" ht="25.25" customHeight="1">' + celdas + '</row></sheetData>');
                }
            });

            const ultima = 4 + filas.length;
            if (ultima > 201) xml = xml.replace('ref="A4:XFD201"', 'ref="A4:XFD' + ultima + '"');
            if (ultima > 233) xml = xml.replace('ref="A1:XFD233"', 'ref="A1:XFD' + ultima + '"');

            zip.file(sheetPath, xml);
            return zip;
        }

        async function descargarExcelConDatos() {
            if (imagenesProcesadas.length === 0) {
                mostrarAlerta('No hay imágenes procesadas para exportar', 'error');
                return;
            }
            const customer = obtenerCliente();
            const category = document.getElementById('categorySelect').value;
            if (!customer || !category) {
                mostrarAlerta(document.getElementById('customerSelect').value === '__OTRO__' && !customer ? 'Escribe el nombre del cliente (Otro)' : 'Por favor completa COSTUMER y CATEGORY antes de exportar', 'error');
                return;
            }
            if (typeof JSZip === 'undefined') {
                mostrarAlerta('No cargó la librería JSZip. Revisa tu conexión a internet y recarga.', 'error');
                return;
            }
            try {
                const filas = imagenesProcesadas.map(img => {
                    const m = img.metadatos;
                    return {
                        size: m.tallas, customer: customer, category: m.categoria || category,
                        style: m.style, name: m.nameExport, placement: m.placement,
                        ancho: parseFloat(m.ancho), alto: parseFloat(m.alto),
                        pxFabric: Number(m.pixelsFabric), pxInk: Number(m.pixelsInk),
                        comments: comentarioPieza(m), complejidad: m.complejidad, colores: Number(m.colores)
                    };
                });
                const hoy = new Date();
                const zip = await llenarPlantillaExcel(excelTemplateBase64, filas, hoy);
                let nRefs = 0;
                if (document.getElementById('chkRefsExcel').checked) {
                    try { nRefs = await agregarReferenciasAlExcel(zip, imagenesProcesadas.map(i => i.metadatos)); }
                    catch (e) { console.error(e); mostrarAlerta('⚠️ El Excel se generó SIN imágenes de referencia: ' + e.message, 'error'); }
                }
                const blob = await zip.generateAsync({
                    type: 'blob', compression: 'DEFLATE',
                    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                });
                const pad = n => String(n).padStart(2, '0');
                const fecha = hoy.getFullYear() + '-' + pad(hoy.getMonth() + 1) + '-' + pad(hoy.getDate());
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                const estilos = [...new Set(imagenesProcesadas.map(i => (i.metadatos.style || '').trim()).filter(Boolean))];
                a.download = estilos.length
                    ? estilos.join('_').replace(/[\\/:*?"<>|]+/g, '-') + '_PRINT_AREA.xlsx'
                    : 'Costos_Serigrafia_' + customer + '_' + fecha + '.xlsx';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                setTimeout(() => URL.revokeObjectURL(url), 2000);
                const malas = imagenesProcesadas.filter(i => i.metadatos.resolucion.nivel === 'error').map(i => i.metadatos.nombre);
                const estimadas = imagenesProcesadas.filter(i => i.metadatos.dpiEstimado).map(i => i.metadatos.nombre);
                if (estimadas.length) mostrarAlerta('⚠️ Excel descargado, pero ' + estimadas.length + ' imagen(es) NO declaran un DPI válido: sus medidas son ESTIMADAS a ' + DPI_PREDETERMINADO + ' DPI: ' + estimadas.join(', '), 'error');
                if (malas.length) mostrarAlerta('⚠️ Excel descargado, pero ' + malas.length + ' imagen(es) NO tienen ' + DPI_ESPERADO + ' DPI (medidas calculadas con su DPI real; la calidad de impresión puede verse afectada): ' + malas.join(', '), 'error');
                else if (!estimadas.length) mostrarAlerta('✅ Excel descargado: ' + filas.length + ' fila(s) en el formato original, con fórmulas' + (nRefs ? ' y ' + nRefs + ' imagen(es) de referencia debajo' : ''), 'success');
            } catch (err) {
                console.error('Error generando Excel:', err);
                mostrarAlerta('❌ Error generando el Excel: ' + err.message, 'error');
            }
        }

        function copiarDatosAlPortapapeles() {
            if (imagenesProcesadas.length === 0) {
                mostrarAlerta('No hay datos para copiar', 'error');
                return;
            }
            
            const customer = obtenerCliente();
            const category = document.getElementById('categorySelect').value;
            const comments = document.getElementById('commentsInput').value || 'HSWB';
            
            if (!customer || !category) {
                mostrarAlerta('Por favor completa COSTUMER y CATEGORY antes de exportar', 'error');
                return;
            }
            
            try {
                let tsvData = "";
                
                // SOLO DATOS - SIN ENCABEZADOS (para pegar desde fila 5)
                imagenesProcesadas.forEach(imagen => {
                    const m = imagen.metadatos;
                    const porcentajeInk = m.pixelsTotal > 0 ? (m.pixelsInk / m.pixelsTotal) : 0;
                    const porcentajeFabric = m.pixelsTotal > 0 ? (m.pixelsFabric / m.pixelsTotal) : 0;
                    
                    const row = [
                        m.tallas,                    // A: SIZE
                        customer,                    // B: COSTUMER
                        m.categoria || category,     // C: CATEGORY
                        m.style,                     // D: STYLE
                        m.nameExport,                // E: NAME
                        m.placement,                 // F: PLACEMENT
                        m.ancho,                     // G: WIDE (inches)
                        m.alto,                      // H: HIGH (inches)
                        m.area,                      // I: AREA (inches^2)
                        m.pixelsTotal,               // J: TOTAL
                        m.pixelsFabric,              // K: FABRIC
                        m.pixelsInk,                 // L: INK COVERAGE
                        '1',                         // M: TOTAL (%)
                        porcentajeFabric.toFixed(6), // N: FABRIC (%)
                        porcentajeInk.toFixed(6),    // O: INK COVERAGE (%)
                        (parseFloat(m.area) * porcentajeInk).toFixed(6), // P: PRINT AREA
                        new Date().toISOString().slice(0, 10), // Q: DATE
                        avisoDPIExcel(m) ? comments + ' | ' + avisoDPIExcel(m) : comments,  // R: COMMENTS
                        '0',                         // S: Factory Price
                        '0',                         // T: Selling Price
                        m.colores.toString(),        // U: COLORS OR WHITE
                        m.complejidad,               // V: LOW MED HIGH
                        m.colores.toString()         // W: COLORS 1, 2, 3, 4
                    ];
                    
                    tsvData += row.join('\t') + '\n';
                });

                navigator.clipboard.writeText(tsvData).then(() => {
                    mostrarAlerta('✅ Datos copiados al portapapeles - PEGA desde FILA 5 en Excel ✓', 'success');
                }).catch(err => {
                    // Fallback
                    const textarea = document.createElement('textarea');
                    textarea.value = tsvData;
                    document.body.appendChild(textarea);
                    textarea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textarea);
                    mostrarAlerta('✅ Datos copiados - PEGA desde FILA 5 en Excel ✓', 'success');
                });
                
            } catch (error) {
                console.error('Error copiando datos:', error);
                mostrarAlerta('Error al copiar datos: ' + error.message, 'error');
            }
        }
        
        // ========== FUNCIONES BASE64 SIMPLIFICADAS ==========
        function descargarPlantilla() {
            try {
                if (excelTemplateBase64 && excelTemplateBase64 !== "TU_BASE64_COMPLETO_AQUI" && excelTemplateBase64.length > 1000) {
                    descargarDesdeBase64();
                } else {
                    generarPlantillaBasica();
                }
            } catch (error) {
                console.error('Error con base64, generando plantilla básica:', error);
                generarPlantillaBasica();
            }
        }

        function descargarDesdeBase64() {
            try {
                let cleanBase64 = excelTemplateBase64.replace(/^data:[^;]+;base64,/, '');
                cleanBase64 = cleanBase64.replace(/\s/g, '');
                
                if (!/^[A-Za-z0-9+/]*={0,2}$/.test(cleanBase64)) {
                    throw new Error('Base64 contiene caracteres inválidos');
                }
                
                while (cleanBase64.length % 4 !== 0) {
                    cleanBase64 += '=';
                }
                
                const binaryString = atob(cleanBase64);
                const bytes = new Uint8Array(binaryString.length);
                for (let i = 0; i < binaryString.length; i++) {
                    bytes[i] = binaryString.charCodeAt(i);
                }
                
                const blob = new Blob([bytes], {
                    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                });
                
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'Plantilla_Costos_Serigrafia.xlsx';
                a.style.display = 'none';
                
                document.body.appendChild(a);
                a.click();
                
                setTimeout(() => {
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                }, 100);

                mostrarAlerta('✅ Plantilla original descargada correctamente', 'success');
                
            } catch (error) {
                console.error('Error descargando desde base64:', error);
                mostrarAlerta('❌ Error con base64. Generando plantilla básica...', 'error');
                setTimeout(() => {
                    generarPlantillaBasica();
                }, 1000);
            }
        }

        function generarPlantillaBasica() {
            try {
                const wb = XLSX.utils.book_new();
                
                const datos = [
                    ['DESCRIPTIONS', '', '', '', '', 'GRAPHIC', '', '', '', 'PIXELES', '', '', '% PIXELES', '', '', 'PRINT AREA', '', '', 'MATRIX COSTING', '', '', '', ''],
                    ['SIZE', 'COSTUMER', 'CATEGORY', 'STYLE', 'NAME', 'PLACEMENT', 'WIDE (inches)', 'HIGH (inches)', 'AREA (inches^2)', 'TOTAL', 'FABRIC', 'INK COVERAGE', 'TOTAL', 'FABRIC', 'INK COVERAGE', '(INCHES^2) (ONLY INK)', 'DATE', 'COMMENTS', 'Factory Price', 'Selling Price', 'COLORS OR WHITE', 'LOW MED HIGH', 'COLORS 1, 2, 3, 4'],
                    ['', '', '', '', '', '', '', '', '=H3*G3', '', '', '', '1', '=IFERROR(K3/J3,0)', '=IFERROR(L3/J3,0)', '=IFERROR(I3*O3,0)', '', '', '0', '0', '', '', ''],
                    ['', '', '', '', '', '', '', '', '=H4*G4', '', '', '', '1', '=IFERROR(K4/J4,0)', '=IFERROR(L4/J4,0)', '=IFERROR(I4*O4,0)', '', '', '0', '0', '', '', ''],
                    ['', '', '', '', '', '', '', '', '=H5*G5', '', '', '', '1', '=IFERROR(K5/J5,0)', '=IFERROR(L5/J5,0)', '=IFERROR(I5*O5,0)', '', '', '0', '0', '', '', '']
                ];
                
                const ws = XLSX.utils.aoa_to_sheet(datos);
                XLSX.utils.book_append_sheet(wb, ws, "INLINE");
                
                XLSX.writeFile(wb, "Plantilla_Costos_Serigrafia.xlsx");
                mostrarAlerta('✅ Plantilla básica generada y descargada', 'success');
                
            } catch (error) {
                console.error('Error generando plantilla básica:', error);
                mostrarAlerta('❌ Error generando plantilla: ' + error.message, 'error');
            }
        }
        
        function limpiarLote() {
            if (imagenesProcesadas.length === 0) {
                mostrarAlerta('No hay datos para limpiar', 'info');
                return;
            }
            
            if (confirm('¿Estás seguro de que quieres limpiar todos los datos?')) {
                imagenesProcesadas = [];
                thumbnailsGrid.innerHTML = '';
                fileInput.value = '';
                fileCounter.textContent = 'No hay archivos seleccionados';
                progressFill.style.width = '0%';
                projectStats.textContent = '0 imágenes';
                mostrarAlerta('✅ Todos los datos han sido eliminados', 'success');
            }
        }
        
        function mostrarAlerta(mensaje, tipo) {
            const alert = document.createElement('div');
            alert.className = `alert alert-${tipo}`;
            alert.textContent = mensaje;
            alert.style.opacity = '0';
            alert.style.transition = 'opacity 0.3s';
            
            alertContainer.appendChild(alert);
            
            setTimeout(() => {
                alert.style.opacity = '1';
            }, 10);
            
            setTimeout(() => {
                alert.style.opacity = '0';
                setTimeout(() => {
                    if (alert.parentNode) {
                        alert.parentNode.removeChild(alert);
                    }
                }, 300);
            }, 5000);
        }
        
        // ========== RECEPCIÓN DIRECTA DESDE EL EXTRACTOR ==========
        function quitarPorOrigen(origen) {
            imagenesProcesadas = imagenesProcesadas.filter(i => {
                if (i.metadatos.origen !== origen) return true;
                if (i.metadatos.cardEl) i.metadatos.cardEl.remove();
                return false;
            });
        }

        function cargarImagenDesdeBlob(blob) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onerror = () => reject(new Error('No se pudo leer la imagen'));
                reader.onload = e => {
                    const img = new Image();
                    img.onload = () => resolve(img);
                    img.onerror = () => reject(new Error('Imagen no válida'));
                    img.src = e.target.result;
                };
                reader.readAsDataURL(blob);
            });
        }

        // ========== REFERENCIAS DENTRO DEL EXCEL ==========
        const REF_MAX_W = 720, REF_MAX_H = 600;      // px guardados; en Excel se muestran a la mitad (nítidas al ampliar)
        async function descargarReferencia(url) {
            const res = await fetch(url);
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const img = await cargarImagenDesdeBlob(await res.blob());
            const k = Math.min(1, REF_MAX_W / img.width, REF_MAX_H / img.height);
            const c = document.createElement('canvas');
            c.width = Math.max(1, Math.round(img.width * k)); c.height = Math.max(1, Math.round(img.height * k));
            const g = c.getContext('2d');
            g.fillStyle = '#ffffff'; g.fillRect(0, 0, c.width, c.height);
            g.drawImage(img, 0, 0, c.width, c.height);
            return c.toDataURL('image/png');
        }

        function cargarImg(src) {
            return new Promise((resolve, reject) => {
                const i = new Image();
                i.onload = () => resolve(i);
                i.onerror = () => reject(new Error('imagen de referencia no válida'));
                i.src = src;
            });
        }

        // Imagen final: franja con "Fila N · PLACEMENT" + la referencia debajo
        async function componerReferencia(m, fila) {
            const img = await cargarImg(m.refSrc);
            const CAP = 52, MINW = 420;
            const c = document.createElement('canvas');
            c.width = Math.max(img.width, MINW); c.height = img.height + CAP;
            const g = c.getContext('2d');
            g.fillStyle = '#ffffff'; g.fillRect(0, 0, c.width, c.height);
            g.fillStyle = '#f1f1f1'; g.fillRect(0, 0, c.width, CAP);
            g.fillStyle = '#dd1c12'; g.fillRect(0, 0, 8, CAP);
            g.fillStyle = '#222222'; g.font = '600 24px "Segoe UI", Arial, sans-serif'; g.textBaseline = 'middle';
            let txt = 'Fila ' + fila + ' · ' + (m.placement || '');
            while (txt.length > 4 && g.measureText(txt).width > c.width - 28) txt = txt.slice(0, -2) + '…';
            g.fillText(txt, 18, CAP / 2);
            g.drawImage(img, Math.round((c.width - img.width) / 2), CAP);
            g.strokeStyle = '#999999'; g.lineWidth = 2; g.strokeRect(1, 1, c.width - 2, c.height - 2);
            const blob = await new Promise(r => c.toBlob(r, 'image/png'));
            return { buf: await blob.arrayBuffer(), w: c.width, h: c.height };
        }

        // Inserta las referencias en bandas debajo de los datos (fila 5 + n). Devuelve cuántas puso.
        async function agregarReferenciasAlExcel(zip, metas) {
            const items = [];
            metas.forEach((m, i) => { if (m.refSrc && m.incluirRef !== false) items.push({ m: m, fila: 5 + i }); });
            if (!items.length) return 0;

            const sheetPath = 'xl/worksheets/sheet1.xml';
            let xml = await zip.file(sheetPath).async('string');

            // Anchos de columna (A..W) -> píxeles, para repartir las imágenes sin encimarlas
            const NCOLS = 23, GAP = 16;
            const dcw = parseFloat((xml.match(/defaultColWidth="([\d.]+)"/) || [])[1]) || 8.66;
            const wCols = new Array(NCOLS).fill(dcw);
            (xml.match(/<col [^>]*\/>/g) || []).forEach(t => {
                const mn = +(t.match(/min="(\d+)"/) || [])[1], mx = +(t.match(/max="(\d+)"/) || [])[1];
                const w = parseFloat((t.match(/width="([\d.]+)"/) || [])[1]);
                if (!mn || !mx || !w) return;
                for (let c = mn; c <= Math.min(mx, NCOLS); c++) wCols[c - 1] = w;
            });
            const starts = [0];
            for (let c = 0; c < NCOLS; c++) starts.push(starts[c] + Math.round(wCols[c] * 7 + 5));
            const totalPx = starts[NCOLS];
            const drh = parseFloat((xml.match(/defaultRowHeight="([\d.]+)"/) || [])[1]) || 25.25;
            const rowPx = drh * 96 / 72;

            let row = 4 + metas.length + 3;       // fila (base 1) donde empieza la 1ª banda: 2 filas libres tras los datos
            let colIdx = 0, bandH = 0;
            const anchors = [], rels = [];
            for (let k = 0; k < items.length; k++) {
                const comp = await componerReferencia(items[k].m, items[k].fila);
                const wCss = comp.w / 2, hCss = comp.h / 2;
                if (colIdx > 0 && starts[colIdx] + wCss > totalPx) {      // no cabe: nueva banda
                    row += Math.ceil((bandH + GAP) / rowPx); bandH = 0; colIdx = 0;
                }
                const n = k + 1, cx = Math.round(wCss * 9525), cy = Math.round(hCss * 9525);
                zip.file('xl/media/referencia' + n + '.png', comp.buf);
                rels.push('<Relationship Id="rId' + n + '" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/referencia' + n + '.png"/>');
                anchors.push(
                    '<xdr:oneCellAnchor><xdr:from><xdr:col>' + colIdx + '</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>' + (row - 1) +
                    '</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:ext cx="' + cx + '" cy="' + cy + '"/>' +
                    '<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="' + (n + 1) + '" name="Referencia ' + n + '" descr="' + _xmlEsc('Fila ' + items[k].fila + ' ' + (items[k].m.placement || '')) + '"/>' +
                    '<xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr></xdr:nvPicPr>' +
                    '<xdr:blipFill><a:blip r:embed="rId' + n + '"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>' +
                    '<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="' + cx + '" cy="' + cy + '"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr>' +
                    '</xdr:pic><xdr:clientData/></xdr:oneCellAnchor>');
                bandH = Math.max(bandH, hCss);
                const nextX = starts[colIdx] + wCss + GAP;
                let nc = colIdx + 1;
                while (nc < NCOLS && starts[nc] < nextX) nc++;
                colIdx = nc;
            }

            zip.file('xl/drawings/drawing1.xml',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
                '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" ' +
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ' +
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' + anchors.join('') + '</xdr:wsDr>');
            zip.file('xl/drawings/_rels/drawing1.xml.rels',
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + rels.join('') + '</Relationships>');

            // [Content_Types].xml
            let ct = await zip.file('[Content_Types].xml').async('string');
            if (!/Extension="png"/i.test(ct)) ct = ct.replace(/(<Types[^>]*>)/, '$1<Default Extension="png" ContentType="image/png"/>');
            ct = ct.replace('</Types>', '<Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/></Types>');
            zip.file('[Content_Types].xml', ct);

            // relación hoja -> dibujo (sin tocar las de comentarios e impresora)
            const relPath = 'xl/worksheets/_rels/sheet1.xml.rels';
            let rl = await zip.file(relPath).async('string');
            rl = rl.replace('</Relationships>', '<Relationship Id="rIdRefs1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/></Relationships>');
            zip.file(relPath, rl);

            // <drawing> va justo antes de <legacyDrawing> (orden exigido por Excel)
            if (xml.indexOf('<legacyDrawing') >= 0) xml = xml.replace('<legacyDrawing', '<drawing r:id="rIdRefs1"/><legacyDrawing');
            else xml = xml.replace('</worksheet>', '<drawing r:id="rIdRefs1"/></worksheet>');
            zip.file(sheetPath, xml);
            return items.length;
        }

        // p = { origen, pdf, style, teamName, sizes:[], pieces:[{id, placement, file, sizes:[], url, refUrl}] }
        // pieces[].sizes: tallas propias de esa pieza (p. ej. un cuello solo para S-M); si no trae, se usan las de p.sizes
        async function recibirDesdeExtractor(p) {
            const piezas = p.pieces || [];
            const fallos = [];
            [].concat(p.sizes || [], ...piezas.map(pz => pz.sizes || [])).forEach(t => { if (/^\d+$/.test(String(t))) tallasNumericas.add(String(t)); });
            if (p.sizes && p.sizes.length) {
                tallasSeleccionadas = new Set(p.sizes);
                inicializarTallas();
            }
            quitarPorOrigen(p.origen);          // reenviar el mismo PDF reemplaza sus piezas, no duplica
            if (p.category) {
                const selCat = document.getElementById('categorySelect');
                if (Array.from(selCat.options).some(o => o.value === p.category)) selCat.value = p.category;
            }
            const tallasTxt = Array.from(tallasSeleccionadas).join('-');
            fileCounter.textContent = 'Recibiendo ' + piezas.length + ' pieza(s) del extractor...';
            progressFill.style.width = '0%';
            let ok = 0;
            for (let i = 0; i < piezas.length; i++) {
                const pz = piezas[i];
                try {
                    const res = await fetch(pz.url);
                    if (!res.ok) throw new Error('HTTP ' + res.status);
                    const blob = await res.blob();
                    const dpiInfo = leerDPIdePNG(await blob.arrayBuffer());
                    const img = await cargarImagenDesdeBlob(blob);
                    const file = new File([blob], pz.file || (pz.placement + '.png'), { type: 'image/png' });
                    let refSrc = null;
                    if (pz.refUrl) {
                        try { refSrc = await descargarReferencia(pz.refUrl); }
                        catch (e) { fallos.push('referencia de ' + pz.placement + ' (' + e.message + ')'); }
                    }
                    procesarImagen(img, file, dpiInfo, {
                        origen: p.origen, style: p.style, teamName: p.teamName,
                        placement: pz.placement, tallas: (pz.sizes && pz.sizes.length) ? pz.sizes.join('-') : tallasTxt,
                        refSrc: refSrc, categoria: p.category || ''
                    });
                    ok++;
                } catch (err) {
                    fallos.push(pz.placement + ' (' + err.message + ')');
                }
                progressFill.style.width = ((i + 1) / piezas.length * 100) + '%';
                await new Promise(r => setTimeout(r, 0));   // deja respirar a la interfaz
            }
            actualizarEstadisticas();
            fileCounter.textContent = ok + ' pieza(s) recibida(s) de ' + (p.pdf || 'el extractor');
            if (advertenciasLote.length) {
                mostrarAlerta('⛔ Resolución incorrecta (se requieren ' + DPI_ESPERADO + ' DPI) en: ' + advertenciasLote.join(', '), 'error');
                advertenciasLote = [];
            }
            if (fallos.length) mostrarAlerta('⚠️ No se pudieron cargar: ' + fallos.join(' | '), 'error');
            else mostrarAlerta('✅ ' + ok + ' pieza(s) recibida(s) del extractor', 'success');
            avisarDPIEstimado();
            return { ok: ok, fallos: fallos, total: imagenesProcesadas.length };
        }

        // Inicialización
        document.addEventListener('DOMContentLoaded', function() {
            inicializarTallas();
            const dl = document.getElementById('placementsList');
            dl.innerHTML = PLACEMENTS_LISTA.map(p => '<option value="' + p + '"></option>').join('');
            if (new URLSearchParams(location.search).get('embed') === '1') {
                document.querySelector('.header').style.display = 'none';
                document.body.style.padding = '8px';
            }
            
            document.getElementById('customerSelect').value = 'Fanatics';
            document.getElementById('categorySelect').value = 'NFL Elite';
            document.getElementById('commentsInput').value = 'HSWB';
            
            mostrarAlerta('✅ Sistema Tegra listo. Carga tus imágenes PNG para comenzar.', 'success');
            window.__costosListo = true;
        });
    </script>
</body>
</html>"""

EXCEL_TEMPLATE_B64 = "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wQ5ehr2Pi3mHoDah+1aLZlWCXW2bVodaEdtk3g/dpUsp3HjhPrhQbmCdo4rNgSWwUWW5PloIXg2zYu5p9VX2vuXMbStnT53TBlB2WnoeQ3krL1zN0DdYnaqmUBtYwWqy3i4F85Y7Zfd2O+WttivrlpxX4t9281aVLMJWbA4bPy1WWxHWu0696u7tgzWQn1u5NVhfuFjCsMI+sbkU59JMc4/i3Lfdep7G362DNw811AZp75e4f/95wIqOt5Y6vm6+7tbxakzjTVN0e5tbdofM2d7wbpVP2ybyve+dtop8edXxi9D9o9DNbsLx0gq3ti1+U9X9vGr1Fq35rvetB1lQqpR4H8SXu1xt++U0DWr3NN8rF3w1vGH7cINJkVRoN7r3vRsppKkz2naKr17TDhXby/Z9zXpLW2FfjXRzqTysNOz65YaoSmvLklC0CDbkTUPe0aUdIuaw/U44r86GPgr5GeZKOrJ1SfTV9LfZk1S8K5UeldWfD6zuSEU+H1i9R3kcMuEDgkPMo9Xyv9M0OpiKbhzoDjtjuO7Ddff5p57zkHb4vpitkgFZF+QefTsvSP8WQTbmX86efUt7+p3thy9q+7arLx2vjbrD+LR+ng6H3SWpu5gkgzwZzXrWWHH+JMviUe+u9iD1Jii7mh1PkuLFP4L5n6Pirz+6fzb7Jwhn7/22quJOOhikv8b92n/f3cTZIBn9ct9AyzwKq9CJ66Tfj0fzKb5FRU1SRe2AVZFjVdQmVRSxYEcs2MWkodXEwh0GLN5hyAIehjTihkbc0IgbGnFLI25pxB2NuKMRdzTinkbc04g3acSbNOJNGnGaZoY00QxpqhnSZDOk6WZIE86QppyGppwmaLFqCkNaTZ5WU8SqyVhaTTTilkbc0ohbGnFHI+5oxD2NuKcR9zTiTRrxJo14i0a8RSPeohFv04i3acQjGvGIRjxiEbcBi7ilKaelKaelKaelKaelKaelKaelKaelKaelKaelKaelKaelKaelKaelKaelKaelKaelKaelKaelKaelKaelKaelKaelKaelKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaejKaenKaenKaenKaenKaenKaenKaenKaenKaenKaenKaenKaenKaen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"


def _port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--inspect":
        if len(sys.argv) < 3:
            print("Uso: python Textile_Vector_Extractor.py --inspect archivo.pdf", file=sys.stderr)
            sys.exit(2)
        src = Path(sys.argv[2])
        try:
            data = src.read_bytes()
        except OSError as exc:
            print(f"❌ No se pudo leer '{src}': {exc}", file=sys.stderr)
            sys.exit(1)
        try:
            report = inspect_pdf(data, src.name)
        except Exception as exc:
            print(f"❌ No se pudo analizar '{src}': {exc}", file=sys.stderr)
            sys.exit(1)
        dest = src.with_suffix(".inspect.json")
        dest.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Diagnóstico escrito en: {dest}")
        sys.exit(0)
    if _port_in_use(PORT):
        print(f"\n❌ El puerto {PORT} ya está ocupado. Ciérralo y reinicia.\n")
        sys.exit(1)
    if Image is None:
        print("⚠️  Pillow no está instalado (pip install pillow).")
    print("\n==========================================")
    print(f"🚀 TEGRA Pre-Press Suite {VERSION} iniciado")
    print(f"🌐 Abre tu navegador en: http://localhost:{PORT}")
    print("==========================================\n")
    threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    app.run(port=PORT, threaded=True)