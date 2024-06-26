import sys
import typing
import warnings

from kimm._src.kimm_export import kimm_export

# {
#     "name",  # str
#     "feature_extractor",  # bool
#     "feature_keys",  # list of str
#     "weights",  # None or str
# }
MODEL_REGISTRY: typing.List[typing.Dict[str, typing.Union[str, bool]]] = []


def _match_string(query: str, target: str):
    query = query.lower().replace(" ", "").replace("_", "").replace(".", "")
    target = target.lower()
    matched_idx = -1
    for q_char in query:
        matched = False
        for idx, t_char in enumerate(target):
            if matched:
                break
            if q_char == t_char and idx > matched_idx:
                matched_idx = idx
                matched = True
        if not matched:
            return False
    return True


def clear_registry():
    MODEL_REGISTRY.clear()


def add_model_to_registry(model_cls, weights: typing.Optional[str] = None):
    from kimm._src.models.base_model import BaseModel

    # Deal with __all__
    mod = sys.modules[model_cls.__module__]
    model_name = model_cls.__name__
    if hasattr(mod, "__all__"):
        mod.__all__.append(model_name)
    else:
        mod.__all__ = [model_name]

    # Add model information
    feature_extractor = False
    feature_keys = []
    if issubclass(model_cls, BaseModel):
        feature_extractor = True
        feature_keys = model_cls.available_feature_keys
    for info in MODEL_REGISTRY:
        if info["name"] == model_cls.__name__:
            warnings.warn(
                f"MODEL_REGISTRY already contains name={model_cls.__name__}!"
            )
    if weights is not None:
        if not isinstance(weights, str):
            raise ValueError(
                "`weights` must be one of (None, str). "
                f"Recieved: weight={weights}"
            )
        weights = weights.lower()
    MODEL_REGISTRY.append(
        {
            "name": model_cls.__name__,
            "feature_extractor": feature_extractor,
            "feature_keys": feature_keys,
            "weights": weights,
        }
    )


@kimm_export(parent_path=["kimm", "kimm.utils"])
def list_models(
    name: typing.Optional[str] = None,
    feature_extractor: typing.Optional[bool] = None,
    weights: typing.Optional[typing.Union[bool, str]] = None,
):
    """List the models with the given arguments.

    Args:
        name: An optional `str` specifying the substring of the name of the
            model to seatch for. If not specified, all models will be included.
        feature_extractor: Whether to include models that support
            feature extraction. Defaults to `None`, which means this
            argument is not considered.
        weights: An optional boolean or `str` specifying the name of the
            pretrained weights. The available values are (`"imagenet"`).
            Defaults to `None`, which means this argument is not considered.

    Returns:
        A list of model names.
    """
    result_names: typing.Set[str] = set()
    for info in MODEL_REGISTRY:
        # Add by default
        result_names.add(info["name"])
        need_remove = False

        # Match string (simple implementation)
        if name is not None:
            need_remove = not _match_string(name, info["name"])

        # Filter by feature_extractor and weights
        if (
            feature_extractor is not None
            and info["feature_extractor"] is not feature_extractor
        ):
            need_remove = True
        if weights is not None and info["weights"] != weights:
            if weights is True and info["weights"] is None:
                need_remove = True
            elif weights is False and info["weights"] is not None:
                need_remove = True
            elif isinstance(weights, str):
                if weights.lower() != info["weights"]:
                    need_remove = True
        if need_remove:
            result_names.remove(info["name"])
    return sorted(result_names)
