import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def enforce_test_offline_mode() -> None:
    """Đảm bảo kiểm thử tự động luôn chạy ở chế độ offline/replay theo Rule 10 AGENTS.md."""
    os.environ["LLM_MODE"] = "replay"
