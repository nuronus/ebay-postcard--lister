"""
eBay Postcard Auto-Lister

Automatically create eBay listings from postcard photos with AI-generated
SEO-optimized titles and descriptions.

Usage:
    python main.py --input ./images
    python main.py --input ./images --price 14.99
    python main.py --input ./images --dry-run
"""

import argparse
import sys
from pathlib import Path

from config import config
from image_processor import process_image, get_image_files
from ai_analyzer import analyze_image
from ebay_lister import EbayLister


def print_header():
    """Print application header."""
    print("=" * 60)
    print("  eBay Postcard Auto-Lister")
    print("=" * 60)
    print()


def validate_config() -> bool:
    """Validate required configuration is present."""
    missing = config.validate()

    if missing:
        print("ERROR: Missing required configuration:")
        for item in missing:
            print(f"  - {item}")
        print()
        print("Please copy .env.example to .env and fill in your credentials.")
        return False

    return True


def confirm_listing(title: str, description: str, price: float, quantity: int) -> tuple[bool, float]:
    """
    Display listing details and confirm with user.

    Returns:
        Tuple of (should_list, final_price)
    """
    print()
    print("-" * 50)
    print(f"TITLE: {title}")
    print()
    print("DESCRIPTION:")
    clean_desc = description.replace("<p>", "\n").replace("</p>", "")
    clean_desc = clean_desc.replace("<br>", "\n").replace("<b>", "").replace("</b>", "")
    print(clean_desc[:500] + "..." if len(clean_desc) > 500 else clean_desc)
    print()
    print(f"PRICE: ${price:.2f}")
    print(f"QUANTITY: {quantity}")
    print("-" * 50)

    while True:
        response = input(f"List at ${price:.2f} (qty: {quantity})? [Y/n/price]: ").strip().lower()

        if response in ("", "y", "yes"):
            return True, price
        elif response in ("n", "no", "skip"):
            return False, price
        else:
            try:
                new_price = float(response.replace("$", ""))
                return True, new_price
            except ValueError:
                print("Enter 'y', 'n', or a price (e.g., 12.99)")


def process_single_image(
    image_path: Path,
    lister: EbayLister,
    default_price: float,
    quantity: int = 1,
    dry_run: bool = False
) -> bool:
    """
    Process a single image and create listing.

    Returns:
        True if listing was created successfully
    """
    print(f"\nProcessing: {image_path.name}")

    print("  Preparing image...")
    processed_image, image_bytes = process_image(image_path)

    print("  Analyzing with AI...")
    try:
        content = analyze_image(image_bytes)
    except Exception as e:
        print(f"  ERROR: AI analysis failed - {e}")
        return False

    should_list, price = confirm_listing(content.title, content.description, default_price, quantity)

    if not should_list:
        print("  Skipped.")
        return False

    if dry_run:
        print("  [DRY RUN] Would create listing")
        return True

    print("  Creating eBay listing...")
    result = lister.create_listing(
        title=content.title,
        description=content.description,
        image_bytes=image_bytes,
        price=price,
        quantity=quantity
    )

    if result.success:
        print(f"  SUCCESS! Listing ID: {result.listing_id}")
        print(f"  URL: {result.listing_url}")
        return True
    else:
        print(f"  FAILED: {result.error}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Automatically create eBay postcard listings with AI"
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        default=Path("./images"),
        help="Directory containing postcard images (default: ./images)"
    )
    parser.add_argument(
        "--price", "-p",
        type=float,
        default=None,
        help=f"Default listing price (default: ${config.DEFAULT_PRICE:.2f})"
    )
    parser.add_argument(
        "--quantity", "-q",
        type=int,
        default=1,
        help="Quantity of each postcard available (default: 1)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze images but don't create actual listings"
    )

    args = parser.parse_args()

    print_header()

    if not validate_config():
        sys.exit(1)

    input_dir = args.input.resolve()
    if not input_dir.exists():
        print(f"ERROR: Input directory not found: {input_dir}")
        sys.exit(1)

    images = get_image_files(input_dir)
    if not images:
        print(f"No image files found in: {input_dir}")
        sys.exit(0)

    print(f"Found {len(images)} image(s) in {input_dir}")
    print(f"Environment: {'SANDBOX' if config.EBAY_SANDBOX else 'PRODUCTION'}")

    if args.dry_run:
        print("Mode: DRY RUN (no listings will be created)")

    default_price = args.price if args.price else config.DEFAULT_PRICE
    quantity = args.quantity
    print(f"Default price: ${default_price:.2f}")
    print(f"Default quantity: {quantity}")

    lister = EbayLister()
    success_count = 0
    skip_count = 0
    error_count = 0

    for image_path in images:
        try:
            if process_single_image(image_path, lister, default_price, quantity, args.dry_run):
                success_count += 1
            else:
                skip_count += 1
        except KeyboardInterrupt:
            print("\n\nInterrupted by user.")
            break
        except Exception as e:
            print(f"  ERROR: {e}")
            error_count += 1

    print()
    print("=" * 60)
    print("SUMMARY")
    print(f"  Listed:  {success_count}")
    print(f"  Skipped: {skip_count}")
    print(f"  Errors:  {error_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
