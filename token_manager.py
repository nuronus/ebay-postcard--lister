"""
eBay OAuth Token Manager

Handles automatic token acquisition and refresh for eBay API authentication.
- Full OAuth 2.0 flow with browser authorization
- Automatic token refresh before expiration
- Persistent token storage
"""

import json
import base64
import requests
import webbrowser
import socket
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import threading


TOKEN_FILE = Path(__file__).parent / "ebay_tokens.json"

# Token refresh buffer - refresh 5 minutes before expiration
REFRESH_BUFFER_SECONDS = 300

# Local callback server settings
CALLBACK_PORT = 8888
CALLBACK_PATH = "/oauth/callback"


class TokenManager:
    """Manages eBay OAuth tokens with automatic refresh."""

    def __init__(self, sandbox: bool = True):
        self.sandbox = sandbox
        self._token_data: dict = {}
        self._load_tokens()

    @property
    def _token_url(self) -> str:
        if self.sandbox:
            return "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
        return "https://api.ebay.com/identity/v1/oauth2/token"

    @property
    def _auth_url(self) -> str:
        if self.sandbox:
            return "https://auth.sandbox.ebay.com/oauth2/authorize"
        return "https://auth.ebay.com/oauth2/authorize"

    @property
    def _ru_name_key(self) -> str:
        """Key for RuName in config - differs by environment."""
        return "EBAY_RU_NAME"

    def _get_env_key(self) -> str:
        return "sandbox" if self.sandbox else "production"

    def get_oauth_scopes(self) -> list[str]:
        """Get the OAuth scopes needed for the app."""
        return [
            "https://api.ebay.com/oauth/api_scope",
            "https://api.ebay.com/oauth/api_scope/sell.inventory",
            "https://api.ebay.com/oauth/api_scope/sell.account",
            "https://api.ebay.com/oauth/api_scope/sell.fulfillment"
        ]

    def start_oauth_flow(
        self,
        app_id: str,
        cert_id: str,
        ru_name: str,
        callback: callable = None
    ) -> bool:
        """
        Start the OAuth authorization flow.

        Opens browser for user to authorize, then exchanges code for tokens.

        Args:
            app_id: eBay App ID (Client ID)
            cert_id: eBay Cert ID (Client Secret)
            ru_name: eBay RuName (Redirect URL name from developer console)
            callback: Optional callback function(success: bool, message: str)

        Returns:
            True if authorization was successful
        """
        # Build authorization URL
        scopes = " ".join(self.get_oauth_scopes())

        params = {
            "client_id": app_id,
            "response_type": "code",
            "redirect_uri": ru_name,
            "scope": scopes
        }

        auth_url = f"{self._auth_url}?{urllib.parse.urlencode(params)}"

        # Start local server to receive callback
        auth_code = None
        server_error = None

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                nonlocal auth_code, server_error

                # Parse the callback URL
                parsed = urllib.parse.urlparse(self.path)
                query_params = urllib.parse.parse_qs(parsed.query)

                if "code" in query_params:
                    auth_code = query_params["code"][0]
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"""
                        <html><body style="font-family: Arial; text-align: center; padding-top: 50px;">
                        <h1>Authorization Successful!</h1>
                        <p>You can close this window and return to the app.</p>
                        </body></html>
                    """)
                elif "error" in query_params:
                    server_error = query_params.get("error_description", ["Authorization failed"])[0]
                    self.send_response(400)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(f"""
                        <html><body style="font-family: Arial; text-align: center; padding-top: 50px;">
                        <h1>Authorization Failed</h1>
                        <p>{server_error}</p>
                        </body></html>
                    """.encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                pass  # Suppress server logs

        # Find available port
        port = CALLBACK_PORT
        for attempt in range(10):
            try:
                server = HTTPServer(("localhost", port), CallbackHandler)
                break
            except socket.error:
                port += 1
        else:
            if callback:
                callback(False, "Could not start callback server")
            return False

        # Set timeout for server
        server.timeout = 120  # 2 minute timeout

        print(f"Starting OAuth flow...")
        print(f"Opening browser for eBay authorization...")

        # Open browser
        webbrowser.open(auth_url)

        # Wait for callback (with timeout)
        try:
            while auth_code is None and server_error is None:
                server.handle_request()
        except Exception as e:
            if callback:
                callback(False, f"Server error: {e}")
            return False
        finally:
            server.server_close()

        if server_error:
            if callback:
                callback(False, server_error)
            return False

        if not auth_code:
            if callback:
                callback(False, "No authorization code received")
            return False

        # Exchange code for tokens
        print("Exchanging authorization code for tokens...")
        success = self._exchange_code_for_tokens(auth_code, app_id, cert_id, ru_name)

        if success:
            if callback:
                callback(True, "Authorization successful!")
            return True
        else:
            if callback:
                callback(False, "Failed to exchange code for tokens")
            return False

    def _exchange_code_for_tokens(
        self,
        auth_code: str,
        app_id: str,
        cert_id: str,
        ru_name: str
    ) -> bool:
        """Exchange authorization code for access and refresh tokens."""
        # Create Basic auth header
        credentials = f"{app_id}:{cert_id}"
        auth_header = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_header}"
        }

        data = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": ru_name
        }

        try:
            response = requests.post(self._token_url, headers=headers, data=data, timeout=30)

            if response.status_code == 200:
                result = response.json()

                access_token = result.get("access_token")
                refresh_token = result.get("refresh_token")
                expires_in = result.get("expires_in", 7200)

                if access_token and refresh_token:
                    self.set_tokens(
                        access_token=access_token,
                        refresh_token=refresh_token,
                        expires_in=expires_in,
                        app_id=app_id,
                        cert_id=cert_id
                    )
                    print(f"Tokens obtained successfully! Expires in {expires_in}s")
                    return True

            print(f"Token exchange failed: {response.status_code} - {response.text[:200]}")
            return False

        except requests.exceptions.RequestException as e:
            print(f"Token exchange error: {e}")
            return False

    def _load_tokens(self) -> None:
        """Load tokens from file."""
        if TOKEN_FILE.exists():
            try:
                with open(TOKEN_FILE, "r") as f:
                    self._token_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._token_data = {}

    def _save_tokens(self) -> None:
        """Save tokens to file."""
        with open(TOKEN_FILE, "w") as f:
            json.dump(self._token_data, f, indent=2)

    def get_env_tokens(self) -> dict:
        """Get tokens for current environment."""
        return self._token_data.get(self._get_env_key(), {})

    def set_tokens(
        self,
        access_token: str,
        refresh_token: str,
        expires_in: int = 7200,
        app_id: str = "",
        cert_id: str = ""
    ) -> None:
        """
        Store tokens with expiration time.

        Args:
            access_token: The OAuth access token
            refresh_token: The OAuth refresh token (for renewal)
            expires_in: Token lifetime in seconds (default 2 hours)
            app_id: eBay App ID (for refresh requests)
            cert_id: eBay Cert ID (for refresh requests)
        """
        env_key = self._get_env_key()

        self._token_data[env_key] = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": (datetime.now() + timedelta(seconds=expires_in)).isoformat(),
            "app_id": app_id,
            "cert_id": cert_id,
            "updated_at": datetime.now().isoformat()
        }

        self._save_tokens()

    def get_access_token(self, app_id: str = "", cert_id: str = "") -> Optional[str]:
        """
        Get a valid access token, refreshing if necessary.

        Args:
            app_id: eBay App ID (used if refresh is needed)
            cert_id: eBay Cert ID (used if refresh is needed)

        Returns:
            Valid access token or None if refresh failed
        """
        tokens = self.get_env_tokens()

        if not tokens:
            return None

        access_token = tokens.get("access_token")
        expires_at_str = tokens.get("expires_at")

        if not access_token:
            return None

        # Check if token is expired or about to expire
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                if datetime.now() >= expires_at - timedelta(seconds=REFRESH_BUFFER_SECONDS):
                    # Token expired or expiring soon, try to refresh
                    print("  Token expired or expiring soon, refreshing...")
                    new_token = self.refresh_access_token(app_id, cert_id)
                    if new_token:
                        return new_token
                    # Refresh failed, return current token anyway (might still work)
                    print("  Warning: Token refresh failed, using existing token")
            except (ValueError, TypeError):
                pass

        return access_token

    def refresh_access_token(
        self,
        app_id: str = "",
        cert_id: str = ""
    ) -> Optional[str]:
        """
        Refresh the access token using the refresh token.

        Args:
            app_id: eBay App ID
            cert_id: eBay Cert ID

        Returns:
            New access token or None if refresh failed
        """
        tokens = self.get_env_tokens()

        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            print("  No refresh token available")
            return None

        # Use stored credentials if not provided
        app_id = app_id or tokens.get("app_id", "")
        cert_id = cert_id or tokens.get("cert_id", "")

        if not app_id or not cert_id:
            print("  Missing App ID or Cert ID for token refresh")
            return None

        # Create Basic auth header
        credentials = f"{app_id}:{cert_id}"
        auth_header = base64.b64encode(credentials.encode()).decode()

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {auth_header}"
        }

        # eBay OAuth scopes needed for selling
        scopes = [
            "https://api.ebay.com/oauth/api_scope",
            "https://api.ebay.com/oauth/api_scope/sell.inventory",
            "https://api.ebay.com/oauth/api_scope/sell.account",
            "https://api.ebay.com/oauth/api_scope/sell.fulfillment"
        ]

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": " ".join(scopes)
        }

        try:
            response = requests.post(self._token_url, headers=headers, data=data, timeout=30)

            if response.status_code == 200:
                result = response.json()
                new_access_token = result.get("access_token")
                expires_in = result.get("expires_in", 7200)

                # Update stored tokens (refresh token usually stays the same)
                new_refresh_token = result.get("refresh_token", refresh_token)

                self.set_tokens(
                    access_token=new_access_token,
                    refresh_token=new_refresh_token,
                    expires_in=expires_in,
                    app_id=app_id,
                    cert_id=cert_id
                )

                print(f"  Token refreshed successfully (expires in {expires_in}s)")
                return new_access_token
            else:
                print(f"  Token refresh failed: {response.status_code} - {response.text[:200]}")
                return None

        except requests.exceptions.RequestException as e:
            print(f"  Token refresh error: {e}")
            return None

    def is_token_valid(self) -> bool:
        """Check if current token is valid (not expired)."""
        tokens = self.get_env_tokens()

        if not tokens or not tokens.get("access_token"):
            return False

        expires_at_str = tokens.get("expires_at")
        if not expires_at_str:
            return True  # No expiration info, assume valid

        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            return datetime.now() < expires_at
        except (ValueError, TypeError):
            return True

    def get_token_status(self) -> dict:
        """Get current token status information."""
        tokens = self.get_env_tokens()

        if not tokens:
            return {"status": "missing", "message": "No tokens stored"}

        access_token = tokens.get("access_token", "")
        expires_at_str = tokens.get("expires_at")
        has_refresh = bool(tokens.get("refresh_token"))

        if not access_token:
            return {"status": "missing", "message": "No access token"}

        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
                now = datetime.now()

                if now >= expires_at:
                    return {
                        "status": "expired",
                        "message": "Token expired",
                        "has_refresh": has_refresh,
                        "can_refresh": has_refresh
                    }

                remaining = expires_at - now
                hours = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60

                return {
                    "status": "valid",
                    "message": f"Token valid for {hours}h {minutes}m",
                    "expires_at": expires_at_str,
                    "has_refresh": has_refresh
                }
            except (ValueError, TypeError):
                pass

        return {
            "status": "unknown",
            "message": "Token present (expiration unknown)",
            "has_refresh": has_refresh
        }

    def clear_tokens(self) -> None:
        """Clear tokens for current environment."""
        env_key = self._get_env_key()
        if env_key in self._token_data:
            del self._token_data[env_key]
            self._save_tokens()


# Global token manager instances
_token_managers: dict[str, TokenManager] = {}


def get_token_manager(sandbox: bool = True) -> TokenManager:
    """Get the token manager for the specified environment."""
    key = "sandbox" if sandbox else "production"
    if key not in _token_managers:
        _token_managers[key] = TokenManager(sandbox=sandbox)
    return _token_managers[key]
