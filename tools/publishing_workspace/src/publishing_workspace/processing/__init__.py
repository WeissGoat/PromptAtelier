from .models import ImageOperation, MosaicAdapter, ProcessingResult
from .operations import OperationRegistry, StripMetadataOperation
from .pipeline import ImageProcessingPipeline

__all__ = [
    "ImageOperation",
    "ImageProcessingPipeline",
    "MosaicAdapter",
    "OperationRegistry",
    "ProcessingResult",
    "StripMetadataOperation",
]
