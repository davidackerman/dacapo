import funlib.learn.torch as ft
from funlib.geometry import Coordinate
import attr

from .module_wrapper import ModuleWrapper
from .model_abc import ModelABC
from dacapo.converter import converter

from typing import List, Optional, Tuple
from enum import Enum


class ConvPaddingOption(Enum):
    VALID = "valid"
    SAME = "same"


converter.register_unstructure_hook(
    ConvPaddingOption,
    lambda o: {"value": o.value},
)
converter.register_structure_hook(
    ConvPaddingOption,
    lambda o, _: ConvPaddingOption(o["value"]),
)


@attr.s
class UNet(ModelABC):
    # standard model attributes
    input_shape: List[int] = attr.ib(
        metadata={"help_text": "The input shape of the model."}
    )
    fmaps_out: int = attr.ib(
        metadata={"help_text": "Number of feature maps output by model."}
    )

    # unet attributes
    fmap_inc_factor: int = attr.ib(
        metadata={
            "help_text": "The increment factor for the number of "
            "feature maps at each down sample."
        }
    )
    downsample_factors: List[List[int]] = attr.ib(
        metadata={
            "help_text": "The factor by which to downsample spatial dimensions along each axis."
        }
    )

    # optional values
    # standard model attributes
    output_shape: Optional[List[int]] = attr.ib(
        default=None, metadata={"help_text": "The output shape of the Model."}
    )

    # unet attributes
    kernel_size_down: Optional[List[List[int]]] = attr.ib(
        default=None,
        metadata={
            "help_text": "The number and size of the convolutional kernels before downsampling. "
            "Defaults to 2 3x3x3 kernels."
        },
    )
    kernel_size_up: Optional[List[List[int]]] = attr.ib(
        default=None,
        metadata={
            "help_text": "The number and size of the convolutional kernels after upsampling. "
            "Defaults to 2 3x3x3 kernels."
        },
    )
    constant_upsample: bool = attr.ib(
        default=True,
        metadata={
            "help_text": "Whether to learn a transpose convolution or a simple "
            "scale/shift for upsampling. Keeping the upsample constant can help avoid "
            "checkerpattern local minima."
        },
    )
    padding: ConvPaddingOption = attr.ib(
        default=ConvPaddingOption.VALID,
        metadata={"help_text": "How to pad your convolutions. Either same or valid."},
    )

    # attributes that can be read from other configs:
    fmaps_in: Optional[int] = attr.ib(
        default=None, metadata={"help_text": "The number of channels in your raw data."}
    )  # can be read from data num_channels

    def module(self, dataset):
        assert (
            self.fmaps_in is None or self.fmaps_in == dataset.raw.num_channels
        ), f"{self.fmaps_in} {dataset.raw.num_channels}"
        self.fmaps_in = dataset.raw.num_channels
        return UNetModule(self)


class UNetModule(ModuleWrapper):
    """Creates a funlib.learn.torch U-Net for the given data from a model
    configuration."""

    def __init__(self, model_config: UNet):

        super(UNetModule, self).__init__(
            None,
            model_config.fmaps_in,
            model_config.fmaps_out,
        )

        fmaps_in = model_config.fmaps_in
        levels = len(model_config.downsample_factors) + 1
        dims = len(model_config.downsample_factors[0])

        if hasattr(model_config, "kernel_size_down"):
            kernel_size_down = model_config.kernel_size_down
        else:
            kernel_size_down = [[(3,) * dims, (3,) * dims]] * levels
        if hasattr(model_config, "kernel_size_up"):
            kernel_size_up = model_config.kernel_size_up
        else:
            kernel_size_up = [[(3,) * dims, (3,) * dims]] * (levels - 1)

        # downsample factors has to be a list of tuples
        downsample_factors = [tuple(x) for x in model_config.downsample_factors]

        self.unet = ft.models.UNet(
            in_channels=fmaps_in,
            num_fmaps=model_config.fmaps_out,
            fmap_inc_factor=model_config.fmap_inc_factor,
            kernel_size_down=kernel_size_down,
            kernel_size_up=kernel_size_up,
            downsample_factors=downsample_factors,
            constant_upsample=True,
            padding=model_config.padding,
        )

    def forward(self, x):
        return self.unet(x)
