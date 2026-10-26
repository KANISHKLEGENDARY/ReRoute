"""
App package initialization.
Provides pure-Python fallback for uuid_utils on Windows if native DLL is blocked by AppLocker.
"""

import sys

try:
    import uuid_utils  # noqa: F401
except ImportError:
    import types
    import uuid

    m = types.ModuleType("uuid_utils")
    m.UUID, m.uuid1, m.uuid3, m.uuid4, m.uuid5 = (
        uuid.UUID,
        uuid.uuid1,
        uuid.uuid3,
        uuid.uuid4,
        uuid.uuid5,
    )
    m.uuid7, m.uuid8 = lambda: uuid.uuid4(), lambda: uuid.uuid4()
    compat = types.ModuleType("uuid_utils.compat")
    compat.uuid7, compat.UUID = lambda: uuid.uuid4(), uuid.UUID
    m.compat = compat
    sys.modules["uuid_utils"] = m
    sys.modules["uuid_utils.compat"] = compat
