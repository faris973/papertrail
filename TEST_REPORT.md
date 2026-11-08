# Verification — 2026-11-08

Tested on Windows, Python 3.12, CPU inference.

## Passed

- Fourteen backend tests: OCR and text indexing; changed/deleted files; corrupt-file isolation; visual failure recovery; image fingerprint replacement; authenticated APIs; malformed requests; folder browsing; original PDF rendering, grouping and page counts; nested HEIC/photo-only imports; cancellation and resume; automatic updates, removal and undo; unavailable-drive preservation.
- Complete photo-library browser workflow: browse into a folder, recursively import three photos without copying originals, exclude text files, automatically add/delete files, pause/resume syncing, render and navigate a three-page PDF, skip duplicate uploads, undo removal, and fit the import dialog on a 390-pixel screen. No JavaScript errors.
- Browser document workflow: upload, index, search, highlights, reader, deletion, reload, PDF/text filters, grid/list, help, keyboard shortcut, mobile overflow, and no JavaScript errors.
- Real-model photo workflow, repeated against a fresh application virtual environment: three neutral filenames, genuine CLIP embeddings, thumbnail rendering, photo reader, text-only and visual-only switches, mobile layout, restart persistence, offline model loading, and deletion.
- The query `car` has zero text-only matches and retrieves the McLaren through visual search. `orange sports car`, `cat`, and `mountain` retrieve the intended test photos.
- Real-model test runs with Hugging Face and Transformers offline flags after model preparation. Browser requests remain local.
- Dependency consistency and updated bootstrap with package-index access disabled passed. The earlier release also passed a fresh bootstrap installation.
- The live library was migrated to visual search without modifying its originals.

## Accuracy boundaries

Three positive photo fixtures are an acceptance test, not a general accuracy benchmark. Visual matches can be wrong: in exploratory testing, `spaceship` also returned the exotic car. The interface calls out approximate visual suggestions. No confidence percentage is presented.

Folder browsing happens inside Papertrail; no Windows popup is required. Cloud-only libraries need downloading first. Videos and camera RAW are unsupported. Large-library throughput has not been benchmarked; imports run sequentially on CPU and can be stopped after the current file.

## Reproduce

See README.md and tests/FIXTURES.md. The real-model suite requires the cached CLIP model and downloaded fixture images. Screenshots represent the temporary test library, not the user's private files.
