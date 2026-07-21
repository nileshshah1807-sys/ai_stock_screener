#!/usr/bin/env python3
"""
Generate a Gmail API refresh token for Railway.

Run this locally:
    python tools/generate_gmail_refresh_token.py

It opens your browser, asks Google for the gmail.send permission, and prints the
environment variables to copy into Railway. The script does not save secrets.
"""

import getpass
import http.server
import secrets
import socketserver
import urllib.parse
import webbrowser

import requests


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/gmail.send"
REDIRECT_HOST = "127.0.0.1"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}/oauth2callback"


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    server_version = "GmailOAuthCallback/1.0"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        self.server.auth_code = params.get("code", [None])[0]
        self.server.auth_error = params.get("error", [None])[0]

        if parsed.path != "/oauth2callback":
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>Gmail authorization complete.</h2>"
            b"<p>You can close this tab and return to Codex/PowerShell.</p></body></html>"
        )

    def log_message(self, format, *args):
        return


def main():
    print("Create a Google OAuth client first, then paste its values here.")
    client_id = input("GMAIL_CLIENT_ID: ").strip()
    client_secret = getpass.getpass("GMAIL_CLIENT_SECRET: ").strip()

    if not client_id or not client_secret:
        raise SystemExit("Client ID and client secret are required.")

    state = secrets.token_urlsafe(24)
    auth_params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"

    with socketserver.TCPServer((REDIRECT_HOST, REDIRECT_PORT), OAuthCallbackHandler) as server:
        server.auth_code = None
        server.auth_error = None
        print(f"\nOpening browser for Google consent:\n{auth_url}\n")
        webbrowser.open(auth_url)
        print("Waiting for Google callback...")
        server.handle_request()

        if server.auth_error:
            raise SystemExit(f"Google returned OAuth error: {server.auth_error}")
        if not server.auth_code:
            raise SystemExit("No authorization code received.")

        token_response = requests.post(
            TOKEN_URL,
            data={
                "code": server.auth_code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=30,
        )

    if token_response.status_code >= 300:
        raise SystemExit(f"Token exchange failed: HTTP {token_response.status_code} {token_response.text}")

    token_data = token_response.json()
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise SystemExit(
            "Google did not return a refresh_token. Re-run this helper and make sure "
            "you approve the consent screen. If needed, revoke the app from your "
            "Google Account security page and try again."
        )

    print("\nCopy these variables into Railway:")
    print("EMAIL_DELIVERY_METHOD=GMAIL_API")
    print(f"GMAIL_CLIENT_ID={client_id}")
    print(f"GMAIL_CLIENT_SECRET={client_secret}")
    print(f"GMAIL_REFRESH_TOKEN={refresh_token}")
    print(f"EMAIL_SENDER=<the Gmail account you just authorized>")
    print("EMAIL_ENABLED=True")


if __name__ == "__main__":
    main()
