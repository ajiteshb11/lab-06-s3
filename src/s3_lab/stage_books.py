#!/usr/bin/env python3
"""Download Project Gutenberg books and stage them in a public S3 bucket."""

import json
import logging
import os
import sys
import time
from urllib.parse import urlparse

import boto3
import requests
from botocore.exceptions import ClientError

# Set up logging and one shared S3 client.
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)
s3 = boto3.client("s3", region_name="us-east-1")


def parse_args():
    """Read the book list, index page, and bucket name from the command line."""
    if len(sys.argv) < 4:
        log.error(
            "Usage: python stage_books.py <book_urls.txt> <index.html> <bucket>"
        )
        sys.exit(1)
    return sys.argv[1], sys.argv[2], sys.argv[3]


def download_books(list_file, dest_dir):
    """Download books, skipping existing files, and return local paths."""
    os.makedirs(dest_dir, exist_ok=True)
    paths = []

    try:
        with open(list_file, "r", encoding="utf-8") as file:
            urls = [line.strip() for line in file if line.strip()]
    except OSError as error:
        log.error("Cannot read book list: %s", error)
        return paths

    for url in urls:
        filename = os.path.basename(urlparse(url).path)
        path = os.path.join(dest_dir, filename)

        if os.path.exists(path):
            log.info("Already downloaded: %s", filename)
            paths.append(path)
            continue

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            with open(path, "wb") as file:
                file.write(response.content)
            paths.append(path)
            log.info("Downloaded: %s", filename)
        except requests.RequestException as error:
            log.error("Error downloading %s: %s", url, error)
        except OSError as error:
            log.error("Error saving %s: %s", path, error)

        time.sleep(1)

    log.info("Books available locally: %d", len(paths))
    return paths


def create_bucket(bucket):
    """Create the S3 bucket if it does not already exist."""
    try:
        s3.head_bucket(Bucket=bucket)
        log.info("Bucket already exists: %s", bucket)
        return True
    except ClientError as error:
        code = str(error.response["Error"]["Code"])
        if code not in ("404", "NoSuchBucket"):
            log.error("Cannot access bucket %s: %s", bucket, error)
            return False

    try:
        s3.create_bucket(Bucket=bucket)
        log.info("Created bucket: %s", bucket)
        return True
    except ClientError as error:
        log.error("Error creating bucket %s: %s", bucket, error)
        return False


def make_public(bucket):
    """Allow public read access to objects using an S3 bucket policy."""
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/*",
            }
        ],
    }

    try:
        s3.put_public_access_block(
            Bucket=bucket,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": False,
                "IgnorePublicAcls": False,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            },
        )
        s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))
        log.info("Public-read policy applied to %s", bucket)
        return True
    except ClientError as error:
        log.error("Error making bucket public: %s", error)
        return False


def upload_files(bucket, file_paths):
    """Upload books to the bucket root as plain-text objects."""
    uploaded = 0

    for path in file_paths:
        try:
            s3.upload_file(
                path,
                bucket,
                os.path.basename(path),
                ExtraArgs={"ContentType": "text/plain; charset=utf-8"},
            )
            uploaded += 1
            log.info("Uploaded: %s", os.path.basename(path))
        except (ClientError, OSError) as error:
            log.error("Error uploading %s: %s", path, error)

    return uploaded


def upload_index(bucket, index_path):
    """Upload the HTML index page."""
    try:
        s3.upload_file(
            index_path,
            bucket,
            "index.html",
            ExtraArgs={"ContentType": "text/html"},
        )
        log.info("Uploaded index.html")
        return True
    except (ClientError, OSError) as error:
        log.error("Error uploading index: %s", error)
        return False


def main():
    """Run the complete S3 book-staging workflow."""
    list_file, index_path, bucket = parse_args()

    books = download_books(list_file, "books")
    if not books:
        log.error("No books available. Stopping.")
        sys.exit(1)

    if not create_bucket(bucket):
        sys.exit(1)

    if not make_public(bucket):
        sys.exit(1)

    uploaded = upload_files(bucket, books)
    index_ok = upload_index(bucket, index_path)

    if uploaded != len(books) or not index_ok:
        log.error("Staging incomplete: %d/%d books uploaded.", uploaded, len(books))
        sys.exit(1)

    log.info("Success! Uploaded %d books.", uploaded)
    log.info("Public index: https://%s.s3.amazonaws.com/index.html", bucket)


if __name__ == "__main__":
    main()
