#!/bin/bash
set -euo pipefail

# Check for the three required arguments.
if [ "$#" -ne 3 ]; then
    echo "Usage: $0 BOOK_URL BUCKET EXPIRATION"
    exit 1
fi

URL="$1"
BUCKET="$2"
EXPIRATION="$3"

# Get the filename and download the book.
FILE="${URL##*/}"
mkdir -p books
curl -fLsS "$URL" -o "books/$FILE"

# Create a private bucket if it does not exist.
if ! uv run aws s3 ls "s3://$BUCKET" > /dev/null 2>&1; then
    uv run aws s3 mb "s3://$BUCKET" --region us-east-1
fi

# Upload the book without making it public.
uv run aws s3 cp "books/$FILE" "s3://$BUCKET/$FILE" \
    --content-type "text/plain; charset=utf-8"

# Print a temporary access URL.
uv run aws s3 presign "s3://$BUCKET/$FILE" \
    --expires-in "$EXPIRATION"
