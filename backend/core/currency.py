from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


CURRENCY_CODE = "NGN"
CURRENCY_NAME = "Nigerian Naira"
CURRENCY_SYMBOL = "₦"
EXCEL_CURRENCY_NUMBER_FORMAT = '"₦"#,##0.00'
PDF_CURRENCY_FONT_NAME = "TreasurelandCurrency"
PDF_CURRENCY_FONT_PATH = Path(__file__).resolve().parent / "assets" / "fonts" / "DejaVuSans.ttf"


def format_currency(value):
    amount = Decimal(str(value or "0"))
    return f"{CURRENCY_SYMBOL}{amount:,.2f}"


@lru_cache(maxsize=1)
def register_pdf_currency_font():
    if not PDF_CURRENCY_FONT_PATH.is_file():
        raise ImproperlyConfigured(f"Bundled receipt font is missing: {PDF_CURRENCY_FONT_PATH}")
    try:
        font = TTFont(PDF_CURRENCY_FONT_NAME, str(PDF_CURRENCY_FONT_PATH))
    except Exception as exc:
        raise ImproperlyConfigured(f"Bundled receipt font is invalid: {PDF_CURRENCY_FONT_PATH}") from exc
    if ord(CURRENCY_SYMBOL) not in font.face.charToGlyph:
        raise ImproperlyConfigured("Bundled receipt font does not contain the Nigerian Naira glyph U+20A6.")
    if PDF_CURRENCY_FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(font)
    return PDF_CURRENCY_FONT_NAME