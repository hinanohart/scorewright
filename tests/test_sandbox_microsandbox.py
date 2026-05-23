from __future__ import annotations

import pytest

from scorewright.sandbox._microsandbox import _HAVE_MICROSANDBOX, MicrosandboxSandbox


def test_microsandbox_fails_fast() -> None:
    # In v0.1.0a1 the backend never returns a usable instance: it raises either
    # because the optional dependency is absent, or (if present) because it is an
    # interface stub. Either way, construction must fail loudly — never silently
    # hand back a non-isolating sandbox.
    with pytest.raises((RuntimeError, NotImplementedError)):
        MicrosandboxSandbox()


def test_have_flag_is_bool() -> None:
    assert isinstance(_HAVE_MICROSANDBOX, bool)
