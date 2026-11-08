from config import defaults


def make_client(**overrides):
    cfg = {
        "timeout": 60,
        "retries": 1,
    }
    cfg.update(overrides)
    return cfg