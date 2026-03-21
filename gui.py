"""
eBay Postcard Auto-Lister GUI

A graphical interface for creating eBay postcard listings with AI-generated content.
"""

import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path
from PIL import Image, ImageTk
import os

from config import config
from image_processor import process_image, get_image_files, create_bundle_collage, process_images_for_bundle
from ai_analyzer import analyze_image
from ebay_lister import EbayLister, save_listing, LISTINGS_FILE
from token_manager import get_token_manager
from inventory import get_inventory, InventoryItem
from barcode_printer import (
    generate_label_sheet_pdf,
    generate_multiple_sheets,
    get_next_barcode_number,
    peek_barcode_range,
    LABELS_PER_SHEET
)


class ConfigManager:
    """Manages configuration persistence."""

    CONFIG_FILE = Path(__file__).parent / "config.json"

    @classmethod
    def load(cls) -> dict:
        """Load configuration from file."""
        if cls.CONFIG_FILE.exists():
            with open(cls.CONFIG_FILE, "r") as f:
                return json.load(f)
        return {}

    @classmethod
    def save(cls, data: dict) -> None:
        """Save configuration to file."""
        with open(cls.CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)


class SettingsFrame(ttk.Frame):
    """Configuration settings panel."""

    EBAY_FIELDS = ["EBAY_APP_ID", "EBAY_CERT_ID", "EBAY_DEV_ID", "EBAY_RU_NAME", "EBAY_OAUTH_TOKEN", "EBAY_REFRESH_TOKEN"]

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.entries = {}
        self.config_data = {}
        self._create_widgets()
        self._load_settings()

    def _create_widgets(self):
        """Create settings form."""
        # Main container with padding
        container = ttk.Frame(self, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        # Title
        title = ttk.Label(container, text="Configuration Settings", font=("Segoe UI", 14, "bold"))
        title.pack(anchor=tk.W, pady=(0, 20))

        # OpenAI Section
        self._create_section(container, "OpenAI API", [
            ("OPENAI_API_KEY", "API Key:", True)
        ])

        # Environment toggle - BEFORE eBay credentials so it loads first
        env_frame = ttk.LabelFrame(container, text="Environment", padding=10)
        env_frame.pack(fill=tk.X, pady=10)

        self.sandbox_var = tk.BooleanVar(value=True)
        ttk.Radiobutton(env_frame, text="Sandbox (Testing)", variable=self.sandbox_var, value=True,
                        command=self._on_environment_change).pack(anchor=tk.W)
        ttk.Radiobutton(env_frame, text="Production (Live)", variable=self.sandbox_var, value=False,
                        command=self._on_environment_change).pack(anchor=tk.W)

        self.env_label = ttk.Label(env_frame, text="", foreground="blue")
        self.env_label.pack(anchor=tk.W, pady=(5, 0))

        # eBay Section
        self._create_section(container, "eBay API Credentials (per environment)", [
            ("EBAY_APP_ID", "App ID:", False),
            ("EBAY_CERT_ID", "Cert ID:", True),
            ("EBAY_DEV_ID", "Dev ID:", False),
            ("EBAY_RU_NAME", "RuName:", False),
            ("EBAY_OAUTH_TOKEN", "OAuth Token:", True),
            ("EBAY_REFRESH_TOKEN", "Refresh Token:", True)
        ])

        # Token status section
        token_frame = ttk.LabelFrame(container, text="eBay Authorization", padding=10)
        token_frame.pack(fill=tk.X, pady=10)

        # Sign in button - prominent
        signin_row = ttk.Frame(token_frame)
        signin_row.pack(fill=tk.X, pady=5)
        self.signin_btn = ttk.Button(signin_row, text="Sign In with eBay", command=self._sign_in_with_ebay)
        self.signin_btn.pack(side=tk.LEFT, padx=2)
        ttk.Label(signin_row, text="(Opens browser to authorize)", foreground="gray").pack(side=tk.LEFT, padx=5)

        ttk.Separator(token_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        self.token_status_label = ttk.Label(token_frame, text="Not signed in", foreground="gray")
        self.token_status_label.pack(anchor=tk.W)

        token_btn_row = ttk.Frame(token_frame)
        token_btn_row.pack(fill=tk.X, pady=5)
        ttk.Button(token_btn_row, text="Check Token", command=self._check_token_status).pack(side=tk.LEFT, padx=2)
        ttk.Button(token_btn_row, text="Refresh Token Now", command=self._refresh_token_now).pack(side=tk.LEFT, padx=2)

        # Listing Defaults Section
        self._create_section(container, "Listing Defaults", [
            ("DEFAULT_PRICE", "Default Price ($):", False),
            ("SHIPPING_COST", "Shipping Cost ($):", False)
        ])

        # Buttons
        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill=tk.X, pady=20)

        ttk.Button(btn_frame, text="Save Settings", command=self._save_settings).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Test Connection", command=self._test_connection).pack(side=tk.LEFT, padx=5)

        # Status
        self.status_label = ttk.Label(container, text="", foreground="gray")
        self.status_label.pack(anchor=tk.W)

    def _create_section(self, parent, title: str, fields: list):
        """Create a labeled section with fields."""
        frame = ttk.LabelFrame(parent, text=title, padding=10)
        frame.pack(fill=tk.X, pady=10)

        for key, label, is_password in fields:
            row = ttk.Frame(frame)
            row.pack(fill=tk.X, pady=3)

            ttk.Label(row, text=label, width=15).pack(side=tk.LEFT)

            entry = ttk.Entry(row, width=50, show="*" if is_password else "")
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
            self.entries[key] = entry

            if is_password:
                show_btn = ttk.Button(row, text="Show", width=6)
                show_btn.pack(side=tk.LEFT)
                show_btn.configure(command=lambda e=entry, b=show_btn: self._toggle_password(e, b))

    def _toggle_password(self, entry, button):
        """Toggle password visibility."""
        if entry.cget("show") == "*":
            entry.configure(show="")
            button.configure(text="Hide")
        else:
            entry.configure(show="*")
            button.configure(text="Show")

    def _get_env_key(self) -> str:
        """Get current environment key."""
        return "sandbox" if self.sandbox_var.get() else "production"

    def _on_environment_change(self):
        """Handle environment toggle - save current and load new."""
        # Save current entries to config_data before switching
        if self.config_data:
            self._save_ebay_fields_to_data()

        # Load the new environment's credentials
        self._load_ebay_fields_from_data()

        env_name = "Sandbox" if self.sandbox_var.get() else "Production"
        self.env_label.configure(text=f"Editing {env_name} credentials")

    def _save_ebay_fields_to_data(self):
        """Save current eBay field values to config_data."""
        # Determine which environment we're saving FROM (opposite of current)
        env_key = "production" if self.sandbox_var.get() else "sandbox"

        if env_key not in self.config_data:
            self.config_data[env_key] = {}

        for field in self.EBAY_FIELDS:
            if field in self.entries:
                self.config_data[env_key][field] = self.entries[field].get().strip()

    def _load_ebay_fields_from_data(self):
        """Load eBay fields from config_data for current environment."""
        env_key = self._get_env_key()
        env_data = self.config_data.get(env_key, {})

        for field in self.EBAY_FIELDS:
            if field in self.entries:
                self.entries[field].delete(0, tk.END)
                self.entries[field].insert(0, env_data.get(field, ""))

    def _load_settings(self):
        """Load settings from config file."""
        self.config_data = ConfigManager.load()

        # Load non-eBay fields
        for key, entry in self.entries.items():
            if key not in self.EBAY_FIELDS:
                value = self.config_data.get(key, os.getenv(key, ""))
                entry.delete(0, tk.END)
                entry.insert(0, value)

        # Set environment
        self.sandbox_var.set(self.config_data.get("EBAY_SANDBOX", True))

        # Load eBay fields for current environment
        self._load_ebay_fields_from_data()

        env_name = "Sandbox" if self.sandbox_var.get() else "Production"
        self.env_label.configure(text=f"Editing {env_name} credentials")

    def _save_settings(self):
        """Save settings to config file and update environment."""
        # Save current eBay fields to current environment
        env_key = self._get_env_key()
        if env_key not in self.config_data:
            self.config_data[env_key] = {}

        for field in self.EBAY_FIELDS:
            if field in self.entries:
                self.config_data[env_key][field] = self.entries[field].get().strip()

        # Save non-eBay fields
        for key, entry in self.entries.items():
            if key not in self.EBAY_FIELDS:
                value = entry.get().strip()
                self.config_data[key] = value
                os.environ[key] = value

        self.config_data["EBAY_SANDBOX"] = self.sandbox_var.get()
        os.environ["EBAY_SANDBOX"] = str(self.sandbox_var.get()).lower()

        # Ensure both environments exist
        if "sandbox" not in self.config_data:
            self.config_data["sandbox"] = {}
        if "production" not in self.config_data:
            self.config_data["production"] = {}

        ConfigManager.save(self.config_data)

        # Reload config with current environment's credentials
        env_data = self.config_data.get(env_key, {})
        config.OPENAI_API_KEY = self.config_data.get("OPENAI_API_KEY", "")
        config.EBAY_APP_ID = env_data.get("EBAY_APP_ID", "")
        config.EBAY_CERT_ID = env_data.get("EBAY_CERT_ID", "")
        config.EBAY_DEV_ID = env_data.get("EBAY_DEV_ID", "")
        config.EBAY_OAUTH_TOKEN = env_data.get("EBAY_OAUTH_TOKEN", "")
        config.EBAY_SANDBOX = self.config_data.get("EBAY_SANDBOX", True)
        config.DEFAULT_PRICE = float(self.config_data.get("DEFAULT_PRICE", "9.99") or "9.99")
        config.SHIPPING_COST = float(self.config_data.get("SHIPPING_COST", "3.99") or "3.99")

        self.status_label.configure(text="Settings saved!", foreground="green")
        self.after(3000, lambda: self.status_label.configure(text=""))

    def _test_connection(self):
        """Test API connections."""
        self._save_settings()
        missing = config.validate()

        if missing:
            messagebox.showerror("Configuration Error", f"Missing: {', '.join(missing)}")
            return

        self.status_label.configure(text="Testing connections...", foreground="blue")
        self.update()

        # Test in background
        def test():
            errors = []
            details = []

            # Test OpenAI
            try:
                from openai import OpenAI
                client = OpenAI(api_key=config.OPENAI_API_KEY)
                client.models.list()
                details.append("OpenAI: OK")
            except Exception as e:
                errors.append(f"OpenAI: {str(e)[:100]}")

            # Test eBay
            try:
                import requests
                url = f"{config.ebay_api_url}/sell/inventory/v1/inventory_item?limit=1"
                headers = {
                    "Authorization": f"Bearer {config.EBAY_OAUTH_TOKEN}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
                details.append(f"eBay URL: {url}")
                details.append(f"Token (first 50 chars): {config.EBAY_OAUTH_TOKEN[:50]}...")

                resp = requests.get(url, headers=headers)
                details.append(f"eBay Status: {resp.status_code}")
                details.append(f"eBay Response: {resp.text[:500]}")

                if resp.status_code == 401:
                    errors.append(f"eBay: Invalid/Expired OAuth token\nResponse: {resp.text[:200]}")
                elif resp.status_code == 403:
                    errors.append(f"eBay: Access Forbidden (403)\nResponse: {resp.text[:300]}")
                elif resp.status_code >= 400:
                    errors.append(f"eBay: HTTP {resp.status_code}\nResponse: {resp.text[:200]}")
                else:
                    details.append("eBay: OK")
            except Exception as e:
                errors.append(f"eBay: {str(e)[:100]}")

            self.after(0, lambda: self._show_test_result(errors, details))

        threading.Thread(target=test, daemon=True).start()

    def _show_test_result(self, errors, details=None):
        """Show test results."""
        # Log details to console and file
        if details:
            log_text = "\n".join(details)
            print("=== Connection Test Details ===")
            print(log_text)
            print("=" * 30)

            # Also save to log file
            try:
                with open("ebay_debug.log", "w") as f:
                    f.write("=== Connection Test Details ===\n")
                    f.write(log_text)
                    f.write("\n\n=== Errors ===\n")
                    f.write("\n".join(errors) if errors else "None")
            except:
                pass

        if errors:
            self.status_label.configure(text="Connection failed! See ebay_debug.log", foreground="red")
            error_msg = "\n\n".join(errors)
            if details:
                error_msg += "\n\n--- Debug Info ---\n" + "\n".join(details[-3:])
            messagebox.showerror("Connection Test Failed", error_msg)
        else:
            self.status_label.configure(text="All connections successful!", foreground="green")
            messagebox.showinfo("Success", "All API connections are working!")

    def _check_token_status(self):
        """Check and display current token status."""
        token_mgr = get_token_manager(sandbox=self.sandbox_var.get())
        status = token_mgr.get_token_status()

        status_text = status.get("message", "Unknown")
        if status.get("has_refresh"):
            status_text += " (refresh token available)"

        color = "green" if status.get("status") == "valid" else "orange" if status.get("status") == "expired" else "gray"
        self.token_status_label.configure(text=status_text, foreground=color)

    def _refresh_token_now(self):
        """Manually refresh the access token."""
        self._save_settings()  # Ensure credentials are saved first

        token_mgr = get_token_manager(sandbox=self.sandbox_var.get())

        # Get credentials from current entries
        env_key = self._get_env_key()
        app_id = self.entries.get("EBAY_APP_ID", tk.Entry()).get().strip()
        cert_id = self.entries.get("EBAY_CERT_ID", tk.Entry()).get().strip()

        if not app_id or not cert_id:
            messagebox.showerror("Missing Credentials", "App ID and Cert ID are required for token refresh.")
            return

        self.token_status_label.configure(text="Refreshing token...", foreground="blue")
        self.update()

        def refresh():
            new_token = token_mgr.refresh_access_token(app_id=app_id, cert_id=cert_id)
            if new_token:
                self.after(0, lambda: self._on_token_refreshed(True))
            else:
                self.after(0, lambda: self._on_token_refreshed(False))

        threading.Thread(target=refresh, daemon=True).start()

    def _on_token_refreshed(self, success: bool):
        """Handle token refresh result."""
        if success:
            self.token_status_label.configure(text="Token refreshed successfully!", foreground="green")
            # Update the OAuth token entry with the new token
            token_mgr = get_token_manager(sandbox=self.sandbox_var.get())
            tokens = token_mgr.get_env_tokens()
            if tokens.get("access_token"):
                self.entries["EBAY_OAUTH_TOKEN"].delete(0, tk.END)
                self.entries["EBAY_OAUTH_TOKEN"].insert(0, tokens["access_token"])
            self._check_token_status()
        else:
            self.token_status_label.configure(text="Token refresh failed!", foreground="red")
            messagebox.showerror("Refresh Failed", "Could not refresh token. Check your refresh token and credentials.")

    def _sign_in_with_ebay(self):
        """Start the OAuth flow to sign in with eBay."""
        self._save_settings()  # Ensure credentials are saved first

        app_id = self.entries.get("EBAY_APP_ID", tk.Entry()).get().strip()
        cert_id = self.entries.get("EBAY_CERT_ID", tk.Entry()).get().strip()
        ru_name = self.entries.get("EBAY_RU_NAME", tk.Entry()).get().strip()

        if not app_id or not cert_id:
            messagebox.showerror("Missing Credentials",
                "Please enter your eBay App ID and Cert ID first.\n\n"
                "Get these from the eBay Developer Portal:\n"
                "https://developer.ebay.com/my/keys")
            return

        if not ru_name:
            messagebox.showerror("Missing RuName",
                "Please enter your RuName (Redirect URL name).\n\n"
                "Create one in the eBay Developer Portal under your application settings.\n"
                "Set the callback URL to: http://localhost:8888/oauth/callback")
            return

        self.signin_btn.configure(state="disabled")
        self.token_status_label.configure(text="Opening browser for authorization...", foreground="blue")
        self.update()

        def do_oauth():
            token_mgr = get_token_manager(sandbox=self.sandbox_var.get())

            def on_complete(success, message):
                self.after(0, lambda: self._on_oauth_complete(success, message))

            token_mgr.start_oauth_flow(
                app_id=app_id,
                cert_id=cert_id,
                ru_name=ru_name,
                callback=on_complete
            )

        threading.Thread(target=do_oauth, daemon=True).start()

    def _on_oauth_complete(self, success: bool, message: str):
        """Handle OAuth flow completion."""
        self.signin_btn.configure(state="normal")

        if success:
            self.token_status_label.configure(text="Signed in successfully!", foreground="green")

            # Update the token entries with the new tokens
            token_mgr = get_token_manager(sandbox=self.sandbox_var.get())
            tokens = token_mgr.get_env_tokens()

            if tokens.get("access_token"):
                self.entries["EBAY_OAUTH_TOKEN"].delete(0, tk.END)
                self.entries["EBAY_OAUTH_TOKEN"].insert(0, tokens["access_token"])
            if tokens.get("refresh_token"):
                self.entries["EBAY_REFRESH_TOKEN"].delete(0, tk.END)
                self.entries["EBAY_REFRESH_TOKEN"].insert(0, tokens["refresh_token"])

            self._save_settings()
            self._check_token_status()

            messagebox.showinfo("Success", "Successfully signed in with eBay!\n\nTokens will auto-refresh before they expire.")
        else:
            self.token_status_label.configure(text=f"Sign in failed: {message}", foreground="red")
            messagebox.showerror("Sign In Failed", message)


class ListingFrame(ttk.Frame):
    """Main listing interface."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.images = []
        self.current_index = -1
        self.current_image_bytes = None
        self.current_content = None
        self._create_widgets()

    def _create_widgets(self):
        """Create main listing interface."""
        # Top toolbar
        toolbar = ttk.Frame(self, padding=5)
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="Select Folder", command=self._select_folder).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Select Files", command=self._select_files).pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=10)

        self.folder_label = ttk.Label(toolbar, text="No images loaded", foreground="gray")
        self.folder_label.pack(side=tk.LEFT, padx=5)

        # Main content area - horizontal panes
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left panel - Image list
        left_frame = ttk.Frame(paned, width=200)
        paned.add(left_frame, weight=1)

        ttk.Label(left_frame, text="Images", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, padx=5, pady=5)

        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.image_listbox = tk.Listbox(list_frame, selectmode=tk.SINGLE, font=("Segoe UI", 9))
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.image_listbox.yview)
        self.image_listbox.configure(yscrollcommand=scrollbar.set)

        self.image_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.image_listbox.bind("<<ListboxSelect>>", self._on_image_select)

        # Center panel - Image preview and content
        center_frame = ttk.Frame(paned)
        paned.add(center_frame, weight=3)

        # Image preview
        preview_frame = ttk.LabelFrame(center_frame, text="Preview", padding=5)
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        self.preview_label = ttk.Label(preview_frame, text="Select an image", anchor=tk.CENTER)
        self.preview_label.pack(fill=tk.BOTH, expand=True)

        # Generated content
        content_frame = ttk.LabelFrame(center_frame, text="Generated Listing Content", padding=5)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        title_row = ttk.Frame(content_frame)
        title_row.pack(fill=tk.X, pady=2)
        ttk.Label(title_row, text="Title:", width=12).pack(side=tk.LEFT)
        self.title_entry = ttk.Entry(title_row, font=("Segoe UI", 10))
        self.title_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.title_count = ttk.Label(title_row, text="0/80", width=6)
        self.title_count.pack(side=tk.LEFT)
        self.title_entry.bind("<KeyRelease>", self._update_title_count)

        # Description
        ttk.Label(content_frame, text="Description:").pack(anchor=tk.W, pady=(5, 2))
        self.description_text = scrolledtext.ScrolledText(content_frame, height=8, font=("Segoe UI", 9))
        self.description_text.pack(fill=tk.BOTH, expand=True)

        # Right panel - Actions
        right_frame = ttk.Frame(paned, width=200)
        paned.add(right_frame, weight=1)

        ttk.Label(right_frame, text="Actions", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, padx=5, pady=5)

        action_frame = ttk.Frame(right_frame, padding=5)
        action_frame.pack(fill=tk.X)

        ttk.Button(action_frame, text="Analyze Image", command=self._analyze_current).pack(fill=tk.X, pady=2)
        ttk.Button(action_frame, text="Analyze All", command=self._analyze_all).pack(fill=tk.X, pady=2)

        ttk.Separator(action_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # Price
        price_row = ttk.Frame(action_frame)
        price_row.pack(fill=tk.X, pady=2)
        ttk.Label(price_row, text="Price: $").pack(side=tk.LEFT)
        self.price_entry = ttk.Entry(price_row, width=10)
        self.price_entry.pack(side=tk.LEFT)
        self.price_entry.insert(0, str(config.DEFAULT_PRICE))

        # Shipping
        ship_row = ttk.Frame(action_frame)
        ship_row.pack(fill=tk.X, pady=2)
        ttk.Label(ship_row, text="Shipping: $").pack(side=tk.LEFT)
        self.shipping_entry = ttk.Entry(ship_row, width=10)
        self.shipping_entry.pack(side=tk.LEFT)
        self.shipping_entry.insert(0, str(config.SHIPPING_COST))

        # Quantity
        qty_row = ttk.Frame(action_frame)
        qty_row.pack(fill=tk.X, pady=2)
        ttk.Label(qty_row, text="Quantity:").pack(side=tk.LEFT)
        self.quantity_entry = ttk.Entry(qty_row, width=10)
        self.quantity_entry.pack(side=tk.LEFT)
        self.quantity_entry.insert(0, "1")

        # Barcode
        barcode_row = ttk.Frame(action_frame)
        barcode_row.pack(fill=tk.X, pady=2)
        ttk.Label(barcode_row, text="Barcode:").pack(side=tk.LEFT)
        self.barcode_entry = ttk.Entry(barcode_row, width=14)
        self.barcode_entry.pack(side=tk.LEFT, padx=(0, 2))
        self.barcode_entry.bind("<Return>", self._on_barcode_scan)

        ttk.Separator(action_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        ttk.Button(action_frame, text="Create Listing", command=self._create_listing).pack(fill=tk.X, pady=2)
        ttk.Button(action_frame, text="List All", command=self._list_all).pack(fill=tk.X, pady=2)
        ttk.Button(action_frame, text="View History", command=self._view_history).pack(fill=tk.X, pady=2)

        # Status
        ttk.Separator(action_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)
        self.status_label = ttk.Label(action_frame, text="Ready", foreground="gray", wraplength=180)
        self.status_label.pack(anchor=tk.W)

        # Progress bar
        self.progress = ttk.Progressbar(action_frame, mode="indeterminate")
        self.progress.pack(fill=tk.X, pady=5)

    def _select_folder(self):
        """Open folder selection dialog."""
        folder = filedialog.askdirectory(title="Select Image Folder")
        if folder:
            self._load_images(Path(folder))

    def _select_files(self):
        """Open file selection dialog."""
        files = filedialog.askopenfilenames(
            title="Select Images",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.gif *.bmp *.webp"),
                ("All files", "*.*")
            ]
        )
        if files:
            self.images = [Path(f) for f in files]
            self._update_image_list()

    def _load_images(self, folder: Path):
        """Load images from folder."""
        self.images = get_image_files(folder)
        self._update_image_list()
        self.folder_label.configure(text=f"{len(self.images)} images from {folder.name}")

    def _update_image_list(self):
        """Update the image listbox."""
        self.image_listbox.delete(0, tk.END)
        for img in self.images:
            self.image_listbox.insert(tk.END, img.name)

        if self.images:
            self.image_listbox.selection_set(0)
            self._on_image_select(None)

    def _on_image_select(self, event):
        """Handle image selection."""
        selection = self.image_listbox.curselection()
        if not selection:
            return

        self.current_index = selection[0]
        image_path = self.images[self.current_index]

        # Process and display image
        processed, self.current_image_bytes = process_image(image_path)

        # Resize for preview
        preview_size = (400, 300)
        processed.thumbnail(preview_size, Image.Resampling.LANCZOS)

        self.preview_photo = ImageTk.PhotoImage(processed)
        self.preview_label.configure(image=self.preview_photo, text="")

        # Clear content
        self.title_entry.delete(0, tk.END)
        self.description_text.delete("1.0", tk.END)
        self.current_content = None
        self._update_title_count(None)

    def _update_title_count(self, event):
        """Update title character count."""
        count = len(self.title_entry.get())
        self.title_count.configure(
            text=f"{count}/80",
            foreground="red" if count > 80 else "black"
        )

    def _set_status(self, text: str, color: str = "gray"):
        """Update status label."""
        self.status_label.configure(text=text, foreground=color)

    def _on_barcode_scan(self, event):
        """Handle barcode scan/entry."""
        barcode = self.barcode_entry.get().strip().upper()
        if not barcode:
            return

        # Check if barcode exists in inventory
        inventory = get_inventory()
        item = inventory.get_item(barcode)

        if item:
            # Load existing inventory item data
            self._set_status(f"Barcode found: {item.title or 'Untitled'}", "green")
            if item.title:
                self.title_entry.delete(0, tk.END)
                self.title_entry.insert(0, item.title)
            if item.description:
                self.description_text.delete("1.0", tk.END)
                self.description_text.insert("1.0", item.description)
            if item.price:
                self.price_entry.delete(0, tk.END)
                self.price_entry.insert(0, str(item.price))
            if item.quantity:
                self.quantity_entry.delete(0, tk.END)
                self.quantity_entry.insert(0, str(item.quantity))
            self._update_title_count(None)
        else:
            self._set_status(f"New barcode: {barcode}", "blue")

    def _analyze_current(self):
        """Analyze the current image."""
        if self.current_image_bytes is None:
            messagebox.showwarning("No Image", "Please select an image first.")
            return

        missing = config.validate()
        if "OPENAI_API_KEY" in missing:
            messagebox.showerror("Configuration Error", "OpenAI API key not configured.")
            return

        self._set_status("Analyzing...", "blue")
        self.progress.start()

        def analyze():
            try:
                content = analyze_image(self.current_image_bytes)
                self.after(0, lambda: self._show_content(content))
            except Exception as e:
                self.after(0, lambda: self._show_error(f"Analysis failed: {e}"))

        threading.Thread(target=analyze, daemon=True).start()

    def _show_content(self, content):
        """Display generated content."""
        self.progress.stop()
        self.current_content = content

        self.title_entry.delete(0, tk.END)
        self.title_entry.insert(0, content.title)

        self.description_text.delete("1.0", tk.END)
        self.description_text.insert("1.0", content.description)

        self._update_title_count(None)
        self._set_status("Analysis complete!", "green")

    def _show_error(self, message: str):
        """Show error message."""
        self.progress.stop()
        self._set_status(message, "red")
        messagebox.showerror("Error", message)

    def _analyze_all(self):
        """Analyze all images."""
        if not self.images:
            messagebox.showwarning("No Images", "Please load images first.")
            return

        missing = config.validate()
        if "OPENAI_API_KEY" in missing:
            messagebox.showerror("Configuration Error", "OpenAI API key not configured.")
            return

        result = messagebox.askyesno(
            "Analyze All",
            f"Analyze {len(self.images)} images?\nThis will use your OpenAI API credits."
        )
        if not result:
            return

        self._set_status("Analyzing all images...", "blue")
        self.progress.start()

        def analyze_all():
            results = []
            for i, img_path in enumerate(self.images):
                self.after(0, lambda i=i: self._set_status(f"Analyzing {i+1}/{len(self.images)}...", "blue"))
                try:
                    _, img_bytes = process_image(img_path)
                    content = analyze_image(img_bytes)
                    results.append((img_path, content, None))
                except Exception as e:
                    results.append((img_path, None, str(e)))

            self.after(0, lambda: self._analysis_complete(results))

        threading.Thread(target=analyze_all, daemon=True).start()

    def _analysis_complete(self, results):
        """Handle completion of batch analysis."""
        self.progress.stop()

        success = sum(1 for _, c, e in results if c is not None)
        failed = len(results) - success

        self._set_status(f"Done! {success} analyzed, {failed} failed", "green" if failed == 0 else "orange")

        # Store results for listing
        self.analysis_results = {str(path): content for path, content, err in results if content}

        if failed > 0:
            errors = [f"{path.name}: {err}" for path, _, err in results if err]
            messagebox.showwarning("Some Analyses Failed", "\n".join(errors[:5]))

    def _create_listing(self):
        """Create listing for current image."""
        if self.current_image_bytes is None:
            messagebox.showwarning("No Image", "Please select an image first.")
            return

        title = self.title_entry.get().strip()
        description = self.description_text.get("1.0", tk.END).strip()

        if not title or not description:
            messagebox.showwarning("Missing Content", "Please analyze the image first or enter title/description.")
            return

        missing = config.validate()
        if missing:
            messagebox.showerror("Configuration Error", f"Missing: {', '.join(missing)}")
            return

        try:
            price = float(self.price_entry.get())
            shipping = float(self.shipping_entry.get())
            quantity = int(self.quantity_entry.get())
            if quantity < 1:
                raise ValueError("Quantity must be at least 1")
        except ValueError as e:
            messagebox.showerror("Invalid Input", f"Please enter valid values.\n{e}")
            return

        barcode = self.barcode_entry.get().strip().upper()

        env = "SANDBOX" if config.EBAY_SANDBOX else "PRODUCTION"
        barcode_msg = f"\nBarcode: {barcode}" if barcode else ""
        result = messagebox.askyesno(
            "Confirm Listing",
            f"Create listing in {env}?\n\nTitle: {title[:50]}...\nPrice: ${price:.2f}\nShipping: ${shipping:.2f}\nQuantity: {quantity}{barcode_msg}"
        )
        if not result:
            return

        self._set_status("Creating listing...", "blue")
        self.progress.start()

        image_name = self.images[self.current_index].name if self.current_index >= 0 else None
        image_path = str(self.images[self.current_index]) if self.current_index >= 0 else None

        def create():
            try:
                lister = EbayLister()
                result = lister.create_listing(
                    title=title,
                    description=description,
                    image_bytes=self.current_image_bytes,
                    price=price,
                    shipping_cost=shipping,
                    quantity=quantity
                )
                result.image_name = image_name
                result.barcode = barcode if barcode else None
                if result.success:
                    save_listing(result)
                    # Update inventory if barcode provided
                    if barcode:
                        inventory = get_inventory()
                        if inventory.barcode_exists(barcode):
                            inventory.mark_listed(barcode, result.listing_id, result.listing_url)
                        else:
                            inventory.add_item(
                                barcode=barcode,
                                title=title,
                                description=description,
                                image_path=image_path,
                                quantity=quantity,
                                price=price
                            )
                            inventory.mark_listed(barcode, result.listing_id, result.listing_url)
                self.after(0, lambda: self._listing_complete(result))
            except Exception as e:
                self.after(0, lambda: self._show_error(f"Listing failed: {e}"))

        threading.Thread(target=create, daemon=True).start()

    def _listing_complete(self, result):
        """Handle listing creation result."""
        self.progress.stop()

        if result.success:
            self._set_status("Listing created!", "green")
            messagebox.showinfo(
                "Listing Created",
                f"Success!\n\nListing ID: {result.listing_id}\nURL: {result.listing_url}"
            )
        else:
            self._set_status("Listing failed", "red")
            messagebox.showerror("Listing Failed", result.error)

    def _list_all(self):
        """Create listings for all analyzed images."""
        if not hasattr(self, "analysis_results") or not self.analysis_results:
            messagebox.showwarning("No Analysis", "Please analyze images first using 'Analyze All'.")
            return

        missing = config.validate()
        if missing:
            messagebox.showerror("Configuration Error", f"Missing: {', '.join(missing)}")
            return

        try:
            price = float(self.price_entry.get())
            shipping = float(self.shipping_entry.get())
            quantity = int(self.quantity_entry.get())
            if quantity < 1:
                raise ValueError("Quantity must be at least 1")
        except ValueError as e:
            messagebox.showerror("Invalid Input", f"Please enter valid values.\n{e}")
            return

        count = len(self.analysis_results)
        env = "SANDBOX" if config.EBAY_SANDBOX else "PRODUCTION"

        result = messagebox.askyesno(
            "Create All Listings",
            f"Create {count} listings in {env}?\n\nPrice: ${price:.2f} each\nShipping: ${shipping:.2f}\nQuantity: {quantity} each"
        )
        if not result:
            return

        self._set_status("Creating listings...", "blue")
        self.progress.start()

        def create_all():
            lister = EbayLister()
            success = 0
            failed = 0

            for path_str, content in self.analysis_results.items():
                path = Path(path_str)
                self.after(0, lambda s=success, f=failed: self._set_status(
                    f"Creating {s+f+1}/{count}...", "blue"
                ))

                try:
                    _, img_bytes = process_image(path)
                    result = lister.create_listing(
                        title=content.title,
                        description=content.description,
                        image_bytes=img_bytes,
                        price=price,
                        shipping_cost=shipping,
                        quantity=quantity
                    )
                    if result.success:
                        result.image_name = path.name
                        save_listing(result)
                        success += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1

            self.after(0, lambda: self._batch_listing_complete(success, failed))

        threading.Thread(target=create_all, daemon=True).start()

    def _batch_listing_complete(self, success: int, failed: int):
        """Handle batch listing completion."""
        self.progress.stop()
        self._set_status(f"Done! {success} listed, {failed} failed", "green" if failed == 0 else "orange")
        messagebox.showinfo("Batch Complete", f"Created {success} listings.\nFailed: {failed}")

    def _view_history(self):
        """Show listing history in a popup window."""
        if not LISTINGS_FILE.exists():
            messagebox.showinfo("No History", "No listings have been created yet.")
            return

        try:
            with open(LISTINGS_FILE, "r") as f:
                history = json.load(f)
        except (json.JSONDecodeError, IOError):
            messagebox.showerror("Error", "Could not read history file.")
            return

        if not history:
            messagebox.showinfo("No History", "No listings have been created yet.")
            return

        # Create popup window
        popup = tk.Toplevel(self)
        popup.title("Listing History")
        popup.geometry("800x400")

        # Treeview for listings
        columns = ("date", "barcode", "title", "price", "qty", "listing_id", "url")
        tree = ttk.Treeview(popup, columns=columns, show="headings")

        tree.heading("date", text="Date")
        tree.heading("barcode", text="Barcode")
        tree.heading("title", text="Title")
        tree.heading("price", text="Price")
        tree.heading("qty", text="Qty")
        tree.heading("listing_id", text="Listing ID")
        tree.heading("url", text="URL")

        tree.column("date", width=120)
        tree.column("barcode", width=90)
        tree.column("title", width=180)
        tree.column("price", width=55)
        tree.column("qty", width=35)
        tree.column("listing_id", width=110)
        tree.column("url", width=190)

        # Add scrollbar
        scrollbar = ttk.Scrollbar(popup, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        # Populate with data (newest first)
        for entry in reversed(history):
            date_str = entry.get("created_at", "")[:16].replace("T", " ")
            tree.insert("", tk.END, values=(
                date_str,
                entry.get("barcode", ""),
                entry.get("title", "")[:35],
                f"${entry.get('price', 0):.2f}",
                entry.get("quantity", 1),
                entry.get("listing_id", ""),
                entry.get("listing_url", "")
            ))

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Double-click to open URL
        def on_double_click(event):
            item = tree.selection()
            if item:
                url = tree.item(item[0])["values"][6]
                if url:
                    import webbrowser
                    webbrowser.open(url)

        tree.bind("<Double-1>", on_double_click)

        # Info label
        ttk.Label(popup, text="Double-click a row to open the listing in browser").pack(pady=5)


class InventoryFrame(ttk.Frame):
    """Inventory management and barcode printing panel."""

    THUMB_SIZE = (40, 40)  # Thumbnail dimensions

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._thumbnails = {}  # Keep references to prevent garbage collection
        self._create_widgets()
        self._refresh_inventory()

    def _create_widgets(self):
        """Create inventory management interface."""
        # Main container
        container = ttk.Frame(self, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        # Top section - Barcode printing
        print_frame = ttk.LabelFrame(container, text="Print Barcode Labels (Avery 5167 - 0.5\" x 1.75\")", padding=10)
        print_frame.pack(fill=tk.X, pady=(0, 10))

        # Print options row
        options_row = ttk.Frame(print_frame)
        options_row.pack(fill=tk.X, pady=5)

        ttk.Label(options_row, text="Number of labels:").pack(side=tk.LEFT)
        self.num_labels_entry = ttk.Entry(options_row, width=8)
        self.num_labels_entry.pack(side=tk.LEFT, padx=5)
        self.num_labels_entry.insert(0, "80")

        ttk.Label(options_row, text="(80 per sheet)").pack(side=tk.LEFT, padx=(0, 20))

        ttk.Button(options_row, text="Print Labels", command=self._print_labels).pack(side=tk.LEFT, padx=5)
        ttk.Button(options_row, text="Preview Barcodes", command=self._preview_barcodes).pack(side=tk.LEFT, padx=5)

        # Next barcode info
        self.next_barcode_label = ttk.Label(print_frame, text="", foreground="blue")
        self.next_barcode_label.pack(anchor=tk.W, pady=5)
        self._update_next_barcode()

        # Middle section - Add to inventory
        add_frame = ttk.LabelFrame(container, text="Add Item to Inventory", padding=10)
        add_frame.pack(fill=tk.X, pady=(0, 10))

        # Barcode entry
        barcode_row = ttk.Frame(add_frame)
        barcode_row.pack(fill=tk.X, pady=2)
        ttk.Label(barcode_row, text="Scan Barcode:", width=15).pack(side=tk.LEFT)
        self.add_barcode_entry = ttk.Entry(barcode_row, width=20)
        self.add_barcode_entry.pack(side=tk.LEFT, padx=5)
        self.add_barcode_entry.bind("<Return>", self._on_add_barcode_scan)

        # Title entry
        title_row = ttk.Frame(add_frame)
        title_row.pack(fill=tk.X, pady=2)
        ttk.Label(title_row, text="Title:", width=15).pack(side=tk.LEFT)
        self.add_title_entry = ttk.Entry(title_row, width=50)
        self.add_title_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        # Quantity entry
        qty_row = ttk.Frame(add_frame)
        qty_row.pack(fill=tk.X, pady=2)
        ttk.Label(qty_row, text="Quantity:", width=15).pack(side=tk.LEFT)
        self.add_qty_entry = ttk.Entry(qty_row, width=10)
        self.add_qty_entry.pack(side=tk.LEFT, padx=5)
        self.add_qty_entry.insert(0, "1")

        # Price entry
        price_row = ttk.Frame(add_frame)
        price_row.pack(fill=tk.X, pady=2)
        ttk.Label(price_row, text="Price: $", width=15).pack(side=tk.LEFT)
        self.add_price_entry = ttk.Entry(price_row, width=10)
        self.add_price_entry.pack(side=tk.LEFT, padx=5)

        # Image path entry
        image_row = ttk.Frame(add_frame)
        image_row.pack(fill=tk.X, pady=2)
        ttk.Label(image_row, text="Image:", width=15).pack(side=tk.LEFT)
        self.add_image_entry = ttk.Entry(image_row, width=40)
        self.add_image_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(image_row, text="Browse", width=8, command=self._browse_image).pack(side=tk.LEFT, padx=2)

        # Add button
        btn_row = ttk.Frame(add_frame)
        btn_row.pack(fill=tk.X, pady=5)
        ttk.Button(btn_row, text="Add to Inventory", command=self._add_to_inventory).pack(side=tk.LEFT)
        self.add_status_label = ttk.Label(btn_row, text="", foreground="gray")
        self.add_status_label.pack(side=tk.LEFT, padx=10)

        # Bottom section - Inventory list
        list_frame = ttk.LabelFrame(container, text="Inventory", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True)

        # Toolbar
        toolbar = ttk.Frame(list_frame)
        toolbar.pack(fill=tk.X, pady=(0, 5))

        ttk.Button(toolbar, text="Refresh", command=self._refresh_inventory).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Delete Selected", command=self._delete_selected).pack(side=tk.LEFT, padx=2)

        # Stats label
        self.stats_label = ttk.Label(toolbar, text="", foreground="gray")
        self.stats_label.pack(side=tk.RIGHT, padx=5)

        # Configure style for larger row height to fit thumbnails
        style = ttk.Style()
        style.configure("Inventory.Treeview", rowheight=45)

        # Treeview with image column
        columns = ("barcode", "title", "qty", "price", "status", "listing_id")
        self.tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="tree headings",  # Show tree column for images
            height=12,
            style="Inventory.Treeview"
        )

        # Tree column for thumbnail
        self.tree.heading("#0", text="Image")
        self.tree.column("#0", width=50, minwidth=50)

        self.tree.heading("barcode", text="Barcode")
        self.tree.heading("title", text="Title")
        self.tree.heading("qty", text="Qty")
        self.tree.heading("price", text="Price")
        self.tree.heading("status", text="Status")
        self.tree.heading("listing_id", text="Listing ID")

        self.tree.column("barcode", width=95)
        self.tree.column("title", width=260)
        self.tree.column("qty", width=45)
        self.tree.column("price", width=65)
        self.tree.column("status", width=75)
        self.tree.column("listing_id", width=110)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _update_next_barcode(self):
        """Update the next barcode label."""
        try:
            next_barcode = get_next_barcode_number()
            self.next_barcode_label.configure(text=f"Next barcode: {next_barcode}")
        except Exception as e:
            self.next_barcode_label.configure(text=f"Error: {e}", foreground="red")

    def _preview_barcodes(self):
        """Preview the next batch of barcodes."""
        try:
            num_labels = int(self.num_labels_entry.get())
            barcodes = peek_barcode_range(min(num_labels, 20))  # Show max 20
            preview = "\n".join(barcodes)
            if num_labels > 20:
                preview += f"\n... and {num_labels - 20} more"
            messagebox.showinfo("Barcode Preview", f"Next {len(barcodes)} barcodes:\n\n{preview}")
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid number of labels.")

    def _print_labels(self):
        """Generate and open PDF of barcode labels."""
        try:
            num_labels = int(self.num_labels_entry.get())
            if num_labels < 1:
                raise ValueError("Must print at least 1 label")
        except ValueError as e:
            messagebox.showerror("Invalid Input", f"Please enter a valid number.\n{e}")
            return

        # Ask for save location
        output_path = filedialog.asksaveasfilename(
            title="Save Barcode Labels PDF",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile=f"barcode_labels_{num_labels}.pdf"
        )

        if not output_path:
            return

        try:
            # Generate PDF
            pdf_path, barcodes = generate_label_sheet_pdf(output_path, num_labels)

            # Update next barcode display
            self._update_next_barcode()

            # Show success and offer to open
            result = messagebox.askyesno(
                "Labels Generated",
                f"Generated {len(barcodes)} barcode labels.\n\nBarcodes: {barcodes[0]} to {barcodes[-1]}\n\nOpen PDF now?"
            )

            if result:
                import os
                os.startfile(pdf_path)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate labels:\n{e}")

    def _browse_image(self):
        """Browse for an image file."""
        file_path = filedialog.askopenfilename(
            title="Select Postcard Image",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.gif *.bmp *.webp"),
                ("All files", "*.*")
            ]
        )
        if file_path:
            self.add_image_entry.delete(0, tk.END)
            self.add_image_entry.insert(0, file_path)

    def _on_add_barcode_scan(self, event):
        """Handle barcode scan in add section."""
        barcode = self.add_barcode_entry.get().strip().upper()
        if not barcode:
            return

        inventory = get_inventory()
        if inventory.barcode_exists(barcode):
            item = inventory.get_item(barcode)
            self.add_status_label.configure(
                text=f"Exists: {item.title or 'Untitled'} (Qty: {item.quantity})",
                foreground="orange"
            )
        else:
            self.add_status_label.configure(text="New barcode - ready to add", foreground="green")
            # Focus on title entry
            self.add_title_entry.focus_set()

    def _add_to_inventory(self):
        """Add item to inventory."""
        barcode = self.add_barcode_entry.get().strip().upper()
        title = self.add_title_entry.get().strip()
        image_path = self.add_image_entry.get().strip()

        if not barcode:
            messagebox.showwarning("Missing Barcode", "Please scan or enter a barcode.")
            return

        try:
            quantity = int(self.add_qty_entry.get())
            price_str = self.add_price_entry.get().strip()
            price = float(price_str) if price_str else None
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter valid quantity and price.")
            return

        inventory = get_inventory()

        if inventory.barcode_exists(barcode):
            # Update existing
            inventory.update_item(barcode, title=title, quantity=quantity, price=price, image_path=image_path or None)
            self.add_status_label.configure(text=f"Updated: {barcode}", foreground="green")
        else:
            # Add new
            inventory.add_item(barcode=barcode, title=title, quantity=quantity, price=price, image_path=image_path or None)
            self.add_status_label.configure(text=f"Added: {barcode}", foreground="green")

        # Clear entries
        self.add_barcode_entry.delete(0, tk.END)
        self.add_title_entry.delete(0, tk.END)
        self.add_qty_entry.delete(0, tk.END)
        self.add_qty_entry.insert(0, "1")
        self.add_price_entry.delete(0, tk.END)
        self.add_image_entry.delete(0, tk.END)

        # Focus back to barcode for next scan
        self.add_barcode_entry.focus_set()

        # Refresh list
        self._refresh_inventory()

    def _load_thumbnail(self, image_path: str) -> ImageTk.PhotoImage | None:
        """Load and cache a thumbnail image."""
        if not image_path:
            return None

        # Check cache first
        if image_path in self._thumbnails:
            return self._thumbnails[image_path]

        try:
            path = Path(image_path)
            if not path.exists():
                return None

            img = Image.open(path)
            img.thumbnail(self.THUMB_SIZE, Image.Resampling.LANCZOS)

            # Create a square image with padding
            thumb = Image.new("RGB", self.THUMB_SIZE, (240, 240, 240))
            offset = ((self.THUMB_SIZE[0] - img.width) // 2,
                      (self.THUMB_SIZE[1] - img.height) // 2)
            thumb.paste(img, offset)

            photo = ImageTk.PhotoImage(thumb)
            self._thumbnails[image_path] = photo
            return photo
        except Exception:
            return None

    def _refresh_inventory(self):
        """Refresh the inventory list."""
        # Clear tree and thumbnail cache
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._thumbnails.clear()

        inventory = get_inventory()
        items = inventory.get_all_items()

        # Sort by created_at descending
        items.sort(key=lambda x: x.created_at or "", reverse=True)

        # Create a default placeholder image
        placeholder = Image.new("RGB", self.THUMB_SIZE, (200, 200, 200))
        self._placeholder_photo = ImageTk.PhotoImage(placeholder)

        for item in items:
            # Load thumbnail
            thumb = self._load_thumbnail(item.image_path)
            if thumb is None:
                thumb = self._placeholder_photo

            self.tree.insert("", tk.END,
                image=thumb,
                values=(
                    item.barcode,
                    (item.title or "")[:45],
                    item.quantity,
                    f"${item.price:.2f}" if item.price else "",
                    item.status,
                    item.listing_id or ""
                )
            )

        # Update stats
        stats = inventory.get_stats()
        self.stats_label.configure(
            text=f"Total: {stats['total_items']} items ({stats['total_quantity']} qty) | "
                 f"Available: {stats['available']} | Listed: {stats['listed']} | Sold: {stats['sold']}"
        )

    def _delete_selected(self):
        """Delete selected inventory items."""
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select items to delete.")
            return

        barcodes = [self.tree.item(item)["values"][0] for item in selected]

        if not messagebox.askyesno("Confirm Delete", f"Delete {len(barcodes)} item(s)?"):
            return

        inventory = get_inventory()
        for barcode in barcodes:
            inventory.delete_item(barcode)

        self._refresh_inventory()


class BundleFrame(ttk.Frame):
    """Bundle creation panel for combining multiple postcards into one listing."""

    THUMB_SIZE = (100, 100)

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.selected_images = []  # List of Path objects
        self._thumbnails = {}
        self._collage_photo = None
        self._create_widgets()

    def _create_widgets(self):
        """Create bundle interface."""
        # Main container with horizontal panes
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left panel - Image selection
        left_frame = ttk.Frame(paned, width=300)
        paned.add(left_frame, weight=1)

        # Toolbar
        toolbar = ttk.Frame(left_frame)
        toolbar.pack(fill=tk.X, pady=5)

        ttk.Button(toolbar, text="Add Images", command=self._add_images).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Remove Selected", command=self._remove_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Clear All", command=self._clear_all).pack(side=tk.LEFT, padx=2)

        # Selected images list with thumbnails
        ttk.Label(left_frame, text="Selected Images for Bundle:", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, padx=5)

        list_frame = ttk.Frame(left_frame)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Configure style for image list
        style = ttk.Style()
        style.configure("Bundle.Treeview", rowheight=80)

        self.image_tree = ttk.Treeview(
            list_frame,
            columns=("filename",),
            show="tree headings",
            height=8,
            style="Bundle.Treeview"
        )
        self.image_tree.heading("#0", text="Preview")
        self.image_tree.heading("filename", text="Filename")
        self.image_tree.column("#0", width=90)
        self.image_tree.column("filename", width=180)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.image_tree.yview)
        self.image_tree.configure(yscrollcommand=scrollbar.set)

        self.image_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Center panel - Collage preview
        center_frame = ttk.Frame(paned)
        paned.add(center_frame, weight=2)

        preview_frame = ttk.LabelFrame(center_frame, text="Bundle Collage Preview", padding=10)
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        self.collage_label = ttk.Label(preview_frame, text="Add images to see collage preview", anchor=tk.CENTER)
        self.collage_label.pack(fill=tk.BOTH, expand=True)

        ttk.Button(center_frame, text="Generate Collage Preview", command=self._generate_preview).pack(pady=5)

        # Right panel - Listing details
        right_frame = ttk.Frame(paned, width=280)
        paned.add(right_frame, weight=1)

        details_frame = ttk.LabelFrame(right_frame, text="Bundle Listing Details", padding=10)
        details_frame.pack(fill=tk.BOTH, expand=True)

        # Title
        ttk.Label(details_frame, text="Title:").pack(anchor=tk.W)
        self.title_entry = ttk.Entry(details_frame, width=35)
        self.title_entry.pack(fill=tk.X, pady=(0, 5))

        # Description
        ttk.Label(details_frame, text="Description:").pack(anchor=tk.W)
        self.description_text = scrolledtext.ScrolledText(details_frame, height=8, width=35)
        self.description_text.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        # Price
        price_frame = ttk.Frame(details_frame)
        price_frame.pack(fill=tk.X, pady=2)
        ttk.Label(price_frame, text="Bundle Price: $").pack(side=tk.LEFT)
        self.price_entry = ttk.Entry(price_frame, width=10)
        self.price_entry.pack(side=tk.LEFT)
        self.price_entry.insert(0, str(config.DEFAULT_PRICE))

        # Shipping
        ship_frame = ttk.Frame(details_frame)
        ship_frame.pack(fill=tk.X, pady=2)
        ttk.Label(ship_frame, text="Shipping: $").pack(side=tk.LEFT)
        self.shipping_entry = ttk.Entry(ship_frame, width=10)
        self.shipping_entry.pack(side=tk.LEFT)
        self.shipping_entry.insert(0, str(config.SHIPPING_COST))

        # Quantity
        qty_frame = ttk.Frame(details_frame)
        qty_frame.pack(fill=tk.X, pady=2)
        ttk.Label(qty_frame, text="Quantity:").pack(side=tk.LEFT)
        self.quantity_entry = ttk.Entry(qty_frame, width=10)
        self.quantity_entry.pack(side=tk.LEFT)
        self.quantity_entry.insert(0, "1")

        # Barcode
        barcode_frame = ttk.Frame(details_frame)
        barcode_frame.pack(fill=tk.X, pady=2)
        ttk.Label(barcode_frame, text="Barcode:").pack(side=tk.LEFT)
        self.barcode_entry = ttk.Entry(barcode_frame, width=14)
        self.barcode_entry.pack(side=tk.LEFT)

        ttk.Separator(details_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # AI Analysis button
        ttk.Button(details_frame, text="AI Analyze Bundle", command=self._analyze_bundle).pack(fill=tk.X, pady=2)

        # Create listing button
        ttk.Button(details_frame, text="Create Bundle Listing", command=self._create_bundle_listing).pack(fill=tk.X, pady=2)

        # Status
        self.status_label = ttk.Label(details_frame, text="Ready", foreground="gray", wraplength=250)
        self.status_label.pack(anchor=tk.W, pady=5)

        self.progress = ttk.Progressbar(details_frame, mode="indeterminate")
        self.progress.pack(fill=tk.X)

    def _add_images(self):
        """Add images to the bundle."""
        files = filedialog.askopenfilenames(
            title="Select Postcards for Bundle",
            filetypes=[
                ("Image files", "*.jpg *.jpeg *.png *.gif *.bmp *.webp"),
                ("All files", "*.*")
            ]
        )
        if files:
            for f in files:
                path = Path(f)
                if path not in self.selected_images:
                    self.selected_images.append(path)
            self._refresh_image_list()

    def _remove_selected(self):
        """Remove selected images from bundle."""
        selected = self.image_tree.selection()
        if not selected:
            return

        # Get indices to remove
        indices_to_remove = []
        for item in selected:
            idx = self.image_tree.index(item)
            indices_to_remove.append(idx)

        # Remove in reverse order to maintain indices
        for idx in sorted(indices_to_remove, reverse=True):
            if idx < len(self.selected_images):
                del self.selected_images[idx]

        self._refresh_image_list()

    def _clear_all(self):
        """Clear all selected images."""
        self.selected_images.clear()
        self._thumbnails.clear()
        self._refresh_image_list()
        self.collage_label.configure(image="", text="Add images to see collage preview")

    def _load_thumbnail(self, image_path: Path) -> ImageTk.PhotoImage | None:
        """Load and cache a thumbnail."""
        path_str = str(image_path)
        if path_str in self._thumbnails:
            return self._thumbnails[path_str]

        try:
            img = Image.open(image_path)
            img.thumbnail(self.THUMB_SIZE, Image.Resampling.LANCZOS)

            # Create square with padding
            thumb = Image.new("RGB", self.THUMB_SIZE, (240, 240, 240))
            offset = ((self.THUMB_SIZE[0] - img.width) // 2,
                      (self.THUMB_SIZE[1] - img.height) // 2)
            thumb.paste(img, offset)

            photo = ImageTk.PhotoImage(thumb)
            self._thumbnails[path_str] = photo
            return photo
        except Exception:
            return None

    def _refresh_image_list(self):
        """Refresh the image list display."""
        for item in self.image_tree.get_children():
            self.image_tree.delete(item)

        for path in self.selected_images:
            thumb = self._load_thumbnail(path)
            if thumb:
                self.image_tree.insert("", tk.END, image=thumb, values=(path.name,))
            else:
                self.image_tree.insert("", tk.END, values=(path.name,))

    def _generate_preview(self):
        """Generate and display collage preview."""
        if not self.selected_images:
            messagebox.showwarning("No Images", "Please add images to the bundle first.")
            return

        self.status_label.configure(text="Generating preview...", foreground="blue")
        self.update()

        try:
            collage_img, _ = create_bundle_collage(self.selected_images)

            # Resize for preview
            preview_size = (500, 400)
            collage_img.thumbnail(preview_size, Image.Resampling.LANCZOS)

            self._collage_photo = ImageTk.PhotoImage(collage_img)
            self.collage_label.configure(image=self._collage_photo, text="")

            self.status_label.configure(text=f"Preview: {len(self.selected_images)} postcards", foreground="green")
        except Exception as e:
            self.status_label.configure(text=f"Preview failed: {e}", foreground="red")

    def _analyze_bundle(self):
        """Analyze bundle with AI to generate title/description."""
        if not self.selected_images:
            messagebox.showwarning("No Images", "Please add images to the bundle first.")
            return

        missing = config.validate()
        if "OPENAI_API_KEY" in missing:
            messagebox.showerror("Configuration Error", "OpenAI API key not configured.")
            return

        self.status_label.configure(text="Analyzing bundle...", foreground="blue")
        self.progress.start()

        def analyze():
            try:
                # Create collage for analysis
                _, collage_bytes = create_bundle_collage(self.selected_images)

                # Analyze the collage
                content = analyze_image(collage_bytes)

                # Modify title to indicate bundle
                bundle_title = content.title
                if "postcard" in bundle_title.lower() and "lot" not in bundle_title.lower():
                    bundle_title = bundle_title.replace("Postcard", f"Postcard Lot of {len(self.selected_images)}")
                    bundle_title = bundle_title.replace("postcard", f"Postcard Lot of {len(self.selected_images)}")

                self.after(0, lambda: self._show_analysis(bundle_title, content.description))
            except Exception as e:
                self.after(0, lambda: self._show_error(f"Analysis failed: {e}"))

        threading.Thread(target=analyze, daemon=True).start()

    def _show_analysis(self, title, description):
        """Display AI analysis results."""
        self.progress.stop()

        self.title_entry.delete(0, tk.END)
        self.title_entry.insert(0, title[:80])

        self.description_text.delete("1.0", tk.END)
        # Add bundle info to description
        bundle_desc = f"<p><b>This listing is for a lot of {len(self.selected_images)} postcards as shown.</b></p>\n\n"
        self.description_text.insert("1.0", bundle_desc + description)

        self.status_label.configure(text="Analysis complete!", foreground="green")

    def _show_error(self, message):
        """Show error message."""
        self.progress.stop()
        self.status_label.configure(text=message, foreground="red")
        messagebox.showerror("Error", message)

    def _create_bundle_listing(self):
        """Create the bundle listing on eBay."""
        if not self.selected_images:
            messagebox.showwarning("No Images", "Please add images to the bundle first.")
            return

        title = self.title_entry.get().strip()
        description = self.description_text.get("1.0", tk.END).strip()

        if not title or not description:
            messagebox.showwarning("Missing Content", "Please enter title and description or use AI Analyze.")
            return

        missing = config.validate()
        if missing:
            messagebox.showerror("Configuration Error", f"Missing: {', '.join(missing)}")
            return

        try:
            price = float(self.price_entry.get())
            shipping = float(self.shipping_entry.get())
            quantity = int(self.quantity_entry.get())
            if quantity < 1:
                raise ValueError("Quantity must be at least 1")
        except ValueError as e:
            messagebox.showerror("Invalid Input", f"Please enter valid values.\n{e}")
            return

        barcode = self.barcode_entry.get().strip().upper()

        env = "SANDBOX" if config.EBAY_SANDBOX else "PRODUCTION"
        result = messagebox.askyesno(
            "Confirm Bundle Listing",
            f"Create bundle listing in {env}?\n\n"
            f"Items: {len(self.selected_images)} postcards\n"
            f"Title: {title[:50]}...\n"
            f"Price: ${price:.2f}\n"
            f"Shipping: ${shipping:.2f}"
        )
        if not result:
            return

        self.status_label.configure(text="Creating bundle listing...", foreground="blue")
        self.progress.start()

        def create():
            try:
                # Process all images (collage + individuals)
                all_images = process_images_for_bundle(self.selected_images)
                image_bytes_list = [img_bytes for _, img_bytes in all_images]

                lister = EbayLister()
                result = lister.create_bundle_listing(
                    title=title,
                    description=description,
                    image_bytes_list=image_bytes_list,
                    price=price,
                    shipping_cost=shipping,
                    quantity=quantity
                )

                result.barcode = barcode if barcode else None
                result.image_name = f"bundle_{len(self.selected_images)}_postcards"

                if result.success:
                    save_listing(result)
                    if barcode:
                        inventory = get_inventory()
                        if not inventory.barcode_exists(barcode):
                            inventory.add_item(
                                barcode=barcode,
                                title=title,
                                quantity=quantity,
                                price=price
                            )
                        inventory.mark_listed(barcode, result.listing_id, result.listing_url)

                self.after(0, lambda: self._listing_complete(result))
            except Exception as e:
                self.after(0, lambda: self._show_error(f"Listing failed: {e}"))

        threading.Thread(target=create, daemon=True).start()

    def _listing_complete(self, result):
        """Handle listing creation result."""
        self.progress.stop()

        if result.success:
            self.status_label.configure(text="Bundle listing created!", foreground="green")
            messagebox.showinfo(
                "Bundle Listing Created",
                f"Success!\n\nListing ID: {result.listing_id}\nURL: {result.listing_url}"
            )
            # Clear bundle after successful listing
            self._clear_all()
        else:
            self.status_label.configure(text="Listing failed", foreground="red")
            messagebox.showerror("Listing Failed", result.error)


class App(tk.Tk):
    """Main application window."""

    def __init__(self):
        super().__init__()

        self.title("eBay Postcard Auto-Lister")
        self.geometry("1200x800")
        self.minsize(900, 600)

        # Set icon if available
        try:
            self.iconbitmap(default="")
        except Exception:
            pass

        # Apply theme
        style = ttk.Style()
        style.theme_use("clam" if "clam" in style.theme_names() else "default")

        self._create_widgets()
        self._load_saved_config()

    def _create_widgets(self):
        """Create main application widgets."""
        # Notebook for tabs
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Listing tab
        self.listing_frame = ListingFrame(self.notebook, self)
        self.notebook.add(self.listing_frame, text="  Listings  ")

        # Bundle tab
        self.bundle_frame = BundleFrame(self.notebook, self)
        self.notebook.add(self.bundle_frame, text="  Bundle  ")

        # Inventory tab
        self.inventory_frame = InventoryFrame(self.notebook, self)
        self.notebook.add(self.inventory_frame, text="  Inventory  ")

        # Settings tab
        self.settings_frame = SettingsFrame(self.notebook, self)
        self.notebook.add(self.settings_frame, text="  Settings  ")

    def _load_saved_config(self):
        """Load saved configuration on startup."""
        data = ConfigManager.load()

        if data:
            # Determine environment
            is_sandbox = data.get("EBAY_SANDBOX", True)
            env_key = "sandbox" if is_sandbox else "production"
            env_data = data.get(env_key, {})

            # Update config object
            config.OPENAI_API_KEY = data.get("OPENAI_API_KEY", "")
            config.EBAY_APP_ID = env_data.get("EBAY_APP_ID", "")
            config.EBAY_CERT_ID = env_data.get("EBAY_CERT_ID", "")
            config.EBAY_DEV_ID = env_data.get("EBAY_DEV_ID", "")
            config.EBAY_OAUTH_TOKEN = env_data.get("EBAY_OAUTH_TOKEN", "")
            config.EBAY_SANDBOX = is_sandbox
            config.DEFAULT_PRICE = float(data.get("DEFAULT_PRICE", "9.99") or "9.99")
            config.SHIPPING_COST = float(data.get("SHIPPING_COST", "3.99") or "3.99")

            # Update price entries
            self.listing_frame.price_entry.delete(0, tk.END)
            self.listing_frame.price_entry.insert(0, str(config.DEFAULT_PRICE))
            self.listing_frame.shipping_entry.delete(0, tk.END)
            self.listing_frame.shipping_entry.insert(0, str(config.SHIPPING_COST))


def main():
    """Launch the GUI application."""
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
