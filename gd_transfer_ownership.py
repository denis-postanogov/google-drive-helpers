#!/usr/bin/env python3
"""
Recursively traverse a Google Drive folder and replace non-runner-owned files
with runner-owned copies in the same folder.

Behavior:
- Finds the email of the authenticated runner.
- Recursively traverses the given folder.
- For each non-folder, non-shortcut file:
  - if already owned by runner -> skip
  - otherwise:
      1) create a copy in the same parent folder
      2) remove the original file from that parent folder

Notes:
- This script does NOT attempt direct ownership transfer.
- This script does NOT call files.delete().
- It uses removeParents on the original file for the current folder.
- A copied file is a new Drive file, so immutable/output-only metadata such as
  Drive file ID and Drive timestamps like createdTime cannot be preserved exactly.
- The script preserves practical mutable metadata where possible.

Setup:
1. Enable Google Drive API in your Google Cloud project.
2. Create Desktop OAuth credentials and save as credentials.json.
3. Run:
       python gd_transfer_ownership.py FOLDER_ID
"""

from __future__ import annotations

import argparse
import sys
from typing import Iterator, Dict, Any, List, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/drive"]

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"


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
    about = service.about().get(fields="user(emailAddress,displayName,me)").execute()
    user = about.get("user", {})
    email = user.get("emailAddress")
    if not email:
        raise RuntimeError("Could not determine runner email from Drive API.")
    return email.lower()


def format_http_error(e: HttpError) -> str:
    status = getattr(e.resp, "status", "unknown")
    try:
        content = e.content.decode("utf-8", errors="replace")
    except Exception:
        content = str(e)
    return f"HTTP {status}: {content}"


def list_folder_children(service, folder_id: str) -> Iterator[Dict[str, Any]]:
    page_token = None

    while True:
        response = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields=(
                    "nextPageToken,"
                    "files("
                    "id,"
                    "name,"
                    "mimeType,"
                    "parents,"
                    "driveId,"
                    "webViewLink,"
                    "description,"
                    "starred,"
                    "copyRequiresWriterPermission,"
                    "writersCanShare,"
                    "properties,"
                    "appProperties,"
                    "contentHints,"
                    "createdTime,"
                    "modifiedTime,"
                    "owners(emailAddress),"
                    "shortcutDetails(targetId,targetMimeType),"
                    "capabilities(canCopy,canRemoveMyDriveParent)"
                    ")"
                ),
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


def walk_folder(
    service,
    folder_id: str,
    current_path: str = "",
) -> Iterator[Dict[str, Any]]:
    children: List[Dict[str, Any]] = sorted(
        list(list_folder_children(service, folder_id)),
        key=lambda x: (x.get("mimeType") != FOLDER_MIME, x.get("name", "").lower()),
    )

    for item in children:
        name = item["name"]
        mime_type = item["mimeType"]
        owners = item.get("owners", [])
        owner_email = owners[0].get("emailAddress").lower() if owners and owners[0].get("emailAddress") else None
        path = f"{current_path}/{name}" if current_path else name

        base = {
            "id": item["id"],
            "name": name,
            "owner": owner_email,
            "mimeType": mime_type,
            "path": path,
            "parents": item.get("parents", []),
            "driveId": item.get("driveId"),
            "webViewLink": item.get("webViewLink"),
            "description": item.get("description"),
            "starred": item.get("starred"),
            "copyRequiresWriterPermission": item.get("copyRequiresWriterPermission"),
            "writersCanShare": item.get("writersCanShare"),
            "properties": item.get("properties"),
            "appProperties": item.get("appProperties"),
            "contentHints": item.get("contentHints"),
            "createdTime": item.get("createdTime"),
            "modifiedTime": item.get("modifiedTime"),
            "capabilities": item.get("capabilities", {}),
        }

        if mime_type == FOLDER_MIME:
            yield {
                **base,
                "kind": "folder",
                "current_parent_id": folder_id,
            }
            yield from walk_folder(service, item["id"], path)
        else:
            yield {
                **base,
                "kind": "file",
                "shortcutDetails": item.get("shortcutDetails"),
                "current_parent_id": folder_id,
            }


def build_copy_body(file_entry: Dict[str, Any], destination_parent_id: str) -> Dict[str, Any]:
    """
    Build a best-effort metadata body for files.copy().

    Some metadata like createdTime / modifiedTime / ID / owners are not preserved,
    because the copy is a new Drive file and those fields are not practically
    transferable as-is.
    """
    body: Dict[str, Any] = {
        "name": file_entry["name"],
        "parents": [destination_parent_id],
    }

    for key in (
        "description",
        "starred",
        "copyRequiresWriterPermission",
        "writersCanShare",
        "properties",
        "appProperties",
        "contentHints",
    ):
        value = file_entry.get(key)
        if value is not None:
            body[key] = value

    return body


def copy_file_to_parent(service, file_entry: Dict[str, Any], destination_parent_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    file_id = file_entry["id"]
    body = build_copy_body(file_entry, destination_parent_id)

    try:
        new_file = (
            service.files()
            .copy(
                fileId=file_id,
                body=body,
                supportsAllDrives=True,
                fields="id,name,owners(emailAddress),parents,webViewLink,createdTime,modifiedTime"
            )
            .execute()
        )
        return new_file, "copied"
    except HttpError as e:
        return None, f"copy failed: {format_http_error(e)}"


def remove_original_from_parent(service, file_entry: Dict[str, Any], parent_id: str) -> Tuple[bool, str]:
    if file_entry.get("driveId"):
        return False, "shared-drive item; canRemoveMyDriveParent is not applicable here"

    if not file_entry.get("capabilities", {}).get("canRemoveMyDriveParent"):
        return False, "cannot remove original from current My Drive parent"

    try:
        (
            service.files()
            .update(
                fileId=file_entry["id"],
                removeParents=parent_id,
                supportsAllDrives=True,
                fields="id,parents"
            )
            .execute()
        )
        return True, "original removed from current parent"
    except HttpError as e:
        return False, f"removeParents failed: {format_http_error(e)}"


def process_file(service, entry: Dict[str, Any], runner_email: str) -> Dict[str, Any]:
    result = {
        "path": entry["path"],
        "file_id": entry["id"],
        "name": entry["name"],
        "mimeType": entry["mimeType"],
        "owner_before": entry.get("owner"),
        "action": None,
        "success": False,
        "details": [],
    }

    if entry["mimeType"] == SHORTCUT_MIME:
        result["action"] = "skip-shortcut"
        result["success"] = True
        result["details"].append("shortcut skipped")
        return result

    if entry.get("owner") == runner_email:
        result["action"] = "skip-owned-by-runner"
        result["success"] = True
        result["details"].append("already owned by runner")
        return result

    copied, copy_msg = copy_file_to_parent(service, entry, entry["current_parent_id"])
    result["details"].append(copy_msg)

    if not copied:
        result["action"] = "copy-and-remove-parent"
        result["success"] = False
        return result

    copied_owner = None
    copied_owners = copied.get("owners", [])
    if copied_owners:
        copied_owner = copied_owners[0].get("emailAddress")

    result["details"].append(f"new_copy_id={copied.get('id')}")
    result["details"].append(f"new_copy_owner={copied_owner}")
    if copied.get("createdTime"):
        result["details"].append(f"new_copy_createdTime={copied.get('createdTime')}")

    removed, remove_msg = remove_original_from_parent(service, entry, entry["current_parent_id"])
    result["details"].append(remove_msg)

    result["action"] = "copy-and-remove-parent"
    result["success"] = removed

    if not removed:
        result["details"].append(
            "runner-owned copy was created, but original could not be removed from the current parent"
        )

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recursively replace non-runner-owned files in a Drive folder with runner-owned copies."
    )
    parser.add_argument("folder_id", help="Google Drive folder ID")
    args = parser.parse_args()

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
    print()

    scanned = 0
    processed = 0
    changed = 0
    failed = 0
    skipped = 0

    for entry in walk_folder(service, args.folder_id):
        marker = "[DIR] " if entry["kind"] == "folder" else "[FILE]"
        print(f"{marker} {entry['path']}")
        print(f"       id={entry['id']}")
        print(f"       owner={entry.get('owner')}")
        print(f"       mimeType={entry['mimeType']}")
        if entry.get("webViewLink"):
            print(f"       url={entry['webViewLink']}")

        scanned += 1

        if entry["kind"] == "folder":
            print()
            continue

        processed += 1
        result = process_file(service=service, entry=entry, runner_email=runner_email)

        print(f"       action={result['action']}")
        for detail in result["details"]:
            print(f"       detail={detail}")

        if result["action"] in ("skip-owned-by-runner", "skip-shortcut"):
            skipped += 1
        elif result["success"]:
            changed += 1
        else:
            failed += 1

        print()

    print("Summary:")
    print(f"  scanned items:   {scanned}")
    print(f"  files processed: {processed}")
    print(f"  changed:         {changed}")
    print(f"  skipped:         {skipped}")
    print(f"  failed:          {failed}")

    if failed:
        print(
            "\nSome files were copied but the original could not be removed from the current folder."
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())