from tsumtsum_analyze import scene_labels as _src
globals().update({k: v for k, v in vars(_src).items() if not k.startswith("__")})
