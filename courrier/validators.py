from pathlib import Path
import re

from django.core.exceptions import ValidationError

try:
    from PIL import Image
except Exception:
    Image = None

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


def _safe_filename(name: str) -> bool:
    """Return True if filename does not contain dangerous path components."""
    if not name:
        return False
    # No path separators, no parent traversal
    if ".." in name or "/" in name or "\\" in name:
        return False
    # Simple blacklist for special chars that may confuse shells or webservers
    if re.search(r"[\x00-\x1f<>:\\|?*]", name):
        return False
    return True


def validate_document_upload(uploaded_file):
    """Valide le fichier uploadé pour les documents scannés.

    Contrôles effectués :
    - taille maximale
    - nom de fichier sans path traversal
    - extension autorisée
    - signature (magic bytes)
    - mime (si fourni)
    - vérification image via Pillow/imghdr pour JPG/PNG
    - vérification basique PDF : absence de JavaScript embarqué
    """
    if not uploaded_file:
        return

    if uploaded_file.size > MAX_UPLOAD_SIZE:
        raise ValidationError("Le fichier depasse la taille maximale autorisee de 10 Mo.")

    # Nom de fichier
    name = uploaded_file.name or ""
    # Reject filenames that include path components (e.g. ../../secret.pdf)
    if name != Path(name).name:
        raise ValidationError("Nom de fichier invalide ou potentiellement dangereux.")

    if not _safe_filename(name):
        raise ValidationError("Nom de fichier invalide ou potentiellement dangereux.")

    extension = Path(name).suffix.lower()
    rules = ALLOWED_UPLOADS.get(extension)
    if rules is None:
        raise ValidationError("Format non autorise. Formats acceptes : PDF, JPG, PNG.")

    content_type = getattr(uploaded_file, "content_type", None)
    # Do not rely solely on content_type from client, but use it as additional check
    if content_type and content_type not in rules["mimes"]:
        raise ValidationError("Type MIME non autorise pour ce fichier.")

    # Read header for magic bytes
    try:
        position = uploaded_file.tell()
    except (AttributeError, OSError):
        position = None

    header = uploaded_file.read(4096)

    if position is not None:
        uploaded_file.seek(position)
    else:
        uploaded_file.seek(0)

    if not any(header.startswith(signature) for signature in rules["signatures"]):
        raise ValidationError("Le contenu du fichier ne correspond pas au format annonce.")

    # Additional checks per type
    if extension in (".jpg", ".jpeg", ".png"):
        # Attempt to verify image can be opened via Pillow.
        # imghdr was removed in Python 3.13 — we rely on magic bytes (already
        # checked above) as the fallback when Pillow is not installed.
        if Image is not None:
            try:
                # Pillow needs a file-like object starting at 0
                uploaded_file.seek(0)
                img = Image.open(uploaded_file)
                img.verify()
            except Exception:
                raise ValidationError("Image invalide ou corrompue.")
            finally:
                uploaded_file.seek(0)
        # If Pillow is not available, the magic-bytes check above is sufficient.

    if extension == ".pdf":
        # Simple heuristic: scan first 64KB for JavaScript hints commonly used in malicious PDFs
        uploaded_file.seek(0)
        sample = uploaded_file.read(65536)
        uploaded_file.seek(0)
        # Look for /JavaScript, /JS, /OpenAction which can indicate embedded scripts
        if b"/JavaScript" in sample or b"/JS" in sample or b"/OpenAction" in sample:
            raise ValidationError("Le PDF contient des contenus dynamiques potentiellement dangereux (JavaScript).")
