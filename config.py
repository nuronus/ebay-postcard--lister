"""Configuration management for eBay Postcard Lister."""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # eBay credentials
    EBAY_APP_ID: str = os.getenv("EBAY_APP_ID", "")
    EBAY_CERT_ID: str = os.getenv("EBAY_CERT_ID", "")
    EBAY_DEV_ID: str = os.getenv("EBAY_DEV_ID", "")
    EBAY_RU_NAME: str = os.getenv("EBAY_RU_NAME", "")
    EBAY_OAUTH_TOKEN: str = os.getenv("EBAY_OAUTH_TOKEN", "")
    EBAY_REFRESH_TOKEN: str = os.getenv("EBAY_REFRESH_TOKEN", "")

    # eBay environment
    EBAY_SANDBOX: bool = os.getenv("EBAY_SANDBOX", "true").lower() == "true"

    # Listing defaults
    DEFAULT_PRICE: float = float(os.getenv("DEFAULT_PRICE", "9.99"))
    SHIPPING_COST: float = float(os.getenv("SHIPPING_COST", "3.99"))

    # eBay API URLs
    @property
    def ebay_api_url(self) -> str:
        if self.EBAY_SANDBOX:
            return "https://api.sandbox.ebay.com"
        return "https://api.ebay.com"

    def validate(self) -> list[str]:
        """Validate required configuration. Returns list of missing items."""
        missing = []

        if not self.OPENAI_API_KEY:
            missing.append("OPENAI_API_KEY")

        if not self.EBAY_APP_ID:
            missing.append("EBAY_APP_ID")

        if not self.EBAY_CERT_ID:
            missing.append("EBAY_CERT_ID")

        if not self.EBAY_DEV_ID:
            missing.append("EBAY_DEV_ID")

        if not self.EBAY_OAUTH_TOKEN:
            missing.append("EBAY_OAUTH_TOKEN")

        return missing


config = Config()
