import hashlib
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# 1. Load environment variables from .env
load_dotenv()

ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")
ACCESS_KEY = os.getenv("R2_ACCESS_KEY_ID")
SECRET_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "retro-saves")
SAVE_DIR = Path(os.getenv("SAVE_DIR", ""))

# 2. Configure logging to both console and sync.log (ignored by Git)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("sync.log"),
        logging.StreamHandler(sys.stdout),
    ],
)


def get_r2_client():
    """Initialize and return an S3-compatible boto3 client for Cloudflare R2."""
    if not all([ENDPOINT_URL, ACCESS_KEY, SECRET_KEY, SAVE_DIR]):
        logging.error("Missing required variables in .env file.")
        sys.exit(1)

    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT_URL,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name="auto",
    )


def sha256_file(filepath: Path) -> str:
    """Compute the SHA-256 hash of a local file in memory."""
    hasher = hashlib.sha256()
    with filepath.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def backup_local_file(filepath: Path):
    """Save a timestamped backup in .backups/ before overwriting a local save."""
    if not filepath.exists():
        return
    backup_dir = SAVE_DIR / ".backups"
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{filepath.stem}_{timestamp}{filepath.suffix}"
    shutil.copy2(filepath, backup_path)
    logging.info(f"Backed up local save -> {backup_path.name}")


def push_saves(s3):
    """Upload new or modified .srm files from SAVE_DIR to Cloudflare R2."""
    if not SAVE_DIR.exists():
        logging.error(f"SAVE_DIR does not exist: {SAVE_DIR}")
        return

    srm_files = list(SAVE_DIR.glob("*.srm"))
    if not srm_files:
        logging.info("No local .srm files found to push.")
        return

    for filepath in srm_files:
        local_hash = sha256_file(filepath)
        key = filepath.name

        # Check if cloud already has an identical SHA-256 hash
        try:
            head = s3.head_object(Bucket=BUCKET_NAME, Key=key)
            remote_hash = head.get("Metadata", {}).get("sha256", "")
            if remote_hash == local_hash:
                logging.info(f"SKIP (unchanged): {key}")
                continue
        except ClientError as e:
            if e.response["Error"]["Code"] != "404":
                logging.error(f"Error checking {key} on R2: {e}")
                continue

        # Upload file along with its SHA-256 hash in custom metadata
        s3.upload_file(
            str(filepath),
            BUCKET_NAME,
            key,
            ExtraArgs={"Metadata": {"sha256": local_hash}},
        )
        logging.info(f"PUSHED -> R2: {key} (sha256: {local_hash[:8]}...)")


def pull_saves(s3):
    """Download newer or missing .srm files from Cloudflare R2 to SAVE_DIR."""
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    response = s3.list_objects_v2(Bucket=BUCKET_NAME)

    if "Contents" not in response:
        logging.info("Cloud bucket is empty. Nothing to pull.")
        return

    for obj in response["Contents"]:
        key = obj["Key"]
        if not key.endswith(".srm"):
            continue

        local_path = SAVE_DIR / key
        head = s3.head_object(Bucket=BUCKET_NAME, Key=key)
        remote_hash = head.get("Metadata", {}).get("sha256", "")

        if local_path.exists():
            local_hash = sha256_file(local_path)
            if remote_hash and local_hash == remote_hash:
                logging.info(f"SKIP (up to date): {key}")
                continue

            # Compare timestamps so an older cloud file never overwrites newer local progress
            remote_mtime = obj["LastModified"].timestamp()
            local_mtime = local_path.stat().st_mtime
            if local_mtime >= remote_mtime:
                logging.info(f"SKIP (local save is newer): {key}")
                continue

            backup_local_file(local_path)

        s3.download_file(BUCKET_NAME, key, str(local_path))
        logging.info(f"PULLED <- R2: {key}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("push", "pull"):
        print("Usage: python sync.py [push|pull]")
        sys.exit(1)

    client = get_r2_client()
    command = sys.argv[1]

    if command == "push":
        push_saves(client)
    elif command == "pull":
        pull_saves(client)