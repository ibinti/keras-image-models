import typing

from keras import backend
from keras import layers

from kimm._src.kimm_export import kimm_export
from kimm._src.layers.attention import Attention


@kimm_export(parent_path=["kimm.blocks"])
def apply_mlp_block(
    inputs,
    hidden_dim: int,
    output_dim: typing.Optional[int] = None,
    activation: str = "gelu",
    use_bias: bool = True,
    dropout_rate: float = 0.0,
    use_conv_mlp: bool = False,
    data_format: typing.Optional[str] = None,
    name: str = "mlp_block",
):
    """Dense/Conv2D + Activation + Dense/Conv2D."""
    if data_format is None:
        data_format = backend.image_data_format()
    dim_axis = -1 if data_format == "channels_last" else 1
    input_dim = inputs.shape[dim_axis]
    output_dim = output_dim or input_dim

    x = inputs
    if use_conv_mlp:
        x = layers.Conv2D(
            hidden_dim, 1, use_bias=use_bias, name=f"{name}_fc1_conv2d"
        )(x)
    else:
        x = layers.Dense(hidden_dim, use_bias=use_bias, name=f"{name}_fc1")(x)
    x = layers.Activation(activation, name=f"{name}_act")(x)
    x = layers.Dropout(dropout_rate, name=f"{name}_drop1")(x)
    if use_conv_mlp:
        x = layers.Conv2D(
            output_dim, 1, use_bias=use_bias, name=f"{name}_fc2_conv2d"
        )(x)
    else:
        x = layers.Dense(output_dim, use_bias=use_bias, name=f"{name}_fc2")(x)
    x = layers.Dropout(dropout_rate, name=f"{name}_drop2")(x)
    return x


@kimm_export(parent_path=["kimm.blocks"])
def apply_transformer_block(
    inputs,
    dim: int,
    num_heads: int,
    mlp_ratio: float = 4.0,
    use_qkv_bias: bool = False,
    projection_dropout_rate: float = 0.0,
    attention_dropout_rate: float = 0.0,
    activation: str = "gelu",
    name: str = "transformer_block",
):
    """LN + Attention + LN + MLP block."""
    # data_format must be "channels_last"
    x = inputs
    residual_1 = x

    x = layers.LayerNormalization(epsilon=1e-6, name=f"{name}_norm1")(x)
    x = Attention(
        dim,
        num_heads,
        use_qkv_bias,
        attention_dropout_rate,
        projection_dropout_rate,
        name=f"{name}_attn",
    )(x)
    x = layers.Add()([residual_1, x])

    residual_2 = x
    x = layers.LayerNormalization(epsilon=1e-6, name=f"{name}_norm2")(x)
    x = apply_mlp_block(
        x,
        int(dim * mlp_ratio),
        activation=activation,
        dropout_rate=projection_dropout_rate,
        data_format="channels_last",
        name=f"{name}_mlp",
    )
    x = layers.Add()([residual_2, x])
    return x
