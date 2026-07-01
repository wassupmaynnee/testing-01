"""Root conftest — make the repo importable as the `saas` package root under a
bare ``pytest`` invocation (what CI runs), not only ``python -m pytest``.

``python -m pytest`` prepends the current directory to ``sys.path``; a bare
``pytest`` does not, so ``tests/conftest.py``'s ``import saas`` fails in CI with
``ModuleNotFoundError: No module named 'saas'``. This root conftest loads before
``tests/conftest.py`` and inserts the repo root, fixing both invocations without
touching any runtime code.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
