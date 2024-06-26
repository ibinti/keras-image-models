import typing

from keras import backend
from keras import layers

from kimm._src.blocks.conv2d import apply_conv2d_block
from kimm._src.blocks.squeeze_and_excitation import apply_se_block
from kimm._src.kimm_export import kimm_export
from kimm._src.utils.make_divisble import make_divisible


@kimm_export(parent_path=["kimm.blocks"])
def apply_inverted_residual_block(
    inputs,
    filters: int,
    depthwise_kernel_size: int = 3,
    expansion_kernel_size: int = 1,
    pointwise_kernel_size: int = 1,
    strides: int = 1,
    expansion_ratio: float = 1.0,
    se_ratio: float = 0.0,
    activation: str = "swish",
    se_channels: typing.Optional[int] = None,
    se_activation: typing.Optional[str] = None,
    se_gate_activation: typing.Optional[str] = "sigmoid",
    se_make_divisible_number: typing.Optional[int] = None,
    bn_epsilon: float = 1e-5,
    padding: typing.Optional[typing.Literal["same", "valid"]] = None,
    name: str = "inverted_residual_block",
):
    """Conv2D block + DepthwiseConv2D block + (SE) + Conv2D."""
    channels_axis = -1 if backend.image_data_format() == "channels_last" else -3
    input_channels = inputs.shape[channels_axis]
    hidden_channels = make_divisible(input_channels * expansion_ratio)
    has_skip = strides == 1 and input_channels == filters

    x = inputs
    # Point-wise expansion
    x = apply_conv2d_block(
        x,
        hidden_channels,
        expansion_kernel_size,
        1,
        activation=activation,
        bn_epsilon=bn_epsilon,
        padding=padding,
        name=f"{name}_conv_pw",
    )
    # Depth-wise convolution
    x = apply_conv2d_block(
        x,
        kernel_size=depthwise_kernel_size,
        strides=strides,
        activation=activation,
        use_depthwise=True,
        bn_epsilon=bn_epsilon,
        padding=padding,
        name=f"{name}_conv_dw",
    )
    # Squeeze-and-excitation
    if se_ratio > 0:
        x = apply_se_block(
            x,
            se_ratio,
            activation=se_activation or activation,
            gate_activation=se_gate_activation,
            se_input_channels=se_channels,
            make_divisible_number=se_make_divisible_number,
            name=f"{name}_se",
        )
    # Point-wise linear projection
    x = apply_conv2d_block(
        x,
        filters,
        pointwise_kernel_size,
        1,
        activation=None,
        bn_epsilon=bn_epsilon,
        padding=padding,
        name=f"{name}_conv_pwl",
    )
    if has_skip:
        x = layers.Add()([x, inputs])
    return x
