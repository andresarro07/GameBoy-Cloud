import os
import sys
import shutil
import hashlib
from pathlib import Path
from datetime import datetime, timezone
import boto3
from botocore.exceptions import ClientError, BotoCoreError
from dotenv import load_dotenv

load_dotenv()

R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "retro-saves")
SAVES_DIR = Path(os.getenv("SAVES_DIR", "./saves")).expanduser().resolve()
MAX_LOCAL_BACKUPS = 5


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def backup_local_file(local_path: Path):
    """Copy existing local .srm to saves/backups/ and keep the newest 5."""
    if not local_path.exists() or local_path.stat().st_size == 0:
        return

    backup_dir = local_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{local_path.stem}_{timestamp}{local_path.suffix}"
    shutil.copy2(local_path, backup_dir / backup_name)

    # Prune older backups for this specific ROM
    existing = sorted(
        backup_dir.glob(f"{local_path.stem}_*{local_path.suffix}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old_file in existing[MAX_LOCAL_BACKUPS:]:
        old_file.unlink(missing_ok=True)


def backup_r2_object(s3, key: str):
    """Server-side copy of existing R2 save into backups/ prefix before overwriting."""
    try:
        s3.head_object(Bucket=R2_BUCKET_NAME, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return  # Nothing in R2 yet to back up
        raise

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stem, ext = os.path.splitext(os.path.basename(key))
    backup_key = f"backups/{stem}_{timestamp}{ext}"

    s3.copy_object(
        Bucket=R2_BUCKET_NAME,
        CopySource={"Bucket": R2_BUCKET_NAME, "Key": key},
        Key=backup_key,
    )
    print(f"[BACKUP] Archived previous cloud save -> {backup_key}")


def pull_saves(s3, target_stem: str | None = None):
    """Download .srm saves from R2 if their SHA-256 differs from local."""
    SAVES_DIR.mkdir(parents=True, exist_ok=True)
    paginator = s3.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=R2_BUCKET_NAME):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            # Ignore backups/ prefix and non-.srm files
            if key.startswith("backups/") or not key.endswith(".srm"):
                continue
            if target_stem and Path(key).stem != target_stem:
                continue

            local_path = SAVES_DIR / os.path.basename(key)
            response = s3.get_object(Bucket=R2_BUCKET_NAME, Key=key)
            remote_data = response["Body"].read()

            if local_path.exists():
                if sha256_file(local_path) == sha256_bytes(remote_data):
                    print(f"[SKIP] {key} is already up to date locally.")
                    continue
                backup_local_file(local_path)

            with open(local_path, "wb") as f:
                f.write(remote_data)
            print(f"[PULL] Downloaded {key} -> {local_path}")


def push_saves(s3, target_stem: str | None = None):
    """Upload local .srm saves to R2, archiving the existing R2 object first."""
    if not SAVES_DIR.exists():
        print(f"[WARN] Saves directory not found: {SAVES_DIR}")
        return

    for local_path in SAVES_DIR.glob("*.srm"):
        if target_stem and local_path.stem != target_stem:
            continue
        if local_path.stat().st_size == 0:
            print(f"[WARN] Skipping empty save file: {local_path.name}")
            continue

        key = local_path.name
        local_hash = sha256_file(local_path)

        # Check if remote file already matches local SHA-256
        try:
            resp = s3.get_object(Bucket=R2_BUCKET_NAME, Key=key)
            remote_hash = sha256_bytes(resp["Body"].read())
            if local_hash == remote_hash:
                print(f"[SKIP] {key} matches cloud copy; no upload needed.")
                continue
        except ClientError as e:
            if e.response["Error"]["Code"] != "404":
                raise

        # Archive existing R2 save into backups/ before overwriting
        backup_r2_object(s3, key)

        s3.upload_file(str(local_path), R2_BUCKET_NAME, key)
        print(f"[PUSH] Uploaded {local_path.name} -> s3://{R2_BUCKET_NAME}/{key}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("pull", "push"):
        print("Usage: python sync.py <pull|push> [optional_rom_stem]")
        sys.exit(1)

    mode = sys.argv[1]
    target_stem = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        s3 = get_s3_client()
        if mode == "pull":
            pull_saves(s3, target_stem)
        else:
            push_saves(s3, target_stem)
    except (ClientError, BotoCoreError, Exception) as e:
        print(f"[ERROR] R2 sync ({mode}) failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()