from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from adproof.domain.models import TypedErrorCode

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_SIDE = 8192


class ImageFreezeError(ValueError):
    def __init__(self, code: TypedErrorCode, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FrozenImage:
    model_input: bytes
    source_image_sha256: str
    model_input_sha256: str
    width: int
    height: int
    source_format: str
    transformation_metadata: dict[str, object]


def freeze_image(data: bytes) -> FrozenImage:
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageFreezeError(TypedErrorCode.IMAGE_TOO_LARGE, "image exceeds 8 MiB")
    if not data:
        raise ImageFreezeError(TypedErrorCode.INVALID_IMAGE, "image is empty")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            Image.MAX_IMAGE_PIXELS = MAX_PIXELS
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"PNG", "JPEG"}:
                    raise ImageFreezeError(
                        TypedErrorCode.INVALID_IMAGE, "only PNG and JPEG are supported"
                    )
                if getattr(image, "n_frames", 1) != 1:
                    raise ImageFreezeError(
                        TypedErrorCode.INVALID_IMAGE, "animated images are unsupported"
                    )
                width, height = image.size
                if width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
                    raise ImageFreezeError(
                        TypedErrorCode.IMAGE_TOO_LARGE, "image dimensions exceed limits"
                    )
                image.load()
                canonical = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                output = io.BytesIO()
                canonical.save(output, format="PNG", optimize=True)
                model_bytes = output.getvalue()
    except ImageFreezeError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ImageFreezeError(
            TypedErrorCode.INVALID_IMAGE, "bytes are not a safe PNG or JPEG image"
        ) from exc
    return FrozenImage(
        model_input=model_bytes,
        source_image_sha256=hashlib.sha256(data).hexdigest(),
        model_input_sha256=hashlib.sha256(model_bytes).hexdigest(),
        width=width,
        height=height,
        source_format=image.format,
        transformation_metadata={
            "format": "PNG",
            "metadata_stripped": True,
            "width": width,
            "height": height,
        },
    )
