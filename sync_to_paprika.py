#!/usr/bin/env python3
"""
Sync recipes from this repo to Paprika Recipe Manager.

Workflow:
  1. Authenticate via Paprika v1 API to get a bearer token
  2. Scan recipes/ for pending .json files  → upload to Paprika
  3. Scan recipes/delete/ for pending .json files → delete from Paprika
  4. Move processed files to recipes/synced/

Auth: v1 login endpoint (v2 login has device-check restrictions).
Upload/delete: v2 sync endpoint with gzipped multipart form data.

Delete format (recipes/delete/<name>.json):
  { "uid": "<PAPRIKA-RECIPE-UID>" }
  or include "name" for logging purposes:
  { "uid": "<PAPRIKA-RECIPE-UID>", "name": "Recipe Name" }
"""

import json
import gzip
import hashlib
import os
import sys
import uuid
import shutil
import requests
from datetime import datetime

# --- Config ---
PAPRIKA_EMAIL = os.environ.get("PAPRIKA_EMAIL", "jtwarta@gmail.com")
PAPRIKA_PASSWORD = os.environ.get("PAPRIKA_PASSWORD", "Hwlig881?")

V1_LOGIN_URL = "https://www.paprikaapp.com/api/v1/account/login/"
V2_SYNC_RECIPE_URL = "https://www.paprikaapp.com/api/v2/sync/recipe/{uid}/"

RECIPES_DIR = os.path.join(os.path.dirname(__file__), "recipes")
SYNCED_DIR = os.path.join(RECIPES_DIR, "synced")
DELETE_DIR = os.path.join(RECIPES_DIR, "delete")


def authenticate():
    """Login via v1 API, return bearer token."""
    print("Authenticating with Paprika...")
    resp = requests.post(
        V1_LOGIN_URL,
        data={"email": PAPRIKA_EMAIL, "password": PAPRIKA_PASSWORD},
        auth=(PAPRIKA_EMAIL, PAPRIKA_PASSWORD),
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    if "result" not in result or "token" not in result["result"]:
        print(f"Auth failed: {result}")
        sys.exit(1)
    print("Authenticated successfully.")
    return result["result"]["token"]


def generate_uid():
    """Generate a UUID in Paprika's expected format."""
    return str(uuid.uuid4()).upper()


def compute_hash(recipe_dict):
    """Compute SHA-256 hash of recipe fields (excluding hash itself)."""
    fields = dict(recipe_dict)
    fields.pop("hash", None)
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True).encode("utf-8")
    ).hexdigest()


def build_recipe(data):
    """
    Take a simplified recipe dict from a JSON file and produce
    the full Paprika recipe payload with all required fields.
    """
    uid = data.get("uid", generate_uid())
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    recipe = {
        "uid": uid,
        "name": data.get("name", "Untitled Recipe"),
        "ingredients": data.get("ingredients", ""),
        "directions": data.get("directions", ""),
        "notes": data.get("notes", ""),
        "nutritional_info": data.get("nutritional_info", ""),
        "servings": data.get("servings", ""),
        "prep_time": data.get("prep_time", ""),
        "cook_time": data.get("cook_time", ""),
        "total_time": data.get("total_time", ""),
        "difficulty": data.get("difficulty", ""),
        "source": data.get("source", ""),
        "source_url": data.get("source_url", ""),
        "rating": data.get("rating", 0),
        "categories": data.get("categories", []),
        "image_url": data.get("image_url", ""),
        "photo": data.get("photo", ""),
        "photo_hash": data.get("photo_hash", ""),
        "photo_large": data.get("photo_large", None),
        "photo_url": data.get("photo_url", None),
        "description": data.get("description", ""),
        "scale": data.get("scale", None),
        "created": data.get("created", now),
        "deleted": False,
        "in_trash": False,
        "is_pinned": data.get("is_pinned", False),
        "on_favorites": data.get("on_favorites", False),
        "on_grocery_list": data.get("on_grocery_list", None),
    }

    recipe["hash"] = compute_hash(recipe)
    return recipe


def upload_recipe(token, recipe):
    """Upload a single recipe to Paprika via v2 API."""
    url = V2_SYNC_RECIPE_URL.format(uid=recipe["uid"])
    payload = gzip.compress(json.dumps(recipe).encode("utf-8"))

    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        files={"data": payload},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    if "error" in result:
        print(f"  ERROR from Paprika: {result['error']}")
        return False

    print(f"  Uploaded successfully: {recipe['name']} ({recipe['uid']})")
    return True


def delete_recipe(token, uid, name="(unnamed)"):
    """
    Delete a recipe from Paprika by uploading a tombstone payload
    (deleted=True, in_trash=True) via the v2 sync endpoint.
    The same endpoint used for uploads handles deletes when these flags are set.
    """
    url = V2_SYNC_RECIPE_URL.format(uid=uid)

    tombstone = {
        "uid": uid,
        "name": name,
        "deleted": True,
        "in_trash": True,
        "ingredients": "",
        "directions": "",
        "notes": "",
        "nutritional_info": "",
        "servings": "",
        "prep_time": "",
        "cook_time": "",
        "total_time": "",
        "difficulty": "",
        "source": "",
        "source_url": "",
        "rating": 0,
        "categories": [],
        "image_url": "",
        "photo": "",
        "photo_hash": "",
        "photo_large": None,
        "photo_url": None,
        "description": "",
        "scale": None,
        "is_pinned": False,
        "on_favorites": False,
        "on_grocery_list": None,
    }
    tombstone["hash"] = compute_hash(tombstone)

    payload = gzip.compress(json.dumps(tombstone).encode("utf-8"))
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        files={"data": payload},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    if "error" in result:
        print(f"  ERROR from Paprika: {result['error']}")
        return False

    print(f"  Deleted successfully: {name} ({uid})")
    return True


def main():
    # Find pending recipe files
    if not os.path.isdir(RECIPES_DIR):
        print(f"No recipes directory found at {RECIPES_DIR}")
        sys.exit(0)

    pending = [
        f for f in os.listdir(RECIPES_DIR)
        if f.endswith(".json") and os.path.isfile(os.path.join(RECIPES_DIR, f))
    ]

    token = None  # Authenticate lazily; reuse across upload + delete

    if not pending:
        print("No pending recipes to sync.")
    else:
        print(f"Found {len(pending)} recipe(s) to sync.")

        # Authenticate
        token = authenticate()

        # Ensure synced directory exists
        os.makedirs(SYNCED_DIR, exist_ok=True)

        # Process each recipe
        success_count = 0
        for filename in pending:
            filepath = os.path.join(RECIPES_DIR, filename)
            print(f"\nProcessing: {filename}")

            try:
                with open(filepath, "r") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"  SKIP - failed to read: {e}")
                continue

            recipe = build_recipe(data)

            if upload_recipe(token, recipe):
                # Move to synced folder with timestamp prefix
                ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                synced_name = f"{ts}_{filename}"
                shutil.move(filepath, os.path.join(SYNCED_DIR, synced_name))
                print(f"  Moved to synced/{synced_name}")
                success_count += 1

        print(f"\nDone. {success_count}/{len(pending)} recipes synced.")

    # --- Process deletions ---
    if not os.path.isdir(DELETE_DIR):
        return  # No delete folder, nothing to do

    to_delete = [
        f for f in os.listdir(DELETE_DIR)
        if f.endswith(".json") and os.path.isfile(os.path.join(DELETE_DIR, f))
    ]

    if not to_delete:
        print("No pending deletions.")
        return

    print(f"\nFound {len(to_delete)} recipe(s) to delete.")

    if not token:
        token = authenticate()

    delete_synced_dir = os.path.join(SYNCED_DIR, "deleted")
    os.makedirs(delete_synced_dir, exist_ok=True)

    delete_count = 0
    for filename in to_delete:
        filepath = os.path.join(DELETE_DIR, filename)
        print(f"\nDeleting: {filename}")

        try:
            with open(filepath, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"  SKIP - failed to read: {e}")
            continue

        uid = data.get("uid")
        if not uid:
            print(f"  SKIP - no 'uid' field in {filename}")
            continue

        name = data.get("name", uid)

        if delete_recipe(token, uid, name):
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            synced_name = f"{ts}_{filename}"
            shutil.move(filepath, os.path.join(delete_synced_dir, synced_name))
            print(f"  Moved to synced/deleted/{synced_name}")
            delete_count += 1

    print(f"\nDone. {delete_count}/{len(to_delete)} recipes deleted.")


if __name__ == "__main__":
    main()
