#!/usr/bin/env python3
"""
Trash all files that:
- are owned by the authenticated runner
- are located directly in My Drive root
- have My Drive root as their only parent

Usage:
    python gd_remove_root_owned_files.py

Setup:
1. Put credentials.json next to this script.
2. On first run, browser auth will open.
3. token.json will be created and reused later.
"""

from __future__ import annotations

import sys
from typing import Optional, Dict, Any, Iterator

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/drive"]


def get_credentials() -> Credentials:
    creds: Optional[Credentials] = None

    try:
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    except FileNotFoundError:
        creds = None

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        with open("token.json", "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return creds


def build_drive_service():
    creds = get_credentials()
    return build("drive", "v3", credentials=creds)


def get_runner_email(service) -> str:
    about = service.about().get(fields="user(emailAddress)").execute()
    email = about.get("user", {}).get("emailAddress")
    if not email:
        raise RuntimeError("Could not determine runner email.")
    return email.lower()


def list_owned_files_in_root(service) -> Iterator[Dict[str, Any]]:
    # Retrieve ID of 'My Drive' root folder
    root = service.files().get(
        fileId="root",
        fields="id"
    ).execute()

    root_id = root["id"]

    print(f"Root folder ID = '{root_id}'")

    """
    List items in My Drive root that are owned by the runner and not already trashed.

    We query only for direct children of root, then filter in Python:
    - ownedByMe must be True
    - parents must be exactly ["root"]
    """
    page_token = None

    while True:
        response = (
            service.files()
            .list(
                q="'root' in parents and trashed = false",
                fields=(
                    "nextPageToken,"
                    "files("
                    "id,"
                    "name,"
                    "mimeType,"
                    "parents,"
                    "ownedByMe,"
                    "trashed,"
                    "webViewLink,"
                    "capabilities(canTrash)"
                    ")"
                ),
                pageSize=1000,
                spaces="drive",
                includeItemsFromAllDrives=False,
                supportsAllDrives=False,
                pageToken=page_token,
            )
            .execute()
        )

        for item in response.get("files", []):
            parents = item.get("parents", [])
            if item.get("ownedByMe") and len(parents) == 1 and parents[0] == root_id:
                yield item
            yield item

        page_token = response.get("nextPageToken")
        if not page_token:
            break

def trash_file(service, file_id: str) -> None:
    service.files().update(
        fileId=file_id,
        body={"trashed": True},
        fields="id,trashed",
        supportsAllDrives=False,
    ).execute()


def format_http_error(e: HttpError) -> str:
    status = getattr(e.resp, "status", "unknown")
    try:
        content = e.content.decode("utf-8", errors="replace")
    except Exception:
        content = str(e)
    return f"HTTP {status}: {content}"


def main() -> int:
    try:
        service = build_drive_service()
        runner_email = get_runner_email(service)
    except FileNotFoundError as e:
        print(f"Missing file: {e}", file=sys.stderr)
        print("Make sure credentials.json is present next to the script.", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Initialization failed: {e}", file=sys.stderr)
        return 2

    print(f"Runner: {runner_email}")
    print("Scanning My Drive root for runner-owned files with root as the only parent...")
    print()

    found = 0
    trashed = 0
    failed = 0

    for item in list_owned_files_in_root(service):
        found += 1
        print(f"[FILE] {item['name']}")
        print(f"       id={item['id']}")
        print(f"       mimeType={item.get('mimeType')}")
        print(f"       parents={item.get('parents')}")
        if item.get("webViewLink"):
            print(f"       url={item['webViewLink']}")

        if not item.get("capabilities", {}).get("canTrash", False):
            failed += 1
            print("       action=skip")
            print("       detail=cannot trash this file")
            print()
            continue

        try:
            trash_file(service, item["id"])
            trashed += 1
            print("       action=trashed")
        except HttpError as e:
            failed += 1
            print("       action=failed")
            print(f"       detail={format_http_error(e)}")

        print()

    print("Summary:")
    print(f"  found:   {found}")
    print(f"  trashed: {trashed}")
    print(f"  failed:  {failed}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
