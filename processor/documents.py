"""Extract every page; render pages without usable text for vision models."""
import base64
import hashlib
from pathlib import Path

import pymupdf


def digest(path):
    result = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def read_document(path, max_pages=40, max_bytes=25 * 1024 * 1024):
    path = Path(path)
    if path.stat().st_size > max_bytes:
        raise ValueError("File exceeds the 25 MB processing limit. Split it before processing.")
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise ValueError("PDF is password protected. Provide an unlocked copy.")
        if not doc.is_pdf:
            converted = doc.convert_to_pdf()
            pdf = pymupdf.open("pdf", converted)
        else:
            pdf = doc
        try:
            if not 0 < len(pdf) <= max_pages:
                raise ValueError(f"Document must contain 1–{max_pages} pages. Split larger files before processing.")
            images, text, total = [], [], 0
            for i, page in enumerate(pdf, 1):
                content = page.get_text().strip()
                text.append(f"--- Page {i} ---\n{content}")
                # Include image-bearing pages even if an incomplete OCR layer exists.
                if len(content) < 80 or page.get_images():
                    scale = min(1.8, 1800 / max(page.rect.width, page.rect.height))
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                    encoded = pix.tobytes("jpeg", jpg_quality=82)
                    total += len(encoded)
                    if total > 18 * 1024 * 1024:
                        raise ValueError("Rendered pages exceed the image request limit. Split this document.")
                    images.append((i, "image/jpeg", base64.b64encode(encoded).decode()))
            joined = "\n".join(text)
            if len(joined) > 350_000:
                raise ValueError("Document text exceeds the request limit. Split this document.")
            return joined, images, len(pdf)
        finally:
            if pdf is not doc:
                pdf.close()
