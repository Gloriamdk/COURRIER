from pathlib import Path
import re
import zipfile

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
    ".docx": {
        "mimes": {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
        "signatures": (b"PK\x03\x04",),
    },
    ".xlsx": {
        "mimes": {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        },
        "signatures": (b"PK\x03\x04",),
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
    - nom de fichier sans path traversal, null bytes, double extension
    - longueur maximale du nom de fichier
    - extension autorisée
    - signature (magic bytes)
    - mime (si fourni)
    - vérification image via Pillow pour JPG/PNG
    - vérification des archives Office et rejet des macros/contenus dangereux
    - vérification PDF : absence de JavaScript et d'actions automatiques
    """
    if not uploaded_file:
        return

    if uploaded_file.size > MAX_UPLOAD_SIZE:
        raise ValidationError("Le fichier depasse la taille maximale autorisee de 10 Mo.")

    # Nom de fichier
    name = uploaded_file.name or ""

    # Rejet des null bytes dans le nom (contournement classique de l'extension)
    if "\x00" in name:
        raise ValidationError("Nom de fichier invalide ou potentiellement dangereux.")

    # Longueur maximale du nom de fichier
    if len(name) > 255:
        raise ValidationError("Le nom du fichier est trop long (255 caractères maximum).")

    # Reject filenames that include path components (e.g. ../../secret.pdf)
    if name != Path(name).name:
        raise ValidationError("Nom de fichier invalide ou potentiellement dangereux.")

    if not _safe_filename(name):
        raise ValidationError("Nom de fichier invalide ou potentiellement dangereux.")

    # Rejet des doubles extensions (ex: fichier.pdf.exe, image.jpg.php)
    stem = Path(name).stem
    if "." in stem:
        inner_ext = Path(stem).suffix.lower()
        if inner_ext and inner_ext not in ALLOWED_UPLOADS:
            raise ValidationError("Les fichiers avec double extension ne sont pas autorisés.")

    extension = Path(name).suffix.lower()
    rules = ALLOWED_UPLOADS.get(extension)
    if rules is None:
        raise ValidationError("Format non autorise. Formats acceptes : PDF, DOCX, XLSX, JPG, PNG.")

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
        # Attempt to verify image can be opened with Pillow
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

    if extension == ".pdf":
        # Reject active PDF features before storing the document.
        uploaded_file.seek(0)
        sample = uploaded_file.read()
        uploaded_file.seek(0)
        if any(marker in sample for marker in (b"/JavaScript", b"/JS", b"/OpenAction", b"/AA")):
            raise ValidationError("Le PDF contient des contenus dynamiques potentiellement dangereux.")

    if extension in (".docx", ".xlsx"):
        uploaded_file.seek(0)
        try:
            with zipfile.ZipFile(uploaded_file) as archive:
                if archive.testzip() is not None:
                    raise ValidationError("L'archive Office est corrompue.")
                for member in archive.infolist():
                    member_path = Path(member.filename)
                    if member.filename.startswith(("/", "\\")) or ".." in member_path.parts:
                        raise ValidationError("L'archive contient un chemin de fichier dangereux.")
                    if member.filename.lower().endswith(("vbaproject.bin", ".exe", ".js", ".vbs", ".cmd", ".bat")):
                        raise ValidationError("Les macros et fichiers exécutables ne sont pas autorisés.")
        except zipfile.BadZipFile:
            raise ValidationError("Le fichier Office est invalide ou corrompu.")
        finally:
            uploaded_file.seek(0)
