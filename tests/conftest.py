import os
import sys
import tempfile

# Eigenes Datenverzeichnis, bevor die App importiert wird
os.environ["DIKTYO_DATA"] = tempfile.mkdtemp(prefix="diktyo-test-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Das Login-Limit gilt pro IP; im Test kommen alle Anfragen vom selben Client."""
    from app import auth
    auth._attempts.clear()
    yield
