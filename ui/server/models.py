"""Video and image models a job can use. `version` selects the script's rules (durations, resolutions, features);
`endpoint` is the account's ModelArk inference endpoint sent as the model ID (None = the public model ID)."""
from __future__ import annotations

VIDEO_MODELS = {
    "seedance-2.5": {"label": "Seedance 2.5", "version": "2.5", "endpoint": None},
    "seedance-2.0": {"label": "Seedance 2.0", "version": "2.0", "endpoint": "ep-20261025002644-wf5mn"},
    "seedance-2.0-fast": {"label": "Seedance 2.0 fast", "version": "2.0-fast", "endpoint": "ep-20261025003119-glwxh"},
    "seedance-2.0-mini": {"label": "Seedance 2.0 mini", "version": "2.0-mini", "endpoint": "ep-20261025003010-z2gxf"},
}
IMAGE_MODELS = {
    "seedream-5.0-pro": {"label": "Seedream 5.0 pro", "version": "5.0-pro", "endpoint": None},
    "seedream-5.0-flash": {"label": "Seedream 5.0 flash", "version": "5.0-flash", "endpoint": "ep-20261007114205-q4znt"},
}
DEFAULT_VIDEO = "seedance-2.5"
DEFAULT_IMAGE = "seedream-5.0-pro"


def flags(entry: dict) -> str:
    """The command-line flags every generate-with-seedance / generate-with-seedream call must carry."""
    return f"--version {entry['version']}" + (f" --model {entry['endpoint']}" if entry.get("endpoint") else "")
