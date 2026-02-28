"""
upload_blog_images.py — Upload eyecatch images to Supabase Storage
and assign them to blog posts.

Usage:
  python3 scripts/upload_blog_images.py --image-dir ~/Desktop/blog
"""

import os
import sys
import random
from pathlib import Path
from supabase import create_client

# Load env from lp-app/.env.local
env_path = Path(__file__).resolve().parent.parent / "lp-app" / ".env.local"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
BUCKET_NAME = "blog-images"

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY not set")
    sys.exit(1)

client = create_client(SUPABASE_URL, SUPABASE_KEY)


def ensure_bucket():
    """Create storage bucket if it doesn't exist."""
    try:
        client.storage.get_bucket(BUCKET_NAME)
        print(f"Bucket '{BUCKET_NAME}' already exists")
    except Exception:
        try:
            client.storage.create_bucket(
                BUCKET_NAME,
                options={
                    "public": True,
                    "file_size_limit": 10 * 1024 * 1024,
                    "allowed_mime_types": ["image/jpeg", "image/png", "image/webp"],
                },
            )
            print(f"Created bucket '{BUCKET_NAME}'")
        except Exception as e:
            print(f"Bucket creation error (may already exist): {e}")


def upload_images(image_dir: Path) -> dict[str, str]:
    """Upload all jpg/png images from directory. Returns {filename: public_url}."""
    bucket = client.storage.from_(BUCKET_NAME)
    uploaded = {}

    images = sorted(
        [f for f in image_dir.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")],
        key=lambda f: f.name,
    )
    print(f"Found {len(images)} images to upload")

    for i, img in enumerate(images):
        storage_path = f"eyecatch/{img.name}"
        print(f"  [{i+1}/{len(images)}] Uploading {img.name} ({img.stat().st_size // 1024}KB)...")

        try:
            with open(img, "rb") as f:
                content_type = "image/jpeg" if img.suffix.lower() in (".jpg", ".jpeg") else f"image/{img.suffix.lower().lstrip('.')}"
                bucket.upload(
                    storage_path,
                    f.read(),
                    file_options={"content-type": content_type, "upsert": "true"},
                )
            public_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET_NAME}/{storage_path}"
            uploaded[img.name] = public_url
        except Exception as e:
            print(f"    Failed: {e}")

    print(f"Uploaded {len(uploaded)} images")
    return uploaded


def assign_to_posts(image_urls: dict[str, str]):
    """Assign images to posts that don't have cover_image set."""
    result = (
        client.table("posts")
        .select("id, slug, cover_image")
        .eq("media_id", "shokunin-san")
        .eq("status", "published")
        .order("published_at", desc=False)
        .execute()
    )
    posts = result.data or []
    print(f"Found {len(posts)} published posts")

    # Posts needing images
    needs_image = [p for p in posts if not p.get("cover_image")]
    urls = list(image_urls.values())

    if not urls:
        print("No images available")
        return

    # Shuffle to get varied assignments
    random.seed(42)  # Deterministic for reproducibility
    random.shuffle(urls)

    updated = 0
    for i, post in enumerate(needs_image):
        url = urls[i % len(urls)]
        try:
            client.table("posts").update({"cover_image": url}).eq("id", post["id"]).execute()
            updated += 1
            print(f"  [{updated}] {post['slug'][:50]} → {url.split('/')[-1]}")
        except Exception as e:
            print(f"  Failed to update {post['slug']}: {e}")

    print(f"Updated {updated} posts with cover images")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--image-dir", required=True, help="Directory with images")
    args = parser.parse_args()

    image_dir = Path(args.image_dir).expanduser()
    if not image_dir.is_dir():
        print(f"ERROR: {image_dir} is not a directory")
        sys.exit(1)

    ensure_bucket()
    urls = upload_images(image_dir)
    assign_to_posts(urls)
    print("Done!")


if __name__ == "__main__":
    main()
