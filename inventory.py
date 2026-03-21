"""
Inventory management for postcard listings.

Tracks postcards by barcode, manages stock levels, and links to eBay listings.
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


INVENTORY_FILE = Path(__file__).parent / "inventory.json"


@dataclass
class InventoryItem:
    """A postcard inventory item."""
    barcode: str
    title: Optional[str] = None
    description: Optional[str] = None
    image_path: Optional[str] = None
    quantity: int = 1
    price: Optional[float] = None
    listing_id: Optional[str] = None
    listing_url: Optional[str] = None
    status: str = "available"  # available, listed, sold
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    listed_at: Optional[str] = None
    sold_at: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "InventoryItem":
        """Create from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class Inventory:
    """Manages the postcard inventory."""

    def __init__(self, inventory_file: Path = INVENTORY_FILE):
        self.inventory_file = inventory_file
        self._items: dict[str, InventoryItem] = {}
        self._load()

    def _load(self) -> None:
        """Load inventory from file."""
        if self.inventory_file.exists():
            try:
                with open(self.inventory_file, "r") as f:
                    data = json.load(f)
                    for barcode, item_data in data.get("items", {}).items():
                        self._items[barcode] = InventoryItem.from_dict(item_data)
            except (json.JSONDecodeError, IOError):
                self._items = {}

    def _save(self) -> None:
        """Save inventory to file."""
        data = {
            "items": {barcode: item.to_dict() for barcode, item in self._items.items()},
            "updated_at": datetime.now().isoformat()
        }
        with open(self.inventory_file, "w") as f:
            json.dump(data, f, indent=2)

    def add_item(
        self,
        barcode: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        image_path: Optional[str] = None,
        quantity: int = 1,
        price: Optional[float] = None
    ) -> InventoryItem:
        """
        Add a new item to inventory.

        Args:
            barcode: The barcode identifier
            title: Item title
            description: Item description
            image_path: Path to the postcard image
            quantity: Number of items
            price: Price per item

        Returns:
            The created InventoryItem
        """
        if barcode in self._items:
            raise ValueError(f"Barcode {barcode} already exists in inventory")

        item = InventoryItem(
            barcode=barcode,
            title=title,
            description=description,
            image_path=image_path,
            quantity=quantity,
            price=price,
            status="available",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat()
        )

        self._items[barcode] = item
        self._save()
        return item

    def get_item(self, barcode: str) -> Optional[InventoryItem]:
        """Get an item by barcode."""
        return self._items.get(barcode)

    def update_item(self, barcode: str, **kwargs) -> Optional[InventoryItem]:
        """
        Update an existing inventory item.

        Args:
            barcode: The barcode to update
            **kwargs: Fields to update

        Returns:
            Updated InventoryItem or None if not found
        """
        if barcode not in self._items:
            return None

        item = self._items[barcode]
        for key, value in kwargs.items():
            if hasattr(item, key):
                setattr(item, key, value)

        item.updated_at = datetime.now().isoformat()
        self._save()
        return item

    def mark_listed(
        self,
        barcode: str,
        listing_id: str,
        listing_url: str
    ) -> Optional[InventoryItem]:
        """Mark an item as listed on eBay."""
        return self.update_item(
            barcode,
            status="listed",
            listing_id=listing_id,
            listing_url=listing_url,
            listed_at=datetime.now().isoformat()
        )

    def mark_sold(self, barcode: str, quantity_sold: int = 1) -> Optional[InventoryItem]:
        """Mark items as sold, reducing quantity."""
        item = self._items.get(barcode)
        if not item:
            return None

        new_quantity = max(0, item.quantity - quantity_sold)
        status = "sold" if new_quantity == 0 else item.status

        return self.update_item(
            barcode,
            quantity=new_quantity,
            status=status,
            sold_at=datetime.now().isoformat() if new_quantity == 0 else item.sold_at
        )

    def delete_item(self, barcode: str) -> bool:
        """Delete an item from inventory."""
        if barcode in self._items:
            del self._items[barcode]
            self._save()
            return True
        return False

    def get_all_items(self) -> list[InventoryItem]:
        """Get all inventory items."""
        return list(self._items.values())

    def get_available_items(self) -> list[InventoryItem]:
        """Get all available (not sold) items."""
        return [item for item in self._items.values() if item.status == "available"]

    def get_listed_items(self) -> list[InventoryItem]:
        """Get all listed items."""
        return [item for item in self._items.values() if item.status == "listed"]

    def search_by_title(self, query: str) -> list[InventoryItem]:
        """Search items by title."""
        query = query.lower()
        return [
            item for item in self._items.values()
            if item.title and query in item.title.lower()
        ]

    def barcode_exists(self, barcode: str) -> bool:
        """Check if a barcode exists in inventory."""
        return barcode in self._items

    def get_stats(self) -> dict:
        """Get inventory statistics."""
        items = list(self._items.values())
        return {
            "total_items": len(items),
            "total_quantity": sum(item.quantity for item in items),
            "available": len([i for i in items if i.status == "available"]),
            "listed": len([i for i in items if i.status == "listed"]),
            "sold": len([i for i in items if i.status == "sold"]),
        }


# Global inventory instance
_inventory: Optional[Inventory] = None


def get_inventory() -> Inventory:
    """Get the global inventory instance."""
    global _inventory
    if _inventory is None:
        _inventory = Inventory()
    return _inventory
