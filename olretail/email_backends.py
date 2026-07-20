"""Django email backend that sends via the Gmail API over HTTPS.

Render's free tier blocks outbound SMTP ports entirely, so a raw SMTP
backend can't reach any provider from there — see the comment in
TLoretail/settings.py. The Gmail API is a normal HTTPS POST, so it isn't
affected. Auth is OAuth2 with a long-lived refresh token instead of an SMTP
password (see .env.example for how to obtain one).
"""

import base64
import time

import requests
from django.core.mail.backends.base import BaseEmailBackend

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
REQUEST_TIMEOUT = 10  # seconds — an HTTPS request can still hang without one

# Access tokens are short-lived (~1h) but cheap to reuse across requests
# within a worker process, so cache the current one at module scope.
_token_cache = {"access_token": None, "expires_at": 0}


class GmailAPIBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        from django.conf import settings

        self.client_id = settings.GMAIL_CLIENT_ID
        self.client_secret = settings.GMAIL_CLIENT_SECRET
        self.refresh_token = settings.GMAIL_REFRESH_TOKEN

    def _get_access_token(self):
        if _token_cache["access_token"] and _token_cache["expires_at"] > time.time() + 30:
            return _token_cache["access_token"]

        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=REQUEST_TIMEOUT,
        )
        if not response.ok:
            # Google's error detail (invalid_grant, invalid_client, etc.) is
            # in the JSON body, which raise_for_status() alone discards.
            raise requests.HTTPError(
                f"{response.status_code} refreshing Gmail access token: {response.text}",
                response=response,
            )
        payload = response.json()
        _token_cache["access_token"] = payload["access_token"]
        _token_cache["expires_at"] = time.time() + payload.get("expires_in", 3600)
        return _token_cache["access_token"]

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        try:
            access_token = self._get_access_token()
        except requests.RequestException:
            if not self.fail_silently:
                raise
            return 0

        sent_count = 0
        for message in email_messages:
            raw = base64.urlsafe_b64encode(message.message().as_bytes()).decode()
            try:
                response = requests.post(
                    SEND_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"raw": raw},
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                sent_count += 1
            except requests.RequestException:
                if not self.fail_silently:
                    raise
        return sent_count
