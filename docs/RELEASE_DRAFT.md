# Papertrail v0.1.0-beta — Find the thing you saved

Papertrail is a private search library for your photos, screenshots, scans, and documents. Import a folder and find photos by what they show, or documents by the words inside them. Everything is processed on your own computer.

Search “car” and retrieve a photo called `IMG_001.jpg` even if there is no text in the image. Search “warranty” to find the relevant document and jump to a matching page.

## In this first beta

- Local CLIP visual search plus OCR and document text search.
- Whole photo-folder imports, including subfolders and HEIC/HEIF images.
- Optional folder sync, pause/resume, and progress reporting.
- Original PDF previews, page navigation, zoom, and extracted text.
- Duplicate-upload detection and two-minute undo after removal.
- No account, subscription, or API key.

## Get started

Install Python 3.12, extract the source ZIP, and double-click **Start Papertrail.cmd**. The first setup downloads dependencies. The first photo import downloads approximately 600 MB of model weights. After setup, cached search works offline.

## Current limits

This is an early beta tested on Windows. Visual matches can be wrong, and very large libraries have not been benchmarked. PDF search is text/OCR based. Videos, camera RAW, and direct iCloud/Google Photos connections are not supported.

## Support

If you'd like to support development, send an optional PayPal donation to **alalifaris22@gmail.com**. All features remain free.

Bug reports, sample reproductions, and stars are welcome. Please never upload private files when reporting an issue.
