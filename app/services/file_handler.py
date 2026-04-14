import mimetypes
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from flask import current_app, has_request_context, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

try:
    import magic
except Exception:  # pragma: no cover
    magic = None


ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/gif",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
}

LOCAL_STORAGE_PREFIX = "local://"
LOCAL_FILE_SALT = "local-file-url"


class FileHandlerError(Exception):
    pass


def _s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=current_app.config.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=current_app.config.get("AWS_SECRET_ACCESS_KEY"),
        region_name=current_app.config.get("AWS_S3_REGION"),
    )


def _use_s3() -> bool:
    if current_app.debug or current_app.testing:
        return False
    return bool(current_app.config.get("USE_S3"))


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def _local_storage_root() -> Path:
    configured = current_app.config.get("LOCAL_STORAGE_PATH", "local_storage")
    root = Path(configured)
    if not root.is_absolute():
        root = Path(current_app.root_path).parent / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def _detect_mime(data: bytes, filename: str) -> str:
    if magic is not None:
        try:
            return str(magic.from_buffer(data, mime=True))
        except Exception:
            pass

    guessed, _encoding = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _safe_filename(filename: str) -> str:
    base_name = Path(filename or "upload").name
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in base_name)


def _build_storage_key(filename: str, mime_type: str) -> str:
    safe_filename = _safe_filename(filename)
    file_stem = Path(safe_filename).stem or "file"
    ext = Path(safe_filename).suffix
    if not ext:
        ext = mimetypes.guess_extension(mime_type) or ""

    folder = "avatars" if file_stem.startswith("avatar_") else "feed"
    return f"{folder}/{uuid.uuid4().hex}_{file_stem}{ext}"


def _ensure_local_storage_path(storage_path: str) -> Path:
    if not storage_path.startswith(LOCAL_STORAGE_PREFIX):
        raise FileHandlerError("Invalid local storage path.")

    relative = storage_path[len(LOCAL_STORAGE_PREFIX) :].lstrip("/").replace("\\", "/")
    if not relative or ".." in Path(relative).parts:
        raise FileHandlerError("Invalid local storage path.")

    root = _local_storage_root().resolve()
    absolute = (root / relative).resolve()
    if not str(absolute).startswith(str(root)):
        raise FileHandlerError("Invalid local storage path.")
    return absolute


def upload_file_to_s3(file_object, filename, allowed_types=None):
    allowed = set(allowed_types or ALLOWED_MIME_TYPES)

    original_filename = str(getattr(file_object, "filename", "") or "").strip()
    requested_filename = str(filename or "").strip()
    effective_filename = requested_filename or original_filename or "upload"

    # If caller passes a logical name without extension (e.g. avatar_<id>),
    # reuse the uploaded file extension so MIME guess and content-type checks remain accurate.
    if not Path(effective_filename).suffix and Path(original_filename).suffix:
        effective_filename = f"{effective_filename}{Path(original_filename).suffix}"

    data = file_object.read()
    file_object.seek(0)

    max_size = int(current_app.config.get("MAX_FILE_SIZE_MB", 10)) * 1024 * 1024
    if len(data) > max_size:
        raise FileHandlerError("File exceeds maximum size.")

    mime_probe_name = original_filename or effective_filename
    mime_type = _detect_mime(data, mime_probe_name)
    if mime_type not in allowed:
        raise FileHandlerError("Unsupported file type.")

    storage_key = _build_storage_key(effective_filename, mime_type)

    if _use_s3():
        try:
            _s3_client().put_object(
                Bucket=current_app.config["AWS_S3_BUCKET"],
                Key=storage_key,
                Body=data,
                ContentType=mime_type,
            )
            return storage_key
        except ClientError as exc:
            raise FileHandlerError("S3 upload failed.") from exc

    local_path = (_local_storage_root() / storage_key).resolve()
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(data)
    return f"{LOCAL_STORAGE_PREFIX}{storage_key}"


def generate_presigned_url(storage_path, expiry=3600):
    if not storage_path:
        return ""

    if storage_path.startswith("http://") or storage_path.startswith("https://"):
        return storage_path

    if _use_s3() and not storage_path.startswith(LOCAL_STORAGE_PREFIX):
        try:
            return _s3_client().generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": current_app.config["AWS_S3_BUCKET"], "Key": storage_path},
                ExpiresIn=expiry,
            )
        except ClientError:
            return ""

    token = _serializer().dumps(storage_path, salt=LOCAL_FILE_SALT)
    if has_request_context():
        return url_for("main.local_file_download", token=token, _external=True)

    base_url = (current_app.config.get("BASE_URL") or "").rstrip("/")
    if base_url:
        return f"{base_url}/files/local/{token}"
    return f"/files/local/{token}"


def decode_local_download_token(token: str, max_age: int = 3600) -> str:
    try:
        storage_path = _serializer().loads(token, salt=LOCAL_FILE_SALT, max_age=max_age)
    except (BadSignature, SignatureExpired) as exc:
        raise FileHandlerError("File link is invalid or expired.") from exc

    if not isinstance(storage_path, str):
        raise FileHandlerError("Invalid file token.")
    return storage_path


def get_local_file_absolute_path(storage_path: str) -> Path:
    return _ensure_local_storage_path(storage_path)


def delete_file_from_s3(storage_path):
    if not storage_path:
        return

    if _use_s3() and not storage_path.startswith(LOCAL_STORAGE_PREFIX):
        try:
            _s3_client().delete_object(Bucket=current_app.config["AWS_S3_BUCKET"], Key=storage_path)
        except ClientError as exc:
            raise FileHandlerError("S3 delete failed.") from exc
        return

    try:
        local_file = _ensure_local_storage_path(storage_path)
    except FileHandlerError:
        return

    if local_file.exists():
        local_file.unlink()
