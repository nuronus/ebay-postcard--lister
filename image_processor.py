"""Image processing for eBay listings - places images on wood table background."""

import base64
import io
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter


def create_wood_background(width: int, height: int) -> Image.Image:
    """
    Generate a realistic wood plank table texture background.

    Args:
        width: Width of the background
        height: Height of the background

    Returns:
        PIL Image with wood texture
    """
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    plank_width = random.randint(80, 120)
    plank_colors = [
        (235, 210, 170),
        (225, 200, 160),
        (240, 218, 180),
        (230, 205, 165),
        (220, 195, 155),
    ]

    x = 0
    while x < width:
        current_plank_width = plank_width + random.randint(-15, 15)
        base_color = random.choice(plank_colors)

        for px in range(x, min(x + current_plank_width, width)):
            for py in range(height):
                variation = random.randint(-8, 8)
                color = (
                    max(0, min(255, base_color[0] + variation)),
                    max(0, min(255, base_color[1] + variation)),
                    max(0, min(255, base_color[2] + variation))
                )
                draw.point((px, py), fill=color)

        for grain_y in range(0, height, random.randint(4, 8)):
            grain_variation = random.randint(-20, 10)
            grain_color = (
                max(0, min(255, base_color[0] + grain_variation)),
                max(0, min(255, base_color[1] + grain_variation)),
                max(0, min(255, base_color[2] + grain_variation))
            )
            wave = random.randint(-2, 2)
            draw.line(
                [(x, grain_y + wave), (min(x + current_plank_width, width), grain_y + wave)],
                fill=grain_color,
                width=random.randint(1, 2)
            )

        gap_color = (160, 130, 95)
        if x + current_plank_width < width:
            draw.line(
                [(x + current_plank_width, 0), (x + current_plank_width, height)],
                fill=gap_color,
                width=3
            )

        x += current_plank_width + 3

    num_knots = random.randint(2, 5)
    for _ in range(num_knots):
        knot_x = random.randint(30, width - 30)
        knot_y = random.randint(30, height - 30)
        knot_size = random.randint(12, 25)

        for r in range(knot_size, 0, -1):
            factor = (knot_size - r) / knot_size
            color = (
                int(170 + factor * 40),
                int(140 + factor * 35),
                int(100 + factor * 30)
            )
            draw.ellipse(
                [knot_x - r, knot_y - r, knot_x + r, knot_y + r],
                fill=color
            )

        for ring in range(3, knot_size, 4):
            ring_color = (150, 120, 85)
            draw.arc(
                [knot_x - ring, knot_y - ring, knot_x + ring, knot_y + ring],
                0, 360,
                fill=ring_color,
                width=1
            )

    img = img.filter(ImageFilter.GaussianBlur(radius=0.8))

    return img


def process_image(image_path: Path, padding: int = 150) -> tuple[Image.Image, bytes]:
    """
    Load an image and place it centered on a wood table background.

    Args:
        image_path: Path to the source image
        padding: Pixels of padding around the image

    Returns:
        Tuple of (processed PIL Image, JPEG bytes for upload)
    """
    original = Image.open(image_path)

    if original.mode == "RGBA":
        background = Image.new("RGBA", original.size, (255, 255, 255, 255))
        background.paste(original, mask=original.split()[3])
        original = background.convert("RGB")
    elif original.mode != "RGB":
        original = original.convert("RGB")

    new_width = original.width + (padding * 2)
    new_height = original.height + (padding * 2)

    canvas = create_wood_background(new_width, new_height)

    paste_x = padding
    paste_y = padding
    canvas.paste(original, (paste_x, paste_y))

    jpeg_buffer = io.BytesIO()
    canvas.save(jpeg_buffer, format="JPEG", quality=95)
    jpeg_bytes = jpeg_buffer.getvalue()

    return canvas, jpeg_bytes


def image_to_base64(image_bytes: bytes) -> str:
    """Convert image bytes to base64 string for API calls."""
    return base64.b64encode(image_bytes).decode("utf-8")


def get_image_files(directory: Path) -> list[Path]:
    """
    Get all image files from a directory.

    Args:
        directory: Path to scan for images

    Returns:
        List of paths to image files
    """
    extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
    images = []

    for file in directory.iterdir():
        if file.is_file() and file.suffix.lower() in extensions:
            images.append(file)

    return sorted(images)


def save_processed_image(image: Image.Image, output_path: Path) -> None:
    """Save processed image to disk."""
    image.save(output_path, format="JPEG", quality=95)


def create_bundle_collage(
    image_paths: list[Path],
    max_width: int = 1600,
    max_height: int = 1600,
    padding: int = 40,
    spacing: int = 20
) -> tuple[Image.Image, bytes]:
    """
    Create a collage image from multiple postcards for bundle listings.

    Arranges postcards in an attractive grid layout on a wood background.
    Automatically scales to fit all images regardless of count.

    Args:
        image_paths: List of paths to postcard images
        max_width: Maximum width of the collage
        max_height: Maximum height of the collage
        padding: Padding around the edges
        spacing: Space between images

    Returns:
        Tuple of (collage PIL Image, JPEG bytes for upload)
    """
    if not image_paths:
        raise ValueError("No images provided for bundle")

    # Load all images
    images = []
    for path in image_paths:
        img = Image.open(path)
        if img.mode == "RGBA":
            background = Image.new("RGBA", img.size, (255, 255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background.convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")
        images.append(img)

    num_images = len(images)

    # Determine optimal grid layout based on number of images
    # Try to keep it roughly square for better appearance
    if num_images == 1:
        cols, rows = 1, 1
    elif num_images == 2:
        cols, rows = 2, 1
    elif num_images == 3:
        cols, rows = 3, 1
    elif num_images == 4:
        cols, rows = 2, 2
    elif num_images == 5:
        cols, rows = 3, 2
    elif num_images == 6:
        cols, rows = 3, 2
    elif num_images <= 8:
        cols, rows = 4, 2
    elif num_images == 9:
        cols, rows = 3, 3
    elif num_images <= 12:
        cols, rows = 4, 3
    elif num_images <= 16:
        cols, rows = 4, 4
    elif num_images <= 20:
        cols, rows = 5, 4
    else:
        # For very large bundles, calculate optimal grid
        cols = min(5, int(num_images ** 0.5) + 1)
        rows = (num_images + cols - 1) // cols

    # Calculate available space for images
    available_width = max_width - (padding * 2) - (spacing * (cols - 1))
    available_height = max_height - (padding * 2) - (spacing * (rows - 1))

    # Calculate cell size - ensure positive values
    cell_width = max(50, available_width // cols)
    cell_height = max(50, available_height // rows)

    # For postcards, they're typically wider than tall, so adjust cell aspect ratio
    # Use a 3:2 aspect ratio for cells (postcard-like)
    target_aspect = 1.5
    if cell_width / cell_height > target_aspect:
        cell_width = int(cell_height * target_aspect)
    else:
        cell_height = int(cell_width / target_aspect)

    # Resize images to fit cells while maintaining aspect ratio
    resized_images = []
    for img in images:
        # Calculate scale to fit in cell
        scale = min(cell_width / img.width, cell_height / img.height)
        new_width = max(1, int(img.width * scale))
        new_height = max(1, int(img.height * scale))
        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        resized_images.append(resized)

    # Calculate actual canvas size needed
    canvas_width = (cols * cell_width) + ((cols - 1) * spacing) + (padding * 2)
    canvas_height = (rows * cell_height) + ((rows - 1) * spacing) + (padding * 2)

    # Ensure canvas doesn't exceed max dimensions
    if canvas_width > max_width or canvas_height > max_height:
        scale = min(max_width / canvas_width, max_height / canvas_height)
        canvas_width = int(canvas_width * scale)
        canvas_height = int(canvas_height * scale)
        cell_width = int(cell_width * scale)
        cell_height = int(cell_height * scale)
        spacing = int(spacing * scale)
        padding = int(padding * scale)

        # Re-resize images for new cell size
        resized_images = []
        for img in images:
            img_scale = min(cell_width / img.width, cell_height / img.height)
            new_width = max(1, int(img.width * img_scale))
            new_height = max(1, int(img.height * img_scale))
            resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            resized_images.append(resized)

    # Create wood background
    canvas = create_wood_background(canvas_width, canvas_height)

    # Place images on canvas
    for idx, img in enumerate(resized_images):
        row = idx // cols
        col = idx % cols

        # Calculate position (centered in cell)
        cell_x = padding + col * (cell_width + spacing)
        cell_y = padding + row * (cell_height + spacing)

        # Center image in cell
        offset_x = (cell_width - img.width) // 2
        offset_y = (cell_height - img.height) // 2

        paste_x = cell_x + offset_x
        paste_y = cell_y + offset_y

        # Add subtle shadow effect
        shadow = Image.new("RGBA", (img.width + 8, img.height + 8), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.rectangle([4, 4, img.width + 4, img.height + 4], fill=(0, 0, 0, 60))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=4))

        # Paste shadow then image
        canvas.paste(Image.new("RGB", (img.width + 8, img.height + 8), (0, 0, 0)),
                     (paste_x - 2, paste_y - 2),
                     shadow.split()[3])
        canvas.paste(img, (paste_x, paste_y))

    # Convert to JPEG bytes
    jpeg_buffer = io.BytesIO()
    canvas.save(jpeg_buffer, format="JPEG", quality=95)
    jpeg_bytes = jpeg_buffer.getvalue()

    return canvas, jpeg_bytes


def process_images_for_bundle(image_paths: list[Path]) -> list[tuple[Image.Image, bytes]]:
    """
    Process multiple images for a bundle listing.

    Returns the collage as the first image, followed by individual processed images.

    Args:
        image_paths: List of paths to postcard images

    Returns:
        List of (PIL Image, JPEG bytes) tuples - collage first, then individuals
    """
    results = []

    # Create collage as main image
    collage_img, collage_bytes = create_bundle_collage(image_paths)
    results.append((collage_img, collage_bytes))

    # Process individual images
    for path in image_paths:
        img, img_bytes = process_image(path, padding=100)
        results.append((img, img_bytes))

    return results
