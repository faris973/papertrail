# Visual acceptance fixtures

Download only when running the optional real-model acceptance test. The images are test inputs, not bundled sample content or files added to the user's library. Save them under the neutral names below; visual acceptance explicitly requires the car query to return no text match.

| Filename | Subject | Source |
|---|---|---|
| IMG_001.jpg | Orange McLaren | Luke Miller, [Unsplash photo](https://unsplash.com/photos/bright-orange-mclaren-supercar-with-doors-open-5JPCIIOdrM8), [image](https://images.unsplash.com/photo-1760689029558-500081eb2bf7?auto=format&fit=crop&w=1100&q=85) |
| IMG_002.jpg | Cat | [Unsplash image](https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=900&q=85) |
| IMG_003.jpg | Mountain | [Unsplash image](https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=900&q=85) |

Images are served under the [Unsplash license](https://unsplash.com/license). Check the source terms before redistributing them. The tested screenshots use these fixtures in a temporary database; the actual user library is untouched.

Run `python tests/visual_e2e.py /path/to/visual-fixtures` from the repository root. Prepare the model with `python vision.py` first. The test enables Hugging Face offline mode and uses cached model files.
