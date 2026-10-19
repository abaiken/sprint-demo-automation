from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


def load_google_credentials(
    *,
    scopes: list[str],
    credentials_path: str,
    token_path: str,
) -> Credentials:
    creds = None
    token_file = Path(token_path)
    credentials_file = Path(credentials_path)

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), scopes)

    # A previously saved token may still be "valid" but lack newly requested scopes.
    # In that case we must run the installed-app flow again because a refresh alone
    # will not expand the granted permissions.
    if creds and not creds.has_scopes(scopes):
        creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                creds = None

        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_file), scopes
            )
            creds = flow.run_local_server(port=0)

        token_file.write_text(creds.to_json())

    return creds
