from tsumtsum_analyze import coin_read as _src
globals().update({k: v for k, v in vars(_src).items() if not k.startswith("__")})
