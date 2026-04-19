"""Glue that builds a full `Ports` bundle from fakes with one call."""

from __future__ import annotations

from termiclaw.ports import Ports
from tests.unit.fakes.artifacts import FakeArtifactsPort
from tests.unit.fakes.container import FakeContainerPort
from tests.unit.fakes.persistence import FakePersistencePort
from tests.unit.fakes.planner import FakePlannerPort
from tests.unit.fakes.summarize import FakeSummarizePort


def build_fake_ports(
    *,
    container: FakeContainerPort | None = None,
    planner: FakePlannerPort | None = None,
    persistence: FakePersistencePort | None = None,
    artifacts: FakeArtifactsPort | None = None,
    summarize: FakeSummarizePort | None = None,
) -> Ports:
    """Return a fully-wired `Ports` with defaults for any port not passed."""
    return Ports(
        container=container or FakeContainerPort(),
        planner=planner or FakePlannerPort(),
        persistence=persistence or FakePersistencePort(),
        artifacts=artifacts or FakeArtifactsPort(),
        summarize=summarize or FakeSummarizePort(),
    )
