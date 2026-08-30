# OLR India - S3 Upload Utility
import uuid, boto3, os
from PIL import Image
from io import BytesIO
from flask import current_app

def compress_and_upload(file, folder="products"):
    """
    Compress image to max 200KB then upload to S3.
    Returns public URL string or None on failure.
    """
    try:
        img = Image.open(file)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        quality = 85
        for _ in range(8):
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            if buffer.tell() <= 200 * 1024:
                break
            quality -= 10
            if quality < 20:
                # Still too big - resize down
                w, h = img.size
                img = img.resize((int(w * 0.8), int(h * 0.8)), Image.LANCZOS)
                quality = 50

        buffer.seek(0)
        filename  = f"{folder}/{uuid.uuid4().hex}.jpg"
        s3 = boto3.client(
            "s3",
            aws_access_key_id     = current_app.config["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key = current_app.config["AWS_SECRET_ACCESS_KEY"],
            region_name           = current_app.config["AWS_S3_REGION"],
        )
        s3.upload_fileobj(
            buffer,
            current_app.config["AWS_S3_BUCKET"],
            filename,
            ExtraArgs={"ContentType": "image/jpeg"},
        )
        return f"https://{current_app.config['AWS_S3_BUCKET']}.s3.{current_app.config['AWS_S3_REGION']}.amazonaws.com/{filename}"

    except Exception as e:
        print(f"S3 upload error: {e}")
        return None


def delete_from_s3(url):
    """Delete an object from S3 given its full URL."""
    try:
        bucket = current_app.config["AWS_S3_BUCKET"]
        region = current_app.config["AWS_S3_REGION"]
        prefix = f"https://{bucket}.s3.{region}.amazonaws.com/"
        key = url.replace(prefix, "")
        boto3.client(
            "s3",
            aws_access_key_id     = current_app.config["AWS_ACCESS_KEY_ID"],
            aws_secret_access_key = current_app.config["AWS_SECRET_ACCESS_KEY"],
            region_name           = region,
        ).delete_object(Bucket=bucket, Key=key)
        return True
    except Exception as e:
        print(f"S3 delete error: {e}")
        return False