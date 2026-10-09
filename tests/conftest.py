import os
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent / "example"

# Must be set before any slidemage module computes PROJECT_ROOT at import.
os.environ["SLIDEMASTER_PROJECT"] = str(EXAMPLE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest  # noqa: E402 -- after the environment setup above


@pytest.fixture(autouse=True)
def _no_cloud_credentials(monkeypatch):
    """No test may find a real Anthropic key (environment or keychain), so
    none can reach the network by accident; tests that need a key set one
    explicitly."""
    from slidemage.ai import credentials

    monkeypatch.delenv(credentials.ENV_VAR, raising=False)
    monkeypatch.setattr(credentials, "_keyring", lambda: None)
