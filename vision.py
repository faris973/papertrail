"""Local CLIP embeddings. No image or query is sent to a remote service."""
import os
import threading
from functools import lru_cache
from pathlib import Path

MODEL_ID = 'openai/clip-vit-base-patch32'
REVISION = '3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268'
MODEL_KEY = MODEL_ID + '@' + REVISION
CACHE = Path(os.environ.get('PAPERTRAIL_MODELS', str(Path(__file__).parent / '.models')))
STATUS = {'state': 'idle', 'message': 'Visual search loads when you add your first photo.'}
_lock = threading.RLock()
_model = None
_processor = None


def ready():
    global _model, _processor
    with _lock:
        if _model is not None:
            return
        try:
            os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
            os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
            os.environ.setdefault('HF_HUB_ETAG_TIMEOUT', '10')
            from huggingface_hub import snapshot_download
            import torch
            from transformers import CLIPModel, CLIPProcessor
            patterns = ['*.json', 'merges.txt', 'vocab.json', 'pytorch_model.bin']
            try:
                folder = snapshot_download(MODEL_ID, revision=REVISION, cache_dir=str(CACHE), allow_patterns=patterns, local_files_only=True)
                if not all((Path(folder) / name).is_file() for name in ['pytorch_model.bin','config.json','preprocessor_config.json','vocab.json','merges.txt','tokenizer_config.json']):
                    raise FileNotFoundError('Weights not cached yet')
            except (OSError, ValueError):
                STATUS.update(state='downloading', message='Downloading the visual model once (about 600 MB). Keep Papertrail open.')
                folder = snapshot_download(MODEL_ID, revision=REVISION, cache_dir=str(CACHE), allow_patterns=patterns)
            STATUS.update(state='loading', message='Starting visual search on this computerâ€¦')
            torch.set_num_threads(min(4, os.cpu_count() or 2))
            processor = CLIPProcessor.from_pretrained(folder, local_files_only=True, use_fast=False)
            model = CLIPModel.from_pretrained(folder, local_files_only=True).eval().to('cpu')
            _processor, _model = processor, model
            STATUS.update(state='ready', message='Visual search is ready. Photos and searches stay on this device.')
        except Exception as error:
            STATUS.update(state='error', message='Visual model setup failed. Check your connection for the first download, then retry.', detail=str(error))
            raise RuntimeError(STATUS['message']) from error


def encode_image(image):
    import torch
    import numpy as np
    ready()
    with _lock, torch.inference_mode():
        inputs = _processor(images=image.convert('RGB'), return_tensors='pt')
        vector = _model.get_image_features(**inputs)
        vector = vector / vector.norm(dim=-1, keepdim=True)
        return vector[0].cpu().numpy().astype(np.float32)


@lru_cache(maxsize=128)
def encode_query(query):
    import torch
    import numpy as np
    ready()
    with _lock, torch.inference_mode():
        inputs = _processor(text=[query, 'a photo of ' + query], padding=True, truncation=True, max_length=77, return_tensors='pt')
        vectors = _model.get_text_features(**inputs)
        vectors = vectors / vectors.norm(dim=-1, keepdim=True)
        vector = vectors.mean(dim=0)
        vector = vector / vector.norm()
        return vector.cpu().numpy().astype(np.float32)

if __name__ == '__main__':
    ready()
    print(STATUS, flush=True)
