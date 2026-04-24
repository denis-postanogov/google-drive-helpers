Here’s a clean, concise, and practical README you can drop in as-is:

---

# Google Drive Helpers

Apache 2.0 License
Free to copy, modify and use.

© Denis Postanogov, with help of ChatGPT, 2026

---

## Description

A small collection of Python scripts for working with Google Drive via API.

Currently includes:

* **`gd_list.py`** — recursively list files in a Google Drive folder
* **`gd_take_ownership.py`** — replace files in a Google Drive folder with copies owned by you (workaround for ownership transfer limitations)
* **`gd_clean_mydrive_root.py`** - move files located in My Drive root folder to trash

These scripts are designed to be simple, local, and require no backend or deployment.

---

## Prerequisites

### Python

* Python **3.9+**

Install dependencies:

```bash
pip install -r requirements.txt
```

---

### Google API Access (one-time setup)

Google requires OAuth credentials even for local scripts.

1. Go to: [https://console.cloud.google.com/](https://console.cloud.google.com/)
2. Create a **Project**
3. Enable **Google Drive API**
4. Go to **APIs & Services → Credentials**
5. Click **Create Credentials → OAuth client ID**
6. Choose **Desktop app**
7. Download file and save as:

```
credentials.json
```

Place it in the project root.

---

### Add Users

1. Go to <https://console.cloud.google.com/apis/credentials/consent>
2. Open **Audience** tab
3. Click **Add users**
4. Enter user email(s) to enable them running the script.

## First Run

When running any script for the first time:

* Browser will open
* You log in and grant access
* `token.json` will be created (cached credentials)

---

## Tools

---

### 1. List Files (Recursive)

```bash
python gd_list.py FOLDER_ID
```

Prints:

* full folder tree
* file IDs
* owners
* metadata

---

### 2. Replace Files with Runner-Owned Copies

```bash
python gd_transfer_ownership.py FOLDER_ID
```

#### What it does

For every file in the folder (recursively):

* If already owned by you → **skip**
* Otherwise:

  1. Create a copy owned by you
  2. Remove original file from the folder

Result:

* Folder ends up containing only **your-owned copies**
* Original files remain in Drive (owned by original owners)

---

## Important Notes

### Ownership transfer

Google Drive **does NOT allow direct ownership transfer** in many cases (especially personal accounts without consent).

This tool uses a workaround:

> copy file → remove original from folder

---

### Metadata limitations

Copied files:

* get a **new file ID**
* get **new timestamps** (`createdTime`, etc.)

Some metadata is preserved where possible, but not everything can be copied exactly.

---

### Permissions

* You must have:

  * access to read files
  * permission to copy files
  * permission to modify the folder (to remove parents)

---

### Shared Drives

Behavior may differ for Shared Drives:

* ownership model is different
* some operations may be skipped

---

## Example

```bash
python gd_transfer_ownership.py 1AbCDeFgHiJkLmNoP
```

---

## Security

* Credentials are stored locally in:

  * `credentials.json`
  * `token.json`
* Do **not** commit them to GitHub

Add to `.gitignore`:

```
credentials.json
token.json
```

---

## License

Apache 2.0

---

## Contributing

PRs and improvements are welcome 👍

