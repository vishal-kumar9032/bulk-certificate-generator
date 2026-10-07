import logging
import os
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from app.settings import settings

logger = logging.getLogger(__name__)

# Primary font configuration with graceful fallback
PRIMARY_FONT_NAME = "CertificateFont"
FALLBACK_FONT_NAME = "Helvetica"
ACTIVE_FONT_NAME = FALLBACK_FONT_NAME


def initialize_fonts() -> str:
    """Register DejaVuSans TrueType font if available, or fall back to Helvetica."""
    global ACTIVE_FONT_NAME
    font_file = settings.FONTS_DIR / "DejaVuSans.ttf"

    if font_file.exists():
        try:
            pdfmetrics.registerFont(TTFont(PRIMARY_FONT_NAME, str(font_file)))
            ACTIVE_FONT_NAME = PRIMARY_FONT_NAME
            logger.info("Registered primary font '%s' from %s", PRIMARY_FONT_NAME, font_file)
            return ACTIVE_FONT_NAME
        except Exception as e:
            logger.warning("Failed to register font from %s: %s. Falling back to Helvetica.", font_file, e)
    else:
        logger.warning("Font file %s not found. Falling back to Helvetica (Unicode limited).", font_file)

    ACTIVE_FONT_NAME = FALLBACK_FONT_NAME
    return ACTIVE_FONT_NAME


# Initialize font on module load
initialize_fonts()


@dataclass
class CertificateData:
    recipient_name: str
    event_name: str
    issue_date: date | str
    issuer_name: Optional[str] = None
    verification_code: Optional[str] = None


def fit_font_size(
    text: str,
    font_name: str,
    start_size: float,
    min_size: float,
    max_width: float,
) -> float:
    """Calculate font size that fits text within max_width, down to min_size."""
    size = start_size
    while size > min_size:
        w = pdfmetrics.stringWidth(text, font_name, size)
        if w <= max_width:
            return size
        size -= 1.0
    return min_size


def render_certificate(data: CertificateData, output_path: Path) -> None:
    """
    Render a single landscape A4 certificate to output_path.
    Uses atomic writing (temp file -> rename) to prevent partial/corrupted files.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Use unique temp file in the same directory for atomic rename
    temp_path = output_path.parent / f".tmp_{uuid.uuid4().hex}_{output_path.name}"

    try:
        # A4 Landscape dimensions: ~841.89 pt x 595.28 pt
        page_width, page_height = landscape(A4)
        c = canvas.Canvas(str(temp_path), pagesize=(page_width, page_height))
        c.setTitle(f"Certificate - {data.recipient_name}")

        font_name = ACTIVE_FONT_NAME

        # Verify that the text can be rendered without font encoding errors
        test_strings = [data.recipient_name, data.event_name, data.issuer_name or ""]
        for s in test_strings:
            try:
                pdfmetrics.stringWidth(s, font_name, 12)
            except Exception as exc:
                raise ValueError(
                    f"Text contains characters that cannot be rendered with font '{font_name}': {exc}"
                ) from exc

        # ----------------- Visual Styling & Borders -----------------
        # Colors
        primary_color = HexColor("#1E3A8A")  # Deep Royal Blue
        accent_color = HexColor("#B45309")   # Warm Amber / Bronze
        text_dark = HexColor("#1F2937")      # Charcoal
        text_muted = HexColor("#4B5563")     # Slate Gray
        border_outer = HexColor("#1E3A8A")   # Outer border
        border_inner = HexColor("#D97706")   # Inner border

        # Outer thick border
        c.setStrokeColor(border_outer)
        c.setLineWidth(3)
        c.rect(20, 20, page_width - 40, page_height - 40)

        # Inner thin accent border
        c.setStrokeColor(border_inner)
        c.setLineWidth(1)
        c.rect(26, 26, page_width - 52, page_height - 52)

        # Subtle decorative corner squares
        corner_size = 12
        c.setFillColor(border_inner)
        for cx, cy in [
            (26, 26),
            (page_width - 26 - corner_size, 26),
            (26, page_height - 26 - corner_size),
            (page_width - 26 - corner_size, page_height - 26 - corner_size),
        ]:
            c.rect(cx, cy, corner_size, corner_size, fill=1, stroke=0)

        center_x = page_width / 2.0

        # ----------------- Issuer Header (Top) -----------------
        if data.issuer_name:
            c.setFont(font_name, 14)
            c.setFillColor(accent_color)
            c.drawCentredString(center_x, page_height - 65, data.issuer_name.upper())

        # ----------------- Certificate Title -----------------
        c.setFont(font_name, 28)
        c.setFillColor(primary_color)
        c.drawCentredString(center_x, page_height - 110, "CERTIFICATE OF COMPLETION")

        # Decorative title line
        c.setStrokeColor(border_inner)
        c.setLineWidth(1.5)
        c.line(center_x - 140, page_height - 122, center_x + 140, page_height - 122)

        # ----------------- "This is to certify that" -----------------
        c.setFont(font_name, 14)
        c.setFillColor(text_muted)
        c.drawCentredString(center_x, page_height - 165, "This is to certify that")

        # ----------------- Recipient Name (Prominent & Auto-scaled) -----------------
        max_name_width = page_width - 160
        name_font_size = fit_font_size(
            data.recipient_name, font_name, start_size=32, min_size=16, max_width=max_name_width
        )
        c.setFont(font_name, name_font_size)
        c.setFillColor(text_dark)
        c.drawCentredString(center_x, page_height - 225, data.recipient_name)

        # Recipient underline
        name_actual_width = min(
            pdfmetrics.stringWidth(data.recipient_name, font_name, name_font_size) + 40,
            max_name_width,
        )
        c.setStrokeColor(accent_color)
        c.setLineWidth(1)
        c.line(
            center_x - (name_actual_width / 2.0),
            page_height - 235,
            center_x + (name_actual_width / 2.0),
            page_height - 235,
        )

        # ----------------- "has successfully completed" -----------------
        c.setFont(font_name, 14)
        c.setFillColor(text_muted)
        c.drawCentredString(center_x, page_height - 280, "has successfully completed")

        # ----------------- Event Name (Wrapped & Centered) -----------------
        max_event_width = page_width - 200
        event_lines = simpleSplit(data.event_name, font_name, 20, max_event_width)
        c.setFont(font_name, 20)
        c.setFillColor(primary_color)

        current_y = page_height - 325
        for line in event_lines[:2]:  # At most 2 lines for event title
            c.drawCentredString(center_x, current_y, line)
            current_y -= 26

        # ----------------- Issue Date & Issuer Details -----------------
        formatted_date = (
            data.issue_date.strftime("%B %d, %Y")
            if isinstance(data.issue_date, date)
            else str(data.issue_date)
        )

        meta_y = 130
        c.setFont(font_name, 11)
        c.setFillColor(text_muted)
        c.drawCentredString(center_x, meta_y, f"Issued on: {formatted_date}")

        if data.issuer_name:
            c.drawCentredString(center_x, meta_y - 20, f"Issued by: {data.issuer_name}")

        # ----------------- Verification Code Footer -----------------
        if data.verification_code:
            c.setFont(font_name, 9)
            c.setFillColor(HexColor("#6B7280"))
            c.drawCentredString(
                center_x, 48, f"Verification Code: {data.verification_code}"
            )

        c.showPage()
        c.save()

        # Atomic rename replacing destination
        os.replace(temp_path, output_path)

    except Exception:
        # Clean up temporary file if render failed
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise
