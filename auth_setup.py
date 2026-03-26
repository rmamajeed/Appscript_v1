"""
auth_setup.py — One-time OAuth2 login script for local testing.

Run this ONCE before running main.py locally:
    python auth_setup.py

It will open a browser window asking you to log in with the Gmail account
the script should read. After you approve, it saves a 'token.json' file
in this folder. main.py will use that token automatically from then on.

The token auto-refreshes, so you only need to run this script once
(unless you delete token.json or revoke access in your Google account).

Prerequisites:
1. Go to https://console.cloud.google.com/
2. Select your GCP project
3. APIs & Services > Credentials > Create Credentials > OAuth client ID
4. Application type: Desktop app
5. Download the JSON file and save it as 'credentials.json' in this folder
"""

import os
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from dotenv import load_dotenv
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run:  pip install -r requirements.txt")
    sys.exit(1)

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

CREDENTIALS_PATH = os.environ.get("OAUTH_CREDENTIALS_PATH", "credentials.json")
TOKEN_PATH       = os.environ.get("OAUTH_TOKEN_PATH", "token.json")


def main():
    if not os.path.exists(CREDENTIALS_PATH):
        print(f"\nERROR: '{CREDENTIALS_PATH}' not found.")
        print(
            "\nTo fix this:\n"
            "  1. Go to https://console.cloud.google.com/\n"
            "  2. APIs & Services > Credentials > Create Credentials > OAuth client ID\n"
            "  3. Application type: Desktop app\n"
            "  4. Download the JSON and save it as 'credentials.json' in this folder\n"
        )
        sys.exit(1)

    creds = None

    # Load existing token if it exists
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # Refresh or re-authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing existing token...")
            creds.refresh(Request())
        else:
            print("Opening browser for Google login...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)

        # Save the token for future runs
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        print(f"\nToken saved to '{TOKEN_PATH}'")

    print("\nAuthentication successful!")
    print(f"You are logged in. main.py will now use '{TOKEN_PATH}' automatically.")
    print("\nNext step:  python main.py")


if __name__ == "__main__":
    main()
