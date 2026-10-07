"""Repository-level pytest bootstrap, loaded before ``tests/conftest.py``.

Importing the original Qt UI creates its shared operational store at
``<INVSYS_HOME>/data/inventory.db``. This file runs before any
``inventory_control`` import and unconditionally points ``INVSYS_HOME`` at a
throwaway directory, so a test run can never open, migrate, or write the real
operational database or leave files in the checkout. CI asserts the working tree
is unchanged after the suite.
"""

import os
import shutil
import tempfile

_TEST_HOME = tempfile.mkdtemp(prefix="invsys-tests-")
os.environ["INVSYS_HOME"] = _TEST_HOME
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def pytest_unconfigure(config):
    shutil.rmtree(_TEST_HOME, ignore_errors=True)
