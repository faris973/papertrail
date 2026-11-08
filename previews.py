"""Bounded, local image previews. All PDFium access shares one mutex."""
import io
import threading
from functools import lru_cache
from pathlib import Path

PDF_LOCK = threading.RLock()


def pdf_page(path, number, width=1500):
    import pypdfium2 as pdfium
    with PDF_LOCK:
        with pdfium.PdfDocument(path) as document:
            if not 1 <= number <= len(document):
                raise ValueError("Page is outside this document")
            page = document[number - 1]
            scale = min(width / max(page.get_width(), 1), 2400 / max(page.get_height(), 1), 3)
            bitmap = page.render(scale=scale)
            # Copy pixels before closing PDFium objects and releasing the mutex.
            image = bitmap.to_pil().convert("RGB").copy()
            bitmap.close()
            page.close()
            return image


def photo(path, width):
    from PIL import Image, ImageOps
    from pillow_heif import register_heif_opener
    register_heif_opener()
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert("RGBA")
        image.thumbnail((width, width))
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(image)
        return background.convert("RGB")


@lru_cache(maxsize=24)
def _render(path, stamp, page, width):
    image = pdf_page(path, page, width) if Path(path).suffix.lower() == ".pdf" else photo(path, width)
    result = io.BytesIO()
    image.save(result, format="JPEG", quality=88)
    return result.getvalue()


def render(path, page=1, width=1500):
    path = Path(path)
    stat = path.stat()
    return _render(str(path), (stat.st_mtime_ns, stat.st_size), page, max(320, min(width, 2200)))
