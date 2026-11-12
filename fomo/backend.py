"""Data sources for the TUI: the real Azure APIs or the built-in demo data.

``PimApp`` picks one backend at start-up and screens call ``self.app.backend``
instead of branching on demo mode themselves.

A backend performs no I/O of its own.  ``AzureBackend`` delegates to
``fomo.azure``, which remains the only module that talks to Azure, and
``DemoBackend`` returns the static data in ``fomo.demo``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from fomo import azure
from fomo import demo as demo_data

DeviceCodeCallback = Callable[[str], None]


class Backend:
    """Base class for TUI data sources.

    Activation always goes through ``fomo.azure`` with :attr:`dry_run`, so a
    backend that forces dry-run never submits a real request.
    """

    #: Whether optional downloads (tier data) may use the network.  Screens
    #: pass it to ``tiering.ensure_*_loaded``; demo mode reads only the cache.
    allow_network: bool = True

    def __init__(self, dry_run: bool) -> None:
        self._dry_run = dry_run

    @property
    def dry_run(self) -> bool:
        """True when activation requests are simulated instead of submitted."""
        return self._dry_run

    # -- listings ------------------------------------------------------

    def list_subscriptions(self) -> list[azure.Subscription]:
        raise NotImplementedError

    def list_eligible_roles(self, sub_id: str) -> list[azure.EligibleRole]:
        raise NotImplementedError

    def list_entra_eligible_roles(
        self,
        on_device_code: DeviceCodeCallback | None = None,
        stop_event: threading.Event | None = None,
    ) -> list[azure.EntraEligibleRole]:
        raise NotImplementedError

    def list_active_arm_assignments(self) -> list[azure.ActiveAssignment]:
        raise NotImplementedError

    def list_active_entra_assignments(
        self,
        on_device_code: DeviceCodeCallback | None = None,
        stop_event: threading.Event | None = None,
    ) -> list[azure.ActiveEntraAssignment]:
        raise NotImplementedError

    # -- activation ----------------------------------------------------

    def activate_role(self, role: azure.EligibleRole, justification: str, duration: str) -> dict:
        return azure.activate_role(role, justification, duration, dry_run=self.dry_run)

    def activate_entra_role(self, role: azure.EntraEligibleRole, justification: str, duration: str) -> dict:
        return azure.activate_entra_role(role, justification, duration, dry_run=self.dry_run)


class AzureBackend(Backend):
    """Live data from ``fomo.azure``.

    Functions are looked up on the module at call time so that tests can
    monkeypatch ``fomo.azure`` after the app has been created.
    """

    def list_subscriptions(self) -> list[azure.Subscription]:
        return azure.list_subscriptions()

    def list_eligible_roles(self, sub_id: str) -> list[azure.EligibleRole]:
        return azure.list_eligible_roles(sub_id)

    def list_entra_eligible_roles(
        self,
        on_device_code: DeviceCodeCallback | None = None,
        stop_event: threading.Event | None = None,
    ) -> list[azure.EntraEligibleRole]:
        return azure.list_entra_eligible_roles(on_device_code=on_device_code, stop_event=stop_event)

    def list_active_arm_assignments(self) -> list[azure.ActiveAssignment]:
        return azure.list_active_arm_assignments()

    def list_active_entra_assignments(
        self,
        on_device_code: DeviceCodeCallback | None = None,
        stop_event: threading.Event | None = None,
    ) -> list[azure.ActiveEntraAssignment]:
        return azure.list_active_entra_assignments(on_device_code=on_device_code, stop_event=stop_event)


class DemoBackend(Backend):
    """Static demo data from ``fomo.demo``; activation is always a dry run."""

    allow_network = False

    def __init__(self) -> None:
        super().__init__(dry_run=True)

    def list_subscriptions(self) -> list[azure.Subscription]:
        return demo_data.list_subscriptions()

    def list_eligible_roles(self, sub_id: str) -> list[azure.EligibleRole]:
        return demo_data.list_eligible_roles(sub_id)

    def list_entra_eligible_roles(
        self,
        on_device_code: DeviceCodeCallback | None = None,  # noqa: ARG002
        stop_event: threading.Event | None = None,  # noqa: ARG002
    ) -> list[azure.EntraEligibleRole]:
        return demo_data.list_entra_eligible_roles()

    def list_active_arm_assignments(self) -> list[azure.ActiveAssignment]:
        return demo_data.list_active_arm_assignments()

    def list_active_entra_assignments(
        self,
        on_device_code: DeviceCodeCallback | None = None,  # noqa: ARG002
        stop_event: threading.Event | None = None,  # noqa: ARG002
    ) -> list[azure.ActiveEntraAssignment]:
        return demo_data.list_active_entra_assignments()


def make_backend(dry_run: bool, demo_mode: bool) -> Backend:
    """Return the backend for the given command-line flags."""
    if demo_mode:
        return DemoBackend()
    return AzureBackend(dry_run=dry_run)
