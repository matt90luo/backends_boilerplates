"""Readiness probe aggregation for ``/readyz``."""

from __future__ import annotations

from collections.abc import Sequence

from tinysaas.application.dto.files import ReadinessReport
from tinysaas.application.ports.external import ReadinessProbe


class CheckReadinessUseCase:
    """Ask every dependency that must be up before serving traffic."""

    def __init__(self, *, probes: Sequence[ReadinessProbe]) -> None:
        self._probes = probes

    async def execute(self) -> ReadinessReport:
        components: dict[str, str] = {}
        for probe in self._probes:
            try:
                await probe.ping()
            except Exception as error:  # noqa: BLE001 - the report carries the reason
                components[probe.name] = f"error: {error}"
            else:
                components[probe.name] = "ok"
        status = "ok" if all(value == "ok" for value in components.values()) else "degraded"
        return ReadinessReport(status=status, components=components)
