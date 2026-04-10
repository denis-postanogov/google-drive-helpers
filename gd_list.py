#!/usr/bin/env python3
"""
Recursively list files in a Google Drive folder.

Setup:
1. In Google Cloud Console, enable the Google Drive API.
2. Create OAuth client credentials for a Desktop app.
3. Download the OAuth client file as "credentials.json" and place it next to this script.
4. Run:
       python drive_list_recursive.py <FOLDER_ID>

On first run, a browser window will open for authorization.
A token will be stored in token.json for later runs.
"""

from __future__ import annotations

import argparse
import sys
from typing import Iterator, Dict, Any, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Read-only access is enough for listing files.
SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"


def get_credentials() -> Credentials:
    """
    Load cached OAuth token if present; otherwise run local browser auth flow.
    """
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


def list_folder_children(service, folder_id: str) -> Iterator[Dict[str, Any]]:
    """
    Yield direct children of a folder, handling pagination.
    Includes support flags for shared drives.
    """
    page_token = None

    while True:
        response = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, parents, webViewLink, owners(emailAddress), shortcutDetails)",
                pageSize=1000,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                pageToken=page_token,
            )
            .execute()
        )

        for item in response.get("files", []):
            yield item

        page_token = response.get("nextPageToken")
        if not page_token:
            break


def resolve_shortcut_target(item: Dict[str, Any]) -> Optional[str]:
    """
    Return target file ID for a Drive shortcut, if present.
    """
    details = item.get("shortcutDetails") or {}
    return details.get("targetId")


def walk_folder(
    service,
    folder_id: str,
    current_path: str = "",
) -> Iterator[Dict[str, Any]]:
    """
    Recursively walk a Drive folder tree.

    Yields dicts with:
      - id
      - name
      - mimeType
      - path
      - webViewLink
      - kind: "folder" or "file"
    """
    children: List[Dict[str, Any]] = sorted(
        list(list_folder_children(service, folder_id)),
        key=lambda x: (x.get("mimeType") != FOLDER_MIME, x.get("name", "").lower()),
    )

    for item in children:
        name = item["name"]
        mime_type = item["mimeType"]
        owners = item.get("owners", [])
        owner_email = None
        if owners:
            owner_email = owners[0].get("emailAddress")
        path = f"{current_path}/{name}" if current_path else name

        if mime_type == FOLDER_MIME:
            yield {
                "id": item["id"],
                "name": name,
                "owner": owner_email,
                "mimeType": mime_type,
                "path": path,
                "webViewLink": item.get("webViewLink"),
                "kind": "folder",
            }
            yield from walk_folder(service, item["id"], path)
        else:
            yield {
                "id": item["id"],
                "name": name,
                "owner": owner_email,
                "mimeType": mime_type,
                "path": path,
                "webViewLink": item.get("webViewLink"),
                "kind": "file",
            }


def main() -> int:
    parser = argparse.ArgumentParser(description="Recursively list files in a Google Drive folder.")
    parser.add_argument("folder_id", help="Google Drive folder ID")
    args = parser.parse_args()

    try:
        service = build_drive_service()
    except FileNotFoundError as e:
        print(f"Missing file: {e}", file=sys.stderr)
        print("Make sure credentials.json is present next to the script.", file=sys.stderr)
        return 2

    print("Listing recursively:\n")
    count = 0

    for entry in walk_folder(service, args.folder_id):
        count += 1
        marker = "[DIR] " if entry["kind"] == "folder" else "[FILE]"
        print(f"{marker} {entry['path']}")
        print(f"       id={entry['id']}")
        print(f"       owner={entry['owner']}")
        print(f"       mimeType={entry['mimeType']}")
        if entry.get("webViewLink"):
            print(f"       url={entry['webViewLink']}")

    print(f"\nTotal items: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
