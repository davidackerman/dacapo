import attr

from .array_config import ArrayConfig
from .logical_or_array import LogicalOrArray
from .array_config import ArrayConfig

from typing import List, Tuple


@attr.s
class LogicalOrArrayConfig(ArrayConfig):
    """This config class takes a source array and performs a logical or over the channels.
    Good for union multiple masks."""

    array_type = LogicalOrArray

    source_array_config: ArrayConfig = attr.ib(
        metadata={"help_text": "The Array of masks from which to take the union"}
    )
