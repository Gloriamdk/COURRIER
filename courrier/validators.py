from pathlib import Path

from django.core.exceptions import ValidationError


MAX_UPLOAD_SIZE = 10 * 1024 * 1024
ALLOWED_UPLOADS = {
    ".pdf": {
        "mimes": {"application/pdf"},
        "signatures": (b"%PDF-",),
    },
    ".jpg": {
        "mimes": {"image/jpeg"},
        "signatures": (b"\xff\xd8\xff",),
    },
    ".jpeg": {
        "mimes": {"image/jpeg"},
        "signatures": (b"\xff\xd8\xff",),
    },
    ".png": {
        "mimes": {"image/png"},
        "signatures": (b"\x89PNG\r\n\x1a\n",),
    },
}


def validate_document_upload(uploaded_file):
    if not uploaded_file:
        return

    if uploaded_file.size > MAX_UPLOAD_SIZE:
        raise ValidationError("Le fichier depasse la taille maximale autorisee de 10 Mo.")

    extension = Path(uploaded_file.name or "").suffix.lower()
    rules = ALLOWED_UPLOADS.get(extension)
    if rules is None:
        raise ValidationError("Format non autorise. Formats acceptes : PDF, JPG, PNG.")

    content_type = getattr(uploaded_file, "content_type", None)
    if content_type and content_type not in rules["mimes"]:
        raise ValidationError("Type MIME non autorise pour ce fichier.")

    try:
        position = uploaded_file.tell()
    except (AttributeError, OSError):
        position = None

    header = uploaded_file.read(16)

    if position is not None:
        uploaded_file.seek(position)
    else:
        uploaded_file.seek(0)

    if not any(header.startswith(signature) for signature in rules["signatures"]):
        raise ValidationError("Le contenu du fichier ne correspond pas au format annonce.")
