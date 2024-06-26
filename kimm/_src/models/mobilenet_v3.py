import math
import pathlib
import typing
import warnings

import keras
from keras import backend
from keras import layers

from kimm._src.blocks.conv2d import apply_conv2d_block
from kimm._src.blocks.depthwise_separation import (
    apply_depthwise_separation_block,
)
from kimm._src.blocks.inverted_residual import apply_inverted_residual_block
from kimm._src.kimm_export import kimm_export
from kimm._src.models.base_model import BaseModel
from kimm._src.utils.make_divisble import make_divisible
from kimm._src.utils.model_registry import add_model_to_registry

DEFAULT_SMALL_CONFIG = [
    # type, repeat, kernel_size, strides, expansion_ratio, channels, se_ratio,
    # activation
    # stage0
    [["ds", 1, 3, 2, 1.0, 16, 0.25, "relu"]],
    # stage1
    [
        ["ir", 1, 3, 2, 4.5, 24, 0.0, "relu"],
        ["ir", 1, 3, 1, 3.67, 24, 0.0, "relu"],
    ],
    # stage2
    [
        ["ir", 1, 5, 2, 4.0, 40, 0.25, "hard_swish"],
        ["ir", 2, 5, 1, 6.0, 40, 0.25, "hard_swish"],
    ],
    # stage3
    [["ir", 2, 5, 1, 3.0, 48, 0.25, "hard_swish"]],
    # stage4
    [["ir", 3, 5, 2, 6.0, 96, 0.25, "hard_swish"]],
    # stage5
    [["cn", 1, 1, 1, 1.0, 576, 0.0, "hard_swish"]],
]
DEFAULT_LARGE_CONFIG = [
    # type, repeat, kernel_size, strides, expansion_ratio, channels, se_ratio,
    # activation
    # stage0
    [["ds", 1, 3, 1, 1.0, 16, 0.0, "relu"]],
    # stage1
    [
        ["ir", 1, 3, 2, 4.0, 24, 0.0, "relu"],
        ["ir", 1, 3, 1, 3.0, 24, 0.0, "relu"],
    ],
    # stage2
    [["ir", 3, 5, 2, 3.0, 40, 0.25, "relu"]],
    # stage3
    [
        ["ir", 1, 3, 2, 6.0, 80, 0.0, "hard_swish"],
        ["ir", 1, 3, 1, 2.5, 80, 0.0, "hard_swish"],
        ["ir", 2, 3, 1, 2.3, 80, 0.0, "hard_swish"],
    ],
    # stage4
    [["ir", 2, 3, 1, 6.0, 112, 0.25, "hard_swish"]],
    # stage5
    [["ir", 3, 5, 2, 6.0, 160, 0.25, "hard_swish"]],
    # stage6
    [["cn", 1, 1, 1, 1.0, 960, 0.0, "hard_swish"]],
]
DEFAULT_LCNET_CONFIG = [
    # type, repeat, kernel_size, strides, expansion_ratio, channels, se_ratio,
    # activation
    # stage0
    [["dsa", 1, 3, 1, 1.0, 32, 0.0, "hard_swish"]],
    # stage1
    [["dsa", 2, 3, 2, 1.0, 64, 0.0, "hard_swish"]],
    # stage2
    [["dsa", 2, 3, 2, 1.0, 128, 0.0, "hard_swish"]],
    # stage3
    [
        ["dsa", 1, 3, 2, 1.0, 256, 0.0, "hard_swish"],
        ["dsa", 1, 5, 1, 1.0, 256, 0.0, "hard_swish"],
    ],
    # stage4
    [["dsa", 4, 5, 1, 1.0, 256, 0.0, "hard_swish"]],
    # stage5
    [["dsa", 2, 5, 2, 1.0, 512, 0.25, "hard_swish"]],
]


@keras.saving.register_keras_serializable(package="kimm")
class MobileNetV3(BaseModel):
    def __init__(
        self,
        width: float = 1.0,
        depth: float = 1.0,
        fix_stem_and_head_channels: bool = False,
        config: typing.Literal["small", "large", "lcnet"] = "large",
        minimal: bool = False,
        input_tensor=None,
        **kwargs,
    ):
        _available_configs = ["small", "large", "lcnet"]
        if config == "small":
            _config = DEFAULT_SMALL_CONFIG
            conv_head_channels = 1024
        elif config == "large":
            _config = DEFAULT_LARGE_CONFIG
            conv_head_channels = 1280
        elif config == "lcnet":
            _config = DEFAULT_LCNET_CONFIG
            conv_head_channels = 1280
        else:
            raise ValueError(
                f"config must be one of {_available_configs} using string. "
                f"Received: config={config}"
            )
        if minimal:
            force_activation = "relu"
            force_kernel_size = 3
            no_se = True
        else:
            force_activation = None
            force_kernel_size = None
            no_se = False
        # TF default config
        bn_epsilon = kwargs.pop("bn_epsilon", 1e-5)
        padding = kwargs.pop("padding", None)

        self.set_properties(kwargs)
        channels_axis = (
            -1 if backend.image_data_format() == "channels_last" else -3
        )

        inputs = self.determine_input_tensor(
            input_tensor,
            self._input_shape,
            self._default_size,
        )
        x = inputs

        x = self.build_preprocessing(x, "imagenet")

        # Prepare feature extraction
        features = {}

        # stem
        stem_channel = (
            16 if fix_stem_and_head_channels else make_divisible(16 * width)
        )
        x = apply_conv2d_block(
            x,
            stem_channel,
            3,
            2,
            activation=force_activation or "hard_swish",
            bn_epsilon=bn_epsilon,
            padding=padding,
            name="conv_stem",
        )
        features["STEM_S2"] = x

        # blocks
        current_stride = 2
        for current_stage_idx, cfg in enumerate(_config):
            for current_block_idx, sub_cfg in enumerate(cfg):
                block_type, r, k, s, e, c, se, act = sub_cfg

                # override default config
                if force_activation is not None:
                    act = force_activation
                if force_kernel_size is not None:
                    k = force_kernel_size if k > force_kernel_size else k
                if no_se:
                    se = 0.0

                c = make_divisible(c * width)
                # no depth multiplier at first and last block
                if current_block_idx not in (0, len(_config) - 1):
                    r = int(math.ceil(r * depth))
                for current_layer_idx in range(r):
                    s = s if current_layer_idx == 0 else 1
                    _kwargs = {
                        "bn_epsilon": bn_epsilon,
                        "padding": padding,
                        "name": (
                            f"blocks_{current_stage_idx}_"
                            f"{current_block_idx + current_layer_idx}"
                        ),
                    }
                    if block_type in ("ds", "dsa"):
                        if block_type == "dsa":
                            has_skip = False
                        else:
                            has_skip = x.shape[channels_axis] == c and s == 1
                        x = apply_depthwise_separation_block(
                            x,
                            c,
                            k,
                            1,
                            s,
                            se,
                            act,
                            se_activation="relu",
                            se_gate_activation="hard_sigmoid",
                            se_make_divisible_number=8,
                            pw_activation=act if block_type == "dsa" else None,
                            has_skip=has_skip,
                            **_kwargs,
                        )
                    elif block_type == "ir":
                        x = apply_inverted_residual_block(
                            x,
                            c,
                            k,
                            1,
                            1,
                            s,
                            e,
                            se,
                            act,
                            se_activation="relu",
                            se_gate_activation="hard_sigmoid",
                            se_make_divisible_number=8,
                            **_kwargs,
                        )
                    elif block_type == "cn":
                        x = apply_conv2d_block(
                            x, c, k, s, activation=act, **_kwargs
                        )
                    current_stride *= s
            features[f"BLOCK{current_stage_idx}_S{current_stride}"] = x

        # Head
        if self._include_top:
            if fix_stem_and_head_channels:
                conv_head_channels = conv_head_channels
            else:
                conv_head_channels = max(
                    conv_head_channels,
                    make_divisible(conv_head_channels * width),
                )
            head_activation = force_activation or "hard_swish"
            x = self.build_top(
                x,
                self._classes,
                self._classifier_activation,
                self._dropout_rate,
                conv_head_channels=conv_head_channels,
                head_activation=head_activation,
            )
        else:
            if self._pooling == "avg":
                x = layers.GlobalAveragePooling2D(name="avg_pool")(x)
            elif self._pooling == "max":
                x = layers.GlobalMaxPooling2D(name="max_pool")(x)

        super().__init__(inputs=inputs, outputs=x, features=features, **kwargs)

        # All references to `self` below this line
        self.width = width
        self.depth = depth
        self.fix_stem_and_head_channels = fix_stem_and_head_channels
        self.config = config
        self.minimal = minimal

    def build_top(
        self,
        inputs,
        classes,
        classifier_activation,
        dropout_rate,
        conv_head_channels,
        head_activation,
    ):
        x = layers.GlobalAveragePooling2D(name="avg_pool", keepdims=True)(
            inputs
        )
        x = layers.Conv2D(
            conv_head_channels, 1, 1, use_bias=True, name="conv_head"
        )(x)
        x = layers.Activation(head_activation, name="act2")(x)
        x = layers.Flatten()(x)
        x = layers.Dropout(rate=dropout_rate, name="conv_head_dropout")(x)
        x = layers.Dense(
            classes, activation=classifier_activation, name="classifier"
        )(x)
        return x

    def get_config(self):
        config = super().get_config()
        config.update(
            {
                "width": self.width,
                "depth": self.depth,
                "fix_stem_and_head_channels": self.fix_stem_and_head_channels,
                "config": self.config,
                "minimal": self.minimal,
            }
        )
        return config

    def fix_config(self, config):
        unused_kwargs = [
            "width",
            "depth",
            "fix_stem_and_head_channels",
            "config",
            "minimal",
        ]
        for k in unused_kwargs:
            config.pop(k, None)
        return config


# Model Definition


class MobileNetV3Variant(MobileNetV3):
    # Parameters
    width = None
    depth = None
    fix_stem_and_head_channels = None
    config = None

    def __init__(
        self,
        input_tensor: typing.Optional[keras.KerasTensor] = None,
        input_shape: typing.Optional[typing.Sequence[int]] = None,
        include_preprocessing: bool = True,
        include_top: bool = True,
        pooling: typing.Optional[str] = None,
        dropout_rate: float = 0.0,
        classes: int = 1000,
        classifier_activation: str = "softmax",
        weights: typing.Optional[typing.Union[str, pathlib.Path]] = "imagenet",
        name: typing.Optional[str] = None,
        feature_extractor: bool = False,
        feature_keys: typing.Optional[typing.Sequence[str]] = None,
        **kwargs,
    ):
        """Instantiates the MobileNetV3 or LCNet architecture.

        Reference:
        - [Searching for MobileNetV3 (ICCV 2019)](https://arxiv.org/abs/1905.02244)
        - [PP-LCNet: A Lightweight CPU Convolutional Neural Network
        (arXiv 2021)](https://arxiv.org/abs/2109.15099)

        Args:
            input_tensor: An optional `keras.KerasTensor` specifying the input.
            input_shape: An optional sequence of ints specifying the input
                shape.
            include_preprocessing: Whether to include preprocessing. Defaults
                to `True`.
            include_top: Whether to include prediction head. Defaults
                to `True`.
            pooling: An optional `str` specifying the pooling type on top of
                the model. This argument only takes effect if
                `include_top=False`. Available values are `"avg"` and `"max"`
                which correspond to `GlobalAveragePooling2D` and
                `GlobalMaxPooling2D`, respectively. Defaults to `None`.
            dropout_rate: A `float` specifying the dropout rate in prediction
                head. This argument only takes effect if `include_top=True`.
                Defaults to `0.0`.
            classes: An `int` specifying the number of classes. Defaults to
                `1000` for ImageNet.
            classifier_activation: A `str` specifying the activation
                function of the final output. Defaults to `"softmax"`.
            weights: An optional `str` or `pathlib.Path` specifying the name,
                url or path of the pretrained weights. Defaults to `"imagenet"`.
            name: An optional `str` specifying the name of the model. If not
                specified, it will be the class name. Defaults to `None`.
            feature_extractor: Whether to enable feature extraction. If `True`,
                the outputs will be a `dict` that keys are feature names and
                values are feature maps. Defaults to `False`.
            feature_keys: An optional sequence of strings specifying the
                selected feature names. This argument only takes effect if
                `feature_extractor=True`. Defaults to `None`.

        Returns:
            A `keras.Model` instance.
        """
        if type(self) is MobileNetV3Variant:
            raise NotImplementedError(
                f"Cannot instantiate base class: {self.__class__.__name__}. "
                "You should use its subclasses."
            )
        kwargs = self.fix_config(kwargs)
        if hasattr(self, "minimal"):
            kwargs["minimal"] = self.minimal
        if hasattr(self, "bn_epsilon"):
            kwargs["bn_epsilon"] = self.bn_epsilon
        if hasattr(self, "padding"):
            kwargs["padding"] = self.padding
        if len(getattr(self, "available_weights", [])) == 0:
            warnings.warn(
                f"{self.__class__.__name__} doesn't have pretrained weights "
                f"for '{weights}'."
            )
            weights = None
        super().__init__(
            width=self.width,
            depth=self.depth,
            fix_stem_and_head_channels=self.fix_stem_and_head_channels,
            config=self.config,
            input_tensor=input_tensor,
            input_shape=input_shape,
            include_preprocessing=include_preprocessing,
            include_top=include_top,
            pooling=pooling,
            dropout_rate=dropout_rate,
            classes=classes,
            classifier_activation=classifier_activation,
            weights=weights,
            name=name or str(self.__class__.__name__),
            feature_extractor=feature_extractor,
            feature_keys=feature_keys,
            **kwargs,
        )


@kimm_export(parent_path=["kimm.models", "kimm.models.mobilenet_v3"])
class MobileNetV3W050Small(MobileNetV3Variant):
    available_feature_keys = [
        "STEM_S2",
        *[f"BLOCK{i}_S{j}" for i, j in zip(range(6), [4, 8, 16, 16, 32, 32])],
    ]
    available_weights = [
        (
            "imagenet",
            MobileNetV3.default_origin,
            "mobilenet050v3small_mobilenetv3_small_050.lamb_in1k.keras",
        )
    ]

    # Parameters
    width = 0.5
    depth = 1.0
    fix_stem_and_head_channels = True
    config = "small"


@kimm_export(parent_path=["kimm.models", "kimm.models.mobilenet_v3"])
class MobileNetV3W075Small(MobileNetV3Variant):
    available_feature_keys = [
        "STEM_S2",
        *[f"BLOCK{i}_S{j}" for i, j in zip(range(6), [4, 8, 16, 16, 32, 32])],
    ]
    available_weights = [
        (
            "imagenet",
            MobileNetV3.default_origin,
            "mobilenet075v3small_mobilenetv3_small_075.lamb_in1k.keras",
        )
    ]

    # Parameters
    width = 0.75
    depth = 1.0
    fix_stem_and_head_channels = False
    config = "small"


@kimm_export(parent_path=["kimm.models", "kimm.models.mobilenet_v3"])
class MobileNetV3W100Small(MobileNetV3Variant):
    available_feature_keys = [
        "STEM_S2",
        *[f"BLOCK{i}_S{j}" for i, j in zip(range(6), [4, 8, 16, 16, 32, 32])],
    ]
    available_weights = [
        (
            "imagenet",
            MobileNetV3.default_origin,
            "mobilenet100v3small_mobilenetv3_small_100.lamb_in1k.keras",
        )
    ]

    # Parameters
    width = 1.0
    depth = 1.0
    fix_stem_and_head_channels = False
    config = "small"


@kimm_export(parent_path=["kimm.models", "kimm.models.mobilenet_v3"])
class MobileNetV3W100SmallMinimal(MobileNetV3Variant):
    available_feature_keys = [
        "STEM_S2",
        *[f"BLOCK{i}_S{j}" for i, j in zip(range(6), [4, 8, 16, 16, 32, 32])],
    ]
    available_weights = [
        (
            "imagenet",
            MobileNetV3.default_origin,
            (
                "mobilenet100v3smallminimal_"
                "tf_mobilenetv3_small_minimal_100.in1k.keras"
            ),
        )
    ]

    # Parameters
    width = 1.0
    depth = 1.0
    fix_stem_and_head_channels = False
    config = "small"
    minimal = True
    bn_epsilon = 1e-3
    padding = "same"


@kimm_export(parent_path=["kimm.models", "kimm.models.mobilenet_v3"])
class MobileNetV3W100Large(MobileNetV3Variant):
    available_feature_keys = [
        "STEM_S2",
        *[
            f"BLOCK{i}_S{j}"
            for i, j in zip(range(7), [2, 4, 8, 16, 16, 32, 32])
        ],
    ]
    available_weights = [
        (
            "imagenet",
            MobileNetV3.default_origin,
            (
                "mobilenet100v3large_"
                "mobilenetv3_large_100.miil_in21k_ft_in1k.keras"
            ),
        )
    ]

    # Parameters
    width = 1.0
    depth = 1.0
    fix_stem_and_head_channels = False
    config = "large"

    def build_preprocessing(self, inputs, mode="imagenet"):
        if (
            self._weights_url is not None
            and "miil_in21k_ft_in1k" in self._weights_url
        ):
            """`miil_in21k_ft_in1k` needs `0_1`"""
            return super().build_preprocessing(inputs, "0_1")
        else:
            return super().build_preprocessing(inputs, mode)


@kimm_export(parent_path=["kimm.models", "kimm.models.mobilenet_v3"])
class MobileNetV3W100LargeMinimal(MobileNetV3Variant):
    available_feature_keys = [
        "STEM_S2",
        *[
            f"BLOCK{i}_S{j}"
            for i, j in zip(range(7), [2, 4, 8, 16, 16, 32, 32])
        ],
    ]
    available_weights = [
        (
            "imagenet",
            MobileNetV3.default_origin,
            (
                "mobilenet100v3largeminimal_"
                "tf_mobilenetv3_large_minimal_100.in1k.keras"
            ),
        )
    ]

    # Parameters
    width = 1.0
    depth = 1.0
    fix_stem_and_head_channels = False
    config = "large"
    minimal = True
    bn_epsilon = 1e-3
    padding = "same"


@kimm_export(parent_path=["kimm.models", "kimm.models.mobilenet_v3"])
class LCNet035(MobileNetV3Variant):
    available_feature_keys = [
        "STEM_S2",
        *[f"BLOCK{i}_S{j}" for i, j in zip(range(6), [2, 4, 8, 16, 16, 32])],
    ]
    available_weights = []

    # Parameters
    width = 0.35
    depth = 1.0
    fix_stem_and_head_channels = False
    config = "lcnet"


@kimm_export(parent_path=["kimm.models", "kimm.models.mobilenet_v3"])
class LCNet050(MobileNetV3Variant):
    available_feature_keys = [
        "STEM_S2",
        *[f"BLOCK{i}_S{j}" for i, j in zip(range(6), [2, 4, 8, 16, 16, 32])],
    ]
    available_weights = [
        (
            "imagenet",
            MobileNetV3.default_origin,
            "lcnet050_lcnet_050.ra2_in1k.keras",
        )
    ]

    # Parameters
    width = 0.5
    depth = 1.0
    fix_stem_and_head_channels = False
    config = "lcnet"


@kimm_export(parent_path=["kimm.models", "kimm.models.mobilenet_v3"])
class LCNet075(MobileNetV3Variant):
    available_feature_keys = [
        "STEM_S2",
        *[f"BLOCK{i}_S{j}" for i, j in zip(range(6), [2, 4, 8, 16, 16, 32])],
    ]
    available_weights = [
        (
            "imagenet",
            MobileNetV3.default_origin,
            "lcnet075_lcnet_075.ra2_in1k.keras",
        )
    ]

    # Parameters
    width = 0.75
    depth = 1.0
    fix_stem_and_head_channels = False
    config = "lcnet"


@kimm_export(parent_path=["kimm.models", "kimm.models.mobilenet_v3"])
class LCNet100(MobileNetV3Variant):
    available_feature_keys = [
        "STEM_S2",
        *[f"BLOCK{i}_S{j}" for i, j in zip(range(6), [2, 4, 8, 16, 16, 32])],
    ]
    available_weights = [
        (
            "imagenet",
            MobileNetV3.default_origin,
            "lcnet100_lcnet_100.ra2_in1k.keras",
        )
    ]

    # Parameters
    width = 1.0
    depth = 1.0
    fix_stem_and_head_channels = False
    config = "lcnet"


@kimm_export(parent_path=["kimm.models", "kimm.models.mobilenet_v3"])
class LCNet150(MobileNetV3):
    available_feature_keys = [
        "STEM_S2",
        *[
            f"BLOCK{i}_S{j}"
            for i, j in zip(range(7), [2, 4, 8, 16, 16, 32, 32])
        ],
    ]
    available_weights = []

    # Parameters
    width = 1.5
    depth = 1.0
    fix_stem_and_head_channels = False
    config = "lcnet"


add_model_to_registry(MobileNetV3W050Small, "imagenet")
add_model_to_registry(MobileNetV3W075Small, "imagenet")
add_model_to_registry(MobileNetV3W100Small, "imagenet")
add_model_to_registry(MobileNetV3W100SmallMinimal, "imagenet")
add_model_to_registry(MobileNetV3W100Large, "imagenet")
add_model_to_registry(MobileNetV3W100LargeMinimal, "imagenet")
add_model_to_registry(LCNet035)
add_model_to_registry(LCNet050, "imagenet")
add_model_to_registry(LCNet075, "imagenet")
add_model_to_registry(LCNet100, "imagenet")
add_model_to_registry(LCNet150)
