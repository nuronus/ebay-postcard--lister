"""
Barcode label printer for inventory management.

Generates sequential barcode labels formatted for Avery 5167 labels:
- Label size: 0.5" x 1.75" (12.7mm x 44.45mm)
- 80 labels per sheet (4 columns x 20 rows)
"""

import json
from pathlib import Path
from io import BytesIO
from datetime import datetime

from barcode import Code128
from barcode.writer import ImageWriter
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from PIL import Image


# Avery 5167 label specifications (in inches)
LABEL_WIDTH = 1.75
LABEL_HEIGHT = 0.5
LABELS_PER_ROW = 4
LABELS_PER_COL = 20
LABELS_PER_SHEET = LABELS_PER_ROW * LABELS_PER_COL  # 80

# Page margins (Avery 5167 specs)
LEFT_MARGIN = 0.3
TOP_MARGIN = 0.5
H_GAP = 0.3  # Horizontal gap between labels
V_GAP = 0.0  # Vertical gap between labels

# Barcode settings
BARCODE_PREFIX = "PC"  # Postcard prefix

# File to track barcode sequence
SEQUENCE_FILE = Path(__file__).parent / "barcode_sequence.json"


def _load_sequence() -> int:
    """Load the current barcode sequence number."""
    if SEQUENCE_FILE.exists():
        try:
            with open(SEQUENCE_FILE, "r") as f:
                data = json.load(f)
                return data.get("next_sequence", 1)
        except (json.JSONDecodeError, IOError):
            pass
    return 1


def _save_sequence(next_seq: int) -> None:
    """Save the next barcode sequence number."""
    data = {"next_sequence": next_seq, "updated_at": datetime.now().isoformat()}
    with open(SEQUENCE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def generate_barcode_number(sequence: int) -> str:
    """Generate a barcode number from sequence."""
    return f"{BARCODE_PREFIX}{sequence:06d}"


def create_barcode_image(barcode_number: str) -> Image.Image:
    """
    Create a barcode image for the given number.

    Args:
        barcode_number: The barcode string to encode

    Returns:
        PIL Image of the barcode
    """
    # Create barcode with ImageWriter
    writer = ImageWriter()
    writer.set_options({
        "module_width": 0.2,  # Width of barcode bars
        "module_height": 8.0,  # Height of bars in mm
        "font_size": 8,
        "text_distance": 2.0,
        "quiet_zone": 2.0,
    })

    code = Code128(barcode_number, writer=writer)

    # Write to BytesIO
    buffer = BytesIO()
    code.write(buffer)
    buffer.seek(0)

    # Open as PIL Image
    img = Image.open(buffer)
    return img.copy()  # Copy to detach from buffer


def generate_label_sheet_pdf(
    output_path: str | Path,
    num_labels: int = LABELS_PER_SHEET,
    start_position: int = 1
) -> tuple[str, list[str]]:
    """
    Generate a PDF sheet of sequential barcode labels.

    Args:
        output_path: Path for the output PDF file
        num_labels: Number of labels to generate (max 80 per sheet)
        start_position: Starting position on the sheet (1-80, for partial sheets)

    Returns:
        Tuple of (pdf_path, list of barcode numbers generated)
    """
    output_path = Path(output_path)

    # Validate inputs
    num_labels = min(num_labels, LABELS_PER_SHEET - start_position + 1)
    if num_labels <= 0:
        raise ValueError("No labels to generate")

    # Get starting sequence
    current_seq = _load_sequence()
    barcodes_generated = []

    # Create PDF
    c = canvas.Canvas(str(output_path), pagesize=LETTER)
    page_width, page_height = LETTER

    label_idx = start_position - 1  # 0-indexed

    for i in range(num_labels):
        # Generate barcode number
        barcode_num = generate_barcode_number(current_seq)
        barcodes_generated.append(barcode_num)

        # Calculate position on sheet
        row = label_idx // LABELS_PER_ROW
        col = label_idx % LABELS_PER_ROW

        # Calculate x, y position (from bottom-left in reportlab)
        x = LEFT_MARGIN + col * (LABEL_WIDTH + H_GAP)
        y = page_height / inch - TOP_MARGIN - (row + 1) * (LABEL_HEIGHT + V_GAP)

        # Generate barcode image
        barcode_img = create_barcode_image(barcode_num)

        # Save to temp buffer for reportlab
        img_buffer = BytesIO()
        barcode_img.save(img_buffer, format='PNG')
        img_buffer.seek(0)

        # Calculate image dimensions to fit in label
        # Leave some padding
        max_width = LABEL_WIDTH * inch - 4
        max_height = LABEL_HEIGHT * inch - 4

        img_width, img_height = barcode_img.size
        scale = min(max_width / img_width, max_height / img_height)

        draw_width = img_width * scale
        draw_height = img_height * scale

        # Center in label
        draw_x = x * inch + (LABEL_WIDTH * inch - draw_width) / 2
        draw_y = y * inch + (LABEL_HEIGHT * inch - draw_height) / 2

        # Draw barcode
        from reportlab.lib.utils import ImageReader
        c.drawImage(
            ImageReader(img_buffer),
            draw_x, draw_y,
            width=draw_width, height=draw_height
        )

        current_seq += 1
        label_idx += 1

        # Start new page if needed
        if label_idx >= LABELS_PER_SHEET and i < num_labels - 1:
            c.showPage()
            label_idx = 0

    c.save()

    # Save updated sequence
    _save_sequence(current_seq)

    return str(output_path), barcodes_generated


def generate_multiple_sheets(
    output_path: str | Path,
    num_sheets: int = 1
) -> tuple[str, list[str]]:
    """
    Generate multiple full sheets of barcode labels.

    Args:
        output_path: Path for the output PDF file
        num_sheets: Number of full sheets to generate

    Returns:
        Tuple of (pdf_path, list of all barcode numbers generated)
    """
    output_path = Path(output_path)
    total_labels = num_sheets * LABELS_PER_SHEET

    # Get starting sequence
    current_seq = _load_sequence()
    barcodes_generated = []

    # Create PDF
    c = canvas.Canvas(str(output_path), pagesize=LETTER)
    page_width, page_height = LETTER

    for sheet in range(num_sheets):
        if sheet > 0:
            c.showPage()

        for label_idx in range(LABELS_PER_SHEET):
            # Generate barcode number
            barcode_num = generate_barcode_number(current_seq)
            barcodes_generated.append(barcode_num)

            # Calculate position on sheet
            row = label_idx // LABELS_PER_ROW
            col = label_idx % LABELS_PER_ROW

            # Calculate x, y position
            x = LEFT_MARGIN + col * (LABEL_WIDTH + H_GAP)
            y = page_height / inch - TOP_MARGIN - (row + 1) * (LABEL_HEIGHT + V_GAP)

            # Generate barcode image
            barcode_img = create_barcode_image(barcode_num)

            # Save to temp buffer
            img_buffer = BytesIO()
            barcode_img.save(img_buffer, format='PNG')
            img_buffer.seek(0)

            # Calculate dimensions
            max_width = LABEL_WIDTH * inch - 4
            max_height = LABEL_HEIGHT * inch - 4

            img_width, img_height = barcode_img.size
            scale = min(max_width / img_width, max_height / img_height)

            draw_width = img_width * scale
            draw_height = img_height * scale

            draw_x = x * inch + (LABEL_WIDTH * inch - draw_width) / 2
            draw_y = y * inch + (LABEL_HEIGHT * inch - draw_height) / 2

            from reportlab.lib.utils import ImageReader
            c.drawImage(
                ImageReader(img_buffer),
                draw_x, draw_y,
                width=draw_width, height=draw_height
            )

            current_seq += 1

    c.save()
    _save_sequence(current_seq)

    return str(output_path), barcodes_generated


def get_next_barcode_number() -> str:
    """Get the next barcode number without incrementing."""
    return generate_barcode_number(_load_sequence())


def peek_barcode_range(count: int) -> list[str]:
    """Preview the next N barcode numbers without generating them."""
    start = _load_sequence()
    return [generate_barcode_number(start + i) for i in range(count)]


if __name__ == "__main__":
    # Test: Generate a single sheet
    import os
    output_dir = Path(__file__).parent
    pdf_path, barcodes = generate_label_sheet_pdf(
        output_dir / "test_barcodes.pdf",
        num_labels=10
    )
    print(f"Generated PDF: {pdf_path}")
    print(f"Barcodes: {barcodes}")
    os.startfile(pdf_path)  # Open on Windows
