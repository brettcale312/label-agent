"""
ebay_utils/auth.py
------------------
Handles eBay OAuth token retrieval and caching for API access.
Now uses the unified logging system (utils.logger).
"""

import os
import requests
import base64
import time
from dotenv import load_dotenv
from utils.logger import get_logger

# Initialize unified logger
logger = get_logger("ebay_auth")

# Load environment variables
load_dotenv()

# Environment variables
EBAY_APP_ID = os.getenv("EBAY_APP_ID") or os.getenv("EBAY_CLIENT_ID")
EBAY_CERT_ID = os.getenv("EBAY_CERT_ID") or os.getenv("EBAY_CLIENT_SECRET")
EBAY_REFRESH_TOKEN = os.getenv("EBAY_REFRESH_TOKEN")
EBAY_ENV = os.getenv("EBAY_ENV", "PRODUCTION").upper()

TOKEN_CACHE = {"access_token": None, "expires_at": 0}


def _get_auth_header() -> str:
    """Return base64 encoded client credentials for eBay API auth."""
    creds = f"{EBAY_APP_ID}:{EBAY_CERT_ID}".encode("utf-8")
    return base64.b64encode(creds).decode("utf-8")


def get_ebay_access_token() -> str:
    """
    Retrieve and cache a valid eBay access token using the refresh token.
    """
    if not EBAY_APP_ID or not EBAY_CERT_ID or not EBAY_REFRESH_TOKEN:
        logger.error("Missing required eBay API credentials (check .env file).")
        raise EnvironmentError("Missing eBay credentials")

    # Return cached token if still valid
    if TOKEN_CACHE["access_token"] and time.time() < TOKEN_CACHE["expires_at"]:
        return TOKEN_CACHE["access_token"]

    token_url = (
        "https://api.ebay.com/identity/v1/oauth2/token"
        if EBAY_ENV == "PRODUCTION"
        else "https://api.sandbox.ebay.com/identity/v1/oauth2/token"
    )

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {_get_auth_header()}",
    }

    data = {
        "grant_type": "refresh_token",
        "refresh_token": EBAY_REFRESH_TOKEN,
        "scope": "https://api.ebay.com/oauth/api_scope",
    }

    try:
        response = requests.post(token_url, headers=headers, data=data, timeout=10)
        if response.status_code != 200:
            msg = f"eBay token request failed: {response.status_code} - {response.text}"
            logger.error(msg)
            raise ConnectionError(msg)

        token_data = response.json()
        TOKEN_CACHE["access_token"] = token_data["access_token"]
        TOKEN_CACHE["expires_at"] = time.time() + token_data.get("expires_in", 7200) - 60

        logger.info("Successfully obtained new eBay access token.")
        return TOKEN_CACHE["access_token"]

    except requests.exceptions.RequestException as e:
        logger.error(f"eBay token request error: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during eBay token retrieval: {e}")
        raise
