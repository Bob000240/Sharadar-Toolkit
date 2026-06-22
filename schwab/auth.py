import os
import json
import base64
import time
import threading
import urllib.parse
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

_TOKEN_PATH = Path(__file__).parent / "tokens.json"
_AUTH_URL   = "https://api.schwabapi.com/v1/oauth/authorize"
_TOKEN_URL  = "https://api.schwabapi.com/v1/oauth/token"


class SchwabAuth:
    def __init__(self):
        self.app_key     = os.getenv("SCHWAB_APP_KEY")
        self.app_secret  = os.getenv("SCHWAB_APP_SECRET")
        self.callback_url = os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182")
        if not self.app_key or not self.app_secret:
            raise ValueError("SCHWAB_APP_KEY and SCHWAB_APP_SECRET must be set in .env")
        self._tokens: dict = self._load_tokens()

    # ------------------------------------------------------------------
    # Token persistence
    # ------------------------------------------------------------------

    def _load_tokens(self) -> dict:
        if _TOKEN_PATH.exists():
            return json.loads(_TOKEN_PATH.read_text())
        return {}

    def _save_tokens(self, data: dict) -> None:
        _TOKEN_PATH.write_text(json.dumps(data, indent=2))
        self._tokens = data

    def _basic_auth(self) -> str:
        return base64.b64encode(f"{self.app_key}:{self.app_secret}".encode()).decode()

    # ------------------------------------------------------------------
    # Public interface used by client.py
    # ------------------------------------------------------------------

    def get_access_token(self) -> str:
        """Return a valid access token, auto-refreshing if within 60s of expiry."""
        if not self._tokens:
            raise RuntimeError(
                "No tokens found. Run the auth flow first:\n"
                "  python -m schwab.auth"
            )
        if time.time() >= self._tokens.get("expires_at", 0) - 60:
            self.refresh()
        return self._tokens["access_token"]

    def refresh(self) -> None:
        """Exchange refresh_token for a new access_token (no browser needed)."""
        r = requests.post(
            _TOKEN_URL,
            headers={
                "Authorization": f"Basic {self._basic_auth()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type":    "refresh_token",
                "refresh_token": self._tokens["refresh_token"],
            },
        )
        r.raise_for_status()
        data = r.json()
        data["expires_at"] = time.time() + data["expires_in"]
        self._save_tokens(data)
        print("Access token refreshed.")

    # ------------------------------------------------------------------
    # Full OAuth flow — run once every 7 days
    # ------------------------------------------------------------------

    def authenticate(self) -> None:
        """
        Automates the Schwab login with Playwright.
        Pauses once to ask for the SMS code, then saves tokens to disk.

        Run: python -m schwab.auth
        """
        from playwright.sync_api import sync_playwright

        username = os.getenv("SCHWAB_USERNAME")
        password = os.getenv("SCHWAB_PASSWORD")
        if not username or not password:
            raise ValueError("SCHWAB_USERNAME and SCHWAB_PASSWORD must be set in .env")

        auth_url = (
            f"{_AUTH_URL}"
            f"?response_type=code"
            f"&client_id={self.app_key}"
            f"&redirect_uri={urllib.parse.quote(self.callback_url, safe='')}"
        )

        captured_url: list[str] = []
        redirect_received = threading.Event()

        def handle_route(route):
            captured_url.append(route.request.url)
            redirect_received.set()
            route.abort()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()

            # Intercept the redirect before the browser tries to load it
            page.route(f"{self.callback_url}**", handle_route)

            page.goto(auth_url)

            # --- Step 1: Username ---
            # Selectors reflect Schwab's login page as of mid-2025.
            # If login breaks, inspect the page and update these selectors.
            page.wait_for_selector("#loginIdInput", timeout=15000)
            page.fill("#loginIdInput", username)
            page.click("#btnLogin")

            # --- Step 2: Password ---
            page.wait_for_selector("#passwordInput", timeout=10000)
            page.fill("#passwordInput", password)
            page.click("#btnLogin")

            # --- Step 3: SMS code ---
            # Schwab may render the OTP input under different IDs across sessions.
            otp_selectors = ["#OTPInput", "input[name='OtpCode']", "#smscode", "input[type='tel']"]
            otp_selector = None
            for sel in otp_selectors:
                try:
                    page.wait_for_selector(sel, timeout=3000)
                    otp_selector = sel
                    break
                except Exception:
                    continue

            if not otp_selector:
                raise RuntimeError(
                    "Could not find the SMS code input. "
                    "Schwab may have updated their login page — inspect and update otp_selectors."
                )

            sms_code = input("\nSchwab sent you an SMS. Enter the code: ").strip()
            page.fill(otp_selector, sms_code)

            submit_selectors = ["#OTPSubmitBtn", "button[type='submit']", "#btnContinue", "#submit-btn"]
            for sel in submit_selectors:
                try:
                    page.click(sel, timeout=2000)
                    break
                except Exception:
                    continue

            # Wait for the redirect to be intercepted (up to 20s)
            redirect_received.wait(timeout=20)
            browser.close()

        if not captured_url:
            raise RuntimeError(
                "OAuth redirect was not captured.\n"
                "Make sure SCHWAB_CALLBACK_URL matches what is registered "
                "in the Schwab Developer Portal."
            )

        parsed = urllib.parse.urlparse(captured_url[0])
        code = urllib.parse.parse_qs(parsed.query).get("code", [None])[0]
        if not code:
            raise RuntimeError(f"No auth code found in redirect URL: {captured_url[0]}")

        r = requests.post(
            _TOKEN_URL,
            headers={
                "Authorization": f"Basic {self._basic_auth()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type":   "authorization_code",
                "code":         code,
                "redirect_uri": self.callback_url,
            },
        )
        r.raise_for_status()
        data = r.json()
        data["expires_at"] = time.time() + data["expires_in"]
        self._save_tokens(data)
        print("Authenticated. Tokens saved to schwab/tokens.json.")


if __name__ == "__main__":
    SchwabAuth().authenticate()
