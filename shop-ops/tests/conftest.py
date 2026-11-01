import os

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import pytest
from pydantic_ai import models

from shop_ops.config import load_config
from shop_ops.db import connect, init_schema

models.ALLOW_MODEL_REQUESTS = False  # tests never call a real model


@pytest.fixture
def conn():
    c = connect(":memory:")
    init_schema(c)
    load_config(c)
    yield c
    c.close()
