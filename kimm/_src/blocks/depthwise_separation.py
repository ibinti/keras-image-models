import typing

from keras import backend
from keras import layers

from kimm._src.blocks.conv2d import apply_conv2d_block
from kimm._src.blocks.squeeze_and_excitation import apply_se_block
from kimm._src.kimm_export import kimm_export


@kimm_export(parent_path=["kimm.blocks"])
def apply_depthwise_separation_block(
    inputs,
    filters: int,
    depthwise_kernel_size: int = 3,
    pointwise_kernel_size: int = 1,
    strides: int = 1,
    se_ratio: float = 0.0,
    activation: typing.Optional[str] = "swish",
    se_activation: typing.Optional[str] = "relu",
    se_gate_activation: typing.Optional[str] = "sigmoid",
    se_make_divisible_number: typing.Optional[int] = None,
    pw_activation: typing.Optional[str] = None,
    has_skip: bool = True,
    bn_epsilon: float = 1e-5,
    padding: typing.Optional[typing.Literal["same", "valid"]] = None,
    name: str = "depthwise_separation_block",
):
    """Conv2D block + (SqueezeAndExcitation) + Conv2D."""
    channels_axis = -1 if backend.image_data_format() == "channels_last" else -3
    input_filters = inputs.shape[channels_axis]
    if has_skip and (strides != 1 or input_filters != filters):
        raise ValueError(
            "If `has_skip=True`, strides must be 1 and `filters` must be the "
            "same as input_filters. "
            f"Received: strides={strides}, filters={filters}, "
            f"input_filters={input_filters}"
        )

    x = inputs
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
    if se_ratio > 0:
        x = apply_se_block(
            x,
            se_ratio,
            activation=se_activation,
            gate_activation=se_gate_activation,
            make_divisible_number=se_make_divisible_number,
            name=f"{name}_se",
        )
    x = apply_conv2d_block(
        x,
        filters,
        pointwise_kernel_size,
        1,
        activation=pw_activation,
        bn_epsilon=bn_epsilon,
        padding=padding,
        name=f"{name}_conv_pw",
    )
    if has_skip:
        x = layers.Add()([x, inputs])
    return x
