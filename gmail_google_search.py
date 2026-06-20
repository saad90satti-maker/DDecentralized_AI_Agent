import os
import base64
import json
import webbrowser
from urllib.parse import quote_plus
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


class _CallbackHandler(BaseHTTPRequestHandler):
    code = None

    def do_GET(self):
        if self.path.startswith("/?code="):
            _CallbackHandler.code = self.path.split("=", 1)[1]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"AUTH_SUCCESSFUL")
        else:
            self.send_response(302)
            self.send_header("Location", "https://mail.google.com")
            self.end_headers()

    def log_message(self, format, *args):
        pass


class GoogleMailSearch:
    def __init__(self, creds_json_path: str = "credentials.json", token_path: str = "token.json"):
        self.creds_json_path = creds_json_path
        self.token_path = token_path
        self.service = None
        self.profile_email = None
        self.warmup_query = None

    def process_auth(self):
        if not os.path.exists(self.creds_json_path):
            raise FileNotFoundError(f"Missing credentials file: {self.creds_json_path}")

        creds = None
        if os.path.exists(self.token_path):
            try:
                creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
            except Exception:
                creds = None

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_token(creds)
                return creds
            except Exception:
                creds = None

        flow = InstalledAppFlow.from_client_secrets_file(self.creds_json_path, SCOPES)
        creds = flow.run_local_server(
            port=0,
            authorization_prompt_template="file://__auth_template__.html",
            open_browser=False,
            success_message="AUTH_SUCCESSFUL_TEMPLATE",
        )
        self._save_token(creds)
        return creds

    def _save_token(self, creds):
        try:
            token_data = json.loads(creds.to_json())
            token_data.pop("client_config", None)
            if "client_info" in token_data:
                token_data["client_info"].pop("client_secret", None)
            with open(self.token_path, "w", encoding="utf-8") as f:
                json.dump(token_data, f, indent=2)
        except Exception:
            with open(self.token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())

    def build_service(self):
        creds = self.process_auth()
        self.service = build("gmail", "v1", credentials=creds)

    def fetch_profile(self):
        profile = self.service.users().getProfile(userId="me").execute()
        self.profile_email = profile.get("emailAddress")

    def warmup(self):
        if self.service is None or self.profile_email is None:
            self.build_service()
        query = f"from:{self.profile_email}"
        result = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=1)
            .execute()
        )
        if result.get("messages"):
            msg_id = result["messages"][0]["id"]
            self.service.users().messages().get(userId="me", id=msg_id, format="minimal").execute()
        self.warmup_query = query
        return self.warmup_query

    def search_emails(self, query: str, max_results: int = 20):
        if self.service is None:
            self.build_service()
        if self.profile_email is None:
            self.fetch_profile()

        q = quote_plus(query)
        url = (
            "https://mail.google.com/mail/u/0/#search/"
            f"{q}"
            f"?query={q}&pik={max_results}"
        )
        webbrowser.open(url)
        return {"query": query, "max_results": max_results, "opened_url": url}

    def search_via_api(self, query: str, max_results: int = 20):
        if self.service is None:
            self.build_service()
        if self.profile_email is None:
            self.fetch_profile()

        response = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = response.get("messages", [])
        results = []
        for msg in messages:
            detail = (
                self.service.users()
                .messages()
                .get(userId="me", id=msg["id"], format="metadata", metadataHeaders=["Subject", "From", "Date"])
                .execute()
            )
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            results.append(
                {
                    "id": msg["id"],
                    "subject": headers.get("Subject"),
                    "from": headers.get("From"),
                    "date": headers.get("Date"),
                }
            )
        return results


def _fetch_session_email(creds_json_path: str, token_path: str) -> str:
    session = GoogleMailSearch(creds_json_path=creds_json_path, token_path=token_path)
    session.build_service()
    session.fetch_profile()
    session.warmup()
    session.search_emails(session.warmup_query, max_results=1)
    return session.profile_email


def fetch_session_email_from_blocked_flow(creds_json_path: str, token_path: str = "token_google.json") -> str:
    if not os.path.exists(creds_json_path):
        print(f"[ERROR] Missing Google Cloud credentials file: {creds_json_path}")
        return ""

    try:
        session = GoogleMailSearch(creds_json_path=creds_json_path, token_path=token_path)
        session.build_service()
        session.fetch_profile()
        session.warmup()
        session.search_emails(session.warmup_query, max_results=1)
        return session.profile_email or ""
    except Exception as exc:
        print(f"[ERROR] Failed to fetch Google session email: {exc}")
        return ""


if __name__ == "__main__":
    creds_path = "credentials.json"
    token_path = "token.json"

    if not os.path.exists(creds_path):
        raise FileNotFoundError(f"Missing credentials file: {creds_path}")

    mail_search = GoogleMailSearch(creds_json_path=creds_path, token_path=token_path)
    mail_search.build_service()
    mail_search.fetch_profile()
    mail_search.warmup()
    print(f"Authenticated as: {mail_search.profile_email}")
    query = input("Enter mail search query: ").strip()
    if query:
        mail_search.search_emails(query, max_results=20)
