"""Genera test_garment.pdf (PDF sintético con 2 piezas: FRONT 300x300 pt y BACK 100x100 pt).
La ruta de salida es relativa a este archivo, no depende del equipo."""
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
try:
    import pymupdf as fitz
except ImportError:
    import fitz

DEFAULT_OUT = Path(__file__).resolve().parent / "test_garment.pdf"


def build(path=DEFAULT_OUT):
    doc = fitz.open()
    page = doc.new_page(width=900, height=700)
    page.insert_text((40, 40), "Style Name: TEST-0001-ABC", fontsize=12)
    # FRONT: pieza grande (300x300 pt) con arte de color
    page.insert_text((60, 90), "Piece Name: FRONT", fontsize=11)
    page.draw_rect(fitz.Rect(60, 110, 360, 410), color=None, fill=(0.8, 0.1, 0.1))
    page.draw_circle(fitz.Point(210, 260), 70, color=None, fill=(0.1, 0.2, 0.8))
    # BACK: pieza pequeña (100x100 pt)
    page.insert_text((520, 90), "Piece Name: BACK", fontsize=11)
    page.draw_rect(fitz.Rect(520, 110, 620, 210), color=None, fill=(0.1, 0.6, 0.2))
    doc.save(str(path))
    doc.close()
    return Path(path)


if __name__ == "__main__":
    print("PDF generado en:", build())
