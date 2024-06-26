"""
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install timm
"""

import os

import keras
import numpy as np
import timm
import torch

from kimm.models import mobilenet_v3
from kimm.timm_utils import assign_weights
from kimm.timm_utils import is_same_weights
from kimm.timm_utils import separate_keras_weights
from kimm.timm_utils import separate_torch_state_dict

timm_model_names = [
    "mobilenetv3_small_050.lamb_in1k",
    "mobilenetv3_small_075.lamb_in1k",
    "tf_mobilenetv3_small_minimal_100.in1k",
    "mobilenetv3_small_100.lamb_in1k",
    "mobilenetv3_large_100.miil_in21k_ft_in1k",
    "tf_mobilenetv3_large_minimal_100.in1k",
    "lcnet_050.ra2_in1k",
    "lcnet_075.ra2_in1k",
    "lcnet_100.ra2_in1k",
]
keras_model_classes = [
    mobilenet_v3.MobileNetV3W050Small,
    mobilenet_v3.MobileNetV3W075Small,
    mobilenet_v3.MobileNetV3W100SmallMinimal,
    mobilenet_v3.MobileNetV3W100Small,
    mobilenet_v3.MobileNetV3W100Large,
    mobilenet_v3.MobileNetV3W100LargeMinimal,
    mobilenet_v3.LCNet050,
    mobilenet_v3.LCNet075,
    mobilenet_v3.LCNet100,
]

for timm_model_name, keras_model_class in zip(
    timm_model_names, keras_model_classes
):
    """
    Prepare timm model and keras model
    """
    input_shape = [224, 224, 3]
    torch_model = timm.create_model(timm_model_name, pretrained=True)
    torch_model = torch_model.eval()
    trainable_state_dict, non_trainable_state_dict = separate_torch_state_dict(
        torch_model.state_dict()
    )
    keras_model = keras_model_class(
        input_shape=input_shape,
        include_preprocessing=False,
        classifier_activation="linear",
        weights=None,
    )
    trainable_weights, non_trainable_weights = separate_keras_weights(
        keras_model
    )

    # for torch_name, (_, keras_name) in zip(
    #     trainable_state_dict.keys(), trainable_weights
    # ):
    #     print(f"{torch_name}    {keras_name}")

    # print(len(trainable_state_dict.keys()))
    # print(len(trainable_weights))

    # exit()

    """
    Assign weights
    """
    for keras_weight, keras_name in trainable_weights + non_trainable_weights:
        keras_name: str
        torch_name = keras_name
        torch_name = torch_name.replace("_", ".")
        # stem
        torch_name = torch_name.replace("conv.stem.conv2d", "conv_stem")
        torch_name = torch_name.replace("conv.stem.bn", "bn1")
        # LCNet
        if "LCNet" in keras_model_class.__name__:
            # depthwise separation block
            torch_name = torch_name.replace("conv.dw.dwconv2d", "conv_dw")
            torch_name = torch_name.replace("conv.dw.bn", "bn1")
            torch_name = torch_name.replace("conv.pw.conv2d", "conv_pw")
            torch_name = torch_name.replace("conv.pw.bn", "bn2")
        # blocks
        if "blocks.0.0" in torch_name:
            # depthwise separation block
            torch_name = torch_name.replace("conv.dw.dwconv2d", "conv_dw")
            torch_name = torch_name.replace("conv.dw.bn", "bn1")
            torch_name = torch_name.replace("conv.pw.conv2d", "conv_pw")
            torch_name = torch_name.replace("conv.pw.bn", "bn2")
        else:
            # inverted residual block
            torch_name = torch_name.replace("conv.pw.conv2d", "conv_pw")
            torch_name = torch_name.replace("conv.pw.bn", "bn1")
            torch_name = torch_name.replace("conv.dw.dwconv2d", "conv_dw")
            torch_name = torch_name.replace("conv.dw.bn", "bn2")
            torch_name = torch_name.replace("conv.pwl.conv2d", "conv_pwl")
            torch_name = torch_name.replace("conv.pwl.bn", "bn3")
        # se
        torch_name = torch_name.replace("se.conv.reduce", "se.conv_reduce")
        torch_name = torch_name.replace("se.conv.expand", "se.conv_expand")
        # last conv block
        if "Small" in keras_model_class.__name__:
            if "blocks.5.0" in torch_name:
                torch_name = torch_name.replace("conv2d", "conv")
                torch_name = torch_name.replace("bn", "bn1")
        if "Large" in keras_model_class.__name__:
            if "blocks.6.0" in torch_name:
                torch_name = torch_name.replace("conv2d", "conv")
                torch_name = torch_name.replace("bn", "bn1")
        # conv head
        torch_name = torch_name.replace("conv.head", "conv_head")

        # weights naming mapping
        torch_name = torch_name.replace("kernel", "weight")  # conv2d
        torch_name = torch_name.replace("gamma", "weight")  # bn
        torch_name = torch_name.replace("beta", "bias")  # bn
        torch_name = torch_name.replace("moving.mean", "running_mean")  # bn
        torch_name = torch_name.replace("moving.variance", "running_var")  # bn

        # assign weights
        if torch_name in trainable_state_dict:
            torch_weights = trainable_state_dict[torch_name].numpy()
        elif torch_name in non_trainable_state_dict:
            torch_weights = non_trainable_state_dict[torch_name].numpy()
        else:
            raise ValueError(
                "Can't find the corresponding torch weights. "
                f"Got keras_name={keras_name}, torch_name={torch_name}"
            )
        if is_same_weights(keras_name, keras_weight, torch_name, torch_weights):
            assign_weights(keras_name, keras_weight, torch_weights)
        else:
            raise ValueError(
                "Can't find the corresponding torch weights. The shape is "
                f"mismatched. Got keras_name={keras_name}, "
                f"keras_weight shape={keras_weight.shape}, "
                f"torch_name={torch_name}, "
                f"torch_weights shape={torch_weights.shape}"
            )

    """
    Verify model outputs
    """
    np.random.seed(2023)
    keras_data = np.random.uniform(size=[1] + input_shape).astype("float32")
    torch_data = torch.from_numpy(np.transpose(keras_data, [0, 3, 1, 2]))
    torch_y = torch_model(torch_data)
    keras_y = keras_model(keras_data, training=False)
    torch_y = torch_y.detach().cpu().numpy()
    keras_y = keras.ops.convert_to_numpy(keras_y)
    np.testing.assert_allclose(torch_y, keras_y, atol=1e-4)
    print(f"{keras_model_class.__name__}: output matched!")

    """
    Save converted model
    """
    os.makedirs("exported", exist_ok=True)
    export_path = f"exported/{keras_model.name.lower()}_{timm_model_name}.keras"
    keras_model.save(export_path)
    print(f"Export to {export_path}")
