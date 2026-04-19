"""In-memory `Ports` fakes for use in unit tests.

Every fake satisfies the matching Protocol from `termiclaw.ports`. They
use constructor-scripted responses — no patching, no monkey-patching.
"""

from __future__ import annotations

from tests.unit.fakes.artifacts import FakeArtifactsPort
from tests.unit.fakes.container import FakeContainerPort
from tests.unit.fakes.persistence import FakePersistencePort
from tests.unit.fakes.planner import FakePlannerPort
from tests.unit.fakes.summarize import FakeSummarizePort
from tests.unit.fakes.wire import build_fake_ports

__all__ = [
    "FakeArtifactsPort",
    "FakeContainerPort",
    "FakePersistencePort",
    "FakePlannerPort",
    "FakeSummarizePort",
    "build_fake_ports",
]
