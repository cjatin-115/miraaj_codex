from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


@pytest.fixture
def tmp_path():
    # Keep test artifacts inside the permitted project directory on locked-down Windows hosts.
    with TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
        yield Path(directory)
