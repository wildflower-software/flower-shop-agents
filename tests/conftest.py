import os

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from pydantic_ai import models  # noqa: E402

models.ALLOW_MODEL_REQUESTS = False  # tests never call a real model
