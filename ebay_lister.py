"""eBay API integration for creating postcard listings."""

import uuid
import base64
import json
import requests
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from config import config
from token_manager import get_token_manager

LISTINGS_FILE = Path(__file__).parent / "listings_history.json"


@dataclass
class ListingResult:
    """Result of creating an eBay listing."""
    success: bool
    listing_id: str | None = None
    listing_url: str | None = None
    error: str | None = None
    title: str | None = None
    price: float | None = None
    quantity: int | None = None
    barcode: str | None = None
    image_name: str | None = None


def save_listing(result: ListingResult) -> None:
    """Save a successful listing to history file."""
    if not result.success:
        return

    history = []
    if LISTINGS_FILE.exists():
        try:
            with open(LISTINGS_FILE, "r") as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError):
            history = []

    entry = {
        "listing_id": result.listing_id,
        "listing_url": result.listing_url,
        "title": result.title,
        "price": result.price,
        "quantity": result.quantity,
        "barcode": result.barcode,
        "image_name": result.image_name,
        "created_at": datetime.now().isoformat()
    }

    history.append(entry)

    with open(LISTINGS_FILE, "w") as f:
        json.dump(history, f, indent=2)


class EbayLister:
    """Handles eBay API calls for creating listings."""

    POSTCARD_CATEGORY_ID = "262043"  # Collectibles > Postcards > Non-Topographical Postcards

    def __init__(self):
        self.base_url = config.ebay_api_url
        self.token_manager = get_token_manager(sandbox=config.EBAY_SANDBOX)
        self._refresh_headers()

    def _refresh_headers(self) -> None:
        """Refresh headers with current/renewed access token."""
        # Try to get token from token manager first (with auto-refresh)
        token = self.token_manager.get_access_token(
            app_id=config.EBAY_APP_ID,
            cert_id=config.EBAY_CERT_ID
        )

        # Fall back to config token if token manager doesn't have one
        if not token:
            token = config.EBAY_OAUTH_TOKEN

        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Content-Language": "en-US"
        }

    def _ensure_valid_token(self) -> None:
        """Ensure we have a valid token before making API calls."""
        if not self.token_manager.is_token_valid():
            print("  Refreshing expired token...")
            self._refresh_headers()

    def _generate_sku(self) -> str:
        """Generate a unique SKU for the inventory item."""
        return f"PC-{uuid.uuid4().hex[:12].upper()}"

    def create_inventory_item(
        self,
        sku: str,
        title: str,
        description: str,
        image_urls: list[str],
        quantity: int = 1,
        occasion: str = "",
        theme: str = "",
        subject: str = "",
        featured_person: str = "",
        character: str = ""
    ) -> bool:
        """
        Create or update an inventory item.

        Args:
            sku: Unique identifier for the item
            title: Item title
            description: HTML description
            image_urls: List of image URLs
            quantity: Available quantity for this item
            occasion: AI-detected occasion (Christmas, Birthday, etc.)
            theme: AI-detected theme (Animals, Landscape, etc.)
            subject: AI-detected subject (Beach, Mountains, etc.)
            featured_person: Famous person if depicted
            character: Fictional character if depicted

        Returns:
            True if successful
        """
        url = f"{self.base_url}/sell/inventory/v1/inventory_item/{sku}"

        from datetime import datetime
        current_year = str(datetime.now().year)

        # Build aspects dict with required fields
        aspects = {
            "Type": ["Postcard"],
            "Country of Origin": ["United States"],
            "Postage Condition": ["Unposted"],
            "Original/Licensed Reprint": ["Original"],
            "Year Manufactured": [current_year],
            "Size": ["Continental (6 x 4 in)"],
            "Era": ["Photochrome (1939-Now)"],
            "Unit of Sale": ["Single Unit"],
            "Personalize": ["No"],
            "Signed": ["No"],
            "Material": ["Cardboard"]
        }

        # Add AI-detected aspects if provided
        if occasion:
            aspects["Occasion"] = [occasion]
        if theme:
            aspects["Theme"] = [theme]
        if subject:
            aspects["Subject"] = [subject]
        if featured_person:
            aspects["Featured Person"] = [featured_person]
        if character:
            aspects["Character"] = [character]

        payload = {
            "availability": {
                "shipToLocationAvailability": {
                    "quantity": quantity
                }
            },
            "condition": "NEW",
            "product": {
                "title": title,
                "description": description,
                "imageUrls": image_urls,
                "aspects": aspects
            }
        }

        response = requests.put(url, headers=self.headers, json=payload)

        if response.status_code in (200, 201, 204):
            return True

        print(f"Inventory item error: {response.status_code} - {response.text}")
        return False

    def create_offer(
        self,
        sku: str,
        price: float,
        shipping_cost: float,
        quantity: int = 1
    ) -> str | None:
        """
        Create an offer for an inventory item.

        Args:
            sku: The inventory item SKU
            price: Listing price in USD
            shipping_cost: Shipping cost in USD
            quantity: Available quantity for this offer

        Returns:
            Offer ID if successful, None otherwise
        """
        url = f"{self.base_url}/sell/inventory/v1/offer"

        payload = {
            "sku": sku,
            "marketplaceId": "EBAY_US",
            "format": "FIXED_PRICE",
            "listingDescription": None,
            "availableQuantity": quantity,
            "categoryId": self.POSTCARD_CATEGORY_ID,
            "pricingSummary": {
                "price": {
                    "value": str(price),
                    "currency": "USD"
                }
            },
            "listingPolicies": {
                "fulfillmentPolicyId": self._get_or_create_fulfillment_policy(shipping_cost),
                "paymentPolicyId": self._get_or_create_payment_policy(),
                "returnPolicyId": self._get_or_create_return_policy()
            },
            "merchantLocationKey": self._get_or_create_location()
        }

        response = requests.post(url, headers=self.headers, json=payload)

        if response.status_code in (200, 201):
            data = response.json()
            return data.get("offerId")

        print(f"Create offer error: {response.status_code} - {response.text}")
        return None

    def publish_offer(self, offer_id: str) -> ListingResult:
        """
        Publish an offer to create a live listing.

        Args:
            offer_id: The offer to publish

        Returns:
            ListingResult with listing details or error
        """
        url = f"{self.base_url}/sell/inventory/v1/offer/{offer_id}/publish"

        response = requests.post(url, headers=self.headers)

        if response.status_code in (200, 201):
            data = response.json()
            listing_id = data.get("listingId")

            if config.EBAY_SANDBOX:
                listing_url = f"https://www.sandbox.ebay.com/itm/{listing_id}"
            else:
                listing_url = f"https://www.ebay.com/itm/{listing_id}"

            return ListingResult(
                success=True,
                listing_id=listing_id,
                listing_url=listing_url
            )

        return ListingResult(
            success=False,
            error=f"Publish error: {response.status_code} - {response.text}"
        )

    def upload_image(self, image_bytes: bytes) -> tuple[str | None, str | None]:
        """
        Upload an image to eBay's picture service using multipart form data.

        Args:
            image_bytes: JPEG image data

        Returns:
            Tuple of (Image URL, error message) - one will be None
        """
        from PIL import Image
        import io

        url = "https://api.ebay.com/ws/api.dll"

        if config.EBAY_SANDBOX:
            url = "https://api.sandbox.ebay.com/ws/api.dll"

        # Re-encode image to ensure valid JPEG format
        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=95)
            image_bytes = buffer.getvalue()
        except Exception as e:
            return None, f"Image re-encoding failed: {e}"

        filename = f"postcard_{uuid.uuid4().hex[:8]}.jpg"

        xml_request = f"""<?xml version="1.0" encoding="utf-8"?>
<UploadSiteHostedPicturesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <PictureName>{filename}</PictureName>
    <PictureSet>Supersize</PictureSet>
</UploadSiteHostedPicturesRequest>"""

        headers = {
            "X-EBAY-API-SITEID": "0",
            "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
            "X-EBAY-API-CALL-NAME": "UploadSiteHostedPictures",
            "X-EBAY-API-IAF-TOKEN": config.EBAY_OAUTH_TOKEN
        }

        # Use requests' built-in multipart handling
        files = {
            'XML Payload': ('request.xml', xml_request, 'text/xml'),
            'file': (filename, image_bytes, 'image/jpeg')
        }

        try:
            response = requests.post(url, headers=headers, files=files, timeout=60)
        except requests.exceptions.RequestException as e:
            return None, f"Network error: {e}"

        # Log the response for debugging
        with open("image_upload_debug.log", "w") as f:
            f.write(f"Status: {response.status_code}\n")
            f.write(f"Response:\n{response.text}\n")

        if response.status_code == 200:
            import re
            # Check for errors in XML response
            if "<Ack>Failure</Ack>" in response.text:
                error_match = re.search(r"<LongMessage>(.+?)</LongMessage>", response.text)
                error_msg = error_match.group(1) if error_match else "Unknown error"
                return None, error_msg

            match = re.search(r"<FullURL>(.+?)</FullURL>", response.text)
            if match:
                return match.group(1), None

        return None, f"HTTP {response.status_code}: {response.text[:200]}"

    def _get_or_create_fulfillment_policy(self, shipping_cost: float) -> str:
        """Get existing or create a fulfillment policy for shipping."""
        url = f"{self.base_url}/sell/account/v1/fulfillment_policy?marketplace_id=EBAY_US"
        response = requests.get(url, headers=self.headers)

        if response.status_code == 200:
            policies = response.json().get("fulfillmentPolicies", [])
            if policies:
                return policies[0]["fulfillmentPolicyId"]

        create_url = f"{self.base_url}/sell/account/v1/fulfillment_policy"
        payload = {
            "name": "Standard Postcard Shipping",
            "marketplaceId": "EBAY_US",
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            "handlingTime": {"value": 1, "unit": "DAY"},
            "shippingOptions": [{
                "optionType": "DOMESTIC",
                "costType": "FLAT_RATE",
                "shippingServices": [{
                    "sortOrder": 1,
                    "shippingCarrierCode": "USPS",
                    "shippingServiceCode": "USPSFirstClass",
                    "shippingCost": {"value": str(shipping_cost), "currency": "USD"},
                    "freeShipping": False
                }]
            }]
        }

        response = requests.post(create_url, headers=self.headers, json=payload)
        if response.status_code in (200, 201):
            return response.json()["fulfillmentPolicyId"]

        raise Exception(f"Failed to create fulfillment policy: {response.text}")

    def _get_or_create_payment_policy(self) -> str:
        """Get existing or create a payment policy."""
        url = f"{self.base_url}/sell/account/v1/payment_policy?marketplace_id=EBAY_US"
        response = requests.get(url, headers=self.headers)

        if response.status_code == 200:
            policies = response.json().get("paymentPolicies", [])
            if policies:
                return policies[0]["paymentPolicyId"]

        create_url = f"{self.base_url}/sell/account/v1/payment_policy"
        payload = {
            "name": "Standard Payment Policy",
            "marketplaceId": "EBAY_US",
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            "paymentMethods": [{"paymentMethodType": "PERSONAL_CHECK"}]
        }

        response = requests.post(create_url, headers=self.headers, json=payload)
        if response.status_code in (200, 201):
            return response.json()["paymentPolicyId"]

        raise Exception(f"Failed to create payment policy: {response.text}")

    def _get_or_create_return_policy(self) -> str:
        """Get existing or create a return policy."""
        url = f"{self.base_url}/sell/account/v1/return_policy?marketplace_id=EBAY_US"
        response = requests.get(url, headers=self.headers)

        if response.status_code == 200:
            policies = response.json().get("returnPolicies", [])
            if policies:
                return policies[0]["returnPolicyId"]

        create_url = f"{self.base_url}/sell/account/v1/return_policy"
        payload = {
            "name": "30 Day Returns",
            "marketplaceId": "EBAY_US",
            "categoryTypes": [{"name": "ALL_EXCLUDING_MOTORS_VEHICLES"}],
            "returnsAccepted": True,
            "returnPeriod": {"value": 30, "unit": "DAY"},
            "refundMethod": "MONEY_BACK",
            "returnShippingCostPayer": "BUYER"
        }

        response = requests.post(create_url, headers=self.headers, json=payload)
        if response.status_code in (200, 201):
            return response.json()["returnPolicyId"]

        raise Exception(f"Failed to create return policy: {response.text}")

    def _get_or_create_location(self) -> str:
        """Get existing or create a merchant location."""
        url = f"{self.base_url}/sell/inventory/v1/location"
        response = requests.get(url, headers=self.headers)

        if response.status_code == 200:
            locations = response.json().get("locations", [])
            if locations:
                return locations[0]["merchantLocationKey"]

        location_key = "DEFAULT_LOCATION"
        create_url = f"{self.base_url}/sell/inventory/v1/location/{location_key}"
        payload = {
            "location": {
                "address": {
                    "city": "New York",
                    "stateOrProvince": "NY",
                    "postalCode": "10001",
                    "country": "US"
                }
            },
            "locationTypes": ["WAREHOUSE"],
            "merchantLocationStatus": "ENABLED",
            "name": "Default Location"
        }

        response = requests.post(create_url, headers=self.headers, json=payload)
        if response.status_code in (200, 201, 204):
            return location_key

        raise Exception(f"Failed to create location: {response.text}")

    def create_listing(
        self,
        title: str,
        description: str,
        image_bytes: bytes,
        price: float,
        shipping_cost: float | None = None,
        quantity: int = 1,
        occasion: str = "",
        theme: str = "",
        subject: str = "",
        featured_person: str = "",
        character: str = ""
    ) -> ListingResult:
        """
        Create a complete eBay listing.

        Args:
            title: Listing title
            description: HTML description
            image_bytes: JPEG image data
            price: Listing price in USD
            shipping_cost: Shipping cost (uses default if None)
            quantity: Number of items available (default 1)
            occasion: AI-detected occasion
            theme: AI-detected theme
            subject: AI-detected subject
            featured_person: Famous person if depicted
            character: Fictional character if depicted

        Note: Automatically refreshes OAuth token if expired.

        Returns:
            ListingResult with listing details or error
        """
        # Ensure token is valid before starting
        self._ensure_valid_token()

        if shipping_cost is None:
            shipping_cost = config.SHIPPING_COST

        print("  Uploading image...")
        image_url, upload_error = self.upload_image(image_bytes)
        if not image_url:
            return ListingResult(success=False, error=f"Failed to upload image: {upload_error}")

        sku = self._generate_sku()
        print(f"  Creating inventory item (SKU: {sku})...")

        if not self.create_inventory_item(
            sku, title, description, [image_url], quantity,
            occasion=occasion, theme=theme, subject=subject,
            featured_person=featured_person, character=character
        ):
            return ListingResult(success=False, error="Failed to create inventory item")

        print("  Creating offer...")
        offer_id = self.create_offer(sku, price, shipping_cost, quantity)
        if not offer_id:
            return ListingResult(success=False, error="Failed to create offer")

        print("  Publishing listing...")
        result = self.publish_offer(offer_id)

        # Add title, price, and quantity to result for saving
        result.title = title
        result.price = price
        result.quantity = quantity

        return result

    def create_bundle_listing(
        self,
        title: str,
        description: str,
        image_bytes_list: list[bytes],
        price: float,
        shipping_cost: float | None = None,
        quantity: int = 1
    ) -> ListingResult:
        """
        Create a bundle eBay listing with multiple images.

        Args:
            title: Listing title
            description: HTML description
            image_bytes_list: List of JPEG image data (first is main/collage image)
            price: Listing price in USD
            shipping_cost: Shipping cost (uses default if None)
            quantity: Number of bundles available (default 1)

        Returns:
            ListingResult with listing details or error
        """
        # Ensure token is valid before starting
        self._ensure_valid_token()

        if shipping_cost is None:
            shipping_cost = config.SHIPPING_COST

        if not image_bytes_list:
            return ListingResult(success=False, error="No images provided for bundle")

        # Upload all images
        image_urls = []
        for i, image_bytes in enumerate(image_bytes_list):
            print(f"  Uploading image {i + 1}/{len(image_bytes_list)}...")
            image_url, upload_error = self.upload_image(image_bytes)
            if not image_url:
                return ListingResult(success=False, error=f"Failed to upload image {i + 1}: {upload_error}")
            image_urls.append(image_url)

        sku = self._generate_sku()
        print(f"  Creating inventory item (SKU: {sku})...")

        if not self.create_inventory_item(sku, title, description, image_urls, quantity):
            return ListingResult(success=False, error="Failed to create inventory item")

        print("  Creating offer...")
        offer_id = self.create_offer(sku, price, shipping_cost, quantity)
        if not offer_id:
            return ListingResult(success=False, error="Failed to create offer")

        print("  Publishing listing...")
        result = self.publish_offer(offer_id)

        # Add title, price, and quantity to result for saving
        result.title = title
        result.price = price
        result.quantity = quantity

        return result
