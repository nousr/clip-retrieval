"""load clip"""

from functools import lru_cache
from torch import autocast, nn
import torch
import clip
from PIL import Image


class OpenClipWrapper(nn.Module):
    """
    Wrap OpenClip for managing input types
    """

    def __init__(self, inner_model, device):
        super().__init__()
        self.inner_model = inner_model
        self.device = torch.device(device=device)
        if self.device.type == "cpu":
            self.dtype = torch.float32
        else:
            self.dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16

    def encode_image(self, image):
        if self.device.type == "cpu":
            return self.inner_model.encode_image(image)
        with autocast(device_type=self.device.type, dtype=self.dtype):
            return self.inner_model.encode_image(image)

    def encode_text(self, text):
        if self.device.type == "cpu":
            return self.inner_model.encode_text(text)
        with autocast(device_type=self.device.type, dtype=self.dtype):
            return self.inner_model.encode_text(text)

    def forward(self, *args, **kwargs):
        return self.inner_model(*args, **kwargs)


@lru_cache(maxsize=None)
def load_open_clip(clip_model, use_jit=True, device="cuda", cache=None):
    """load open clip"""

    import open_clip  # pylint: disable=import-outside-toplevel

    torch.backends.cuda.matmul.allow_tf32 = True

    pretrained = dict(open_clip.list_pretrained())
    checkpoint = pretrained[clip_model]
    model, _, preprocess = open_clip.create_model_and_transforms(
        clip_model, pretrained=checkpoint, device=device, jit=use_jit, cache_dir=cache
    )
    model = OpenClipWrapper(inner_model=model, device=device)
    return model, preprocess


@lru_cache(maxsize=None)
def load_clip(clip_model="ViT-B/32", use_jit=True, warmup_batch_size=1, cache=None):
    """Load clip then warmup"""
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if clip_model.startswith("open_clip:"):
        clip_model = clip_model[len("open_clip:") :]
        model, preprocess = load_open_clip(clip_model, use_jit, device, cache=cache)
    else:
        model, preprocess = clip.load(clip_model, device=device, jit=use_jit, cache=cache)

    print("warming up with batch size", warmup_batch_size)
    warmup(warmup_batch_size, device, preprocess, model)
    print("done warming up")
    return model, preprocess


def warmup(batch_size, device, preprocess, model):
    fake_img = Image.new("RGB", (224, 224), color="red")
    fake_text = ["fake"] * batch_size
    image_tensor = torch.cat([torch.unsqueeze(preprocess(fake_img).to(device), 0)] * batch_size)
    text_tokens = clip.tokenize(fake_text).to(device)
    for _ in range(2):
        with torch.no_grad():
            model.encode_image(image_tensor)
            model.encode_text(text_tokens)
