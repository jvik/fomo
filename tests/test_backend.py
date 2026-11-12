"""Backend selection and delegation."""

from __future__ import annotations

from fomo import demo
from fomo.backend import AzureBackend, DemoBackend, make_backend


def test_make_backend_picks_demo_and_forces_dry_run() -> None:
    backend = make_backend(dry_run=False, demo_mode=True)
    assert isinstance(backend, DemoBackend)
    assert backend.dry_run is True


def test_make_backend_picks_azure_and_keeps_dry_run_flag() -> None:
    live = make_backend(dry_run=False, demo_mode=False)
    assert isinstance(live, AzureBackend)
    assert live.dry_run is False
    assert make_backend(dry_run=True, demo_mode=False).dry_run is True


def test_azure_backend_looks_up_azure_at_call_time(fake_azure) -> None:
    # Screens hold a backend created when the app starts; monkeypatching
    # fomo.azure afterwards must still take effect, so lookups happen per call.
    backend = AzureBackend(dry_run=True)
    subs = backend.list_subscriptions()
    assert [s.id for s in subs] == [s.id for s in fake_azure.subs]
    backend.list_active_arm_assignments()
    assert ("list_active_arm_assignments",) in fake_azure.calls


def test_demo_backend_returns_demo_data_and_activates_as_dry_run(fake_azure) -> None:
    backend = DemoBackend()
    assert backend.list_subscriptions() == demo.list_subscriptions()
    assert backend.list_entra_eligible_roles(on_device_code=lambda _m: None) == demo.list_entra_eligible_roles()
    role = demo.list_eligible_roles(demo.SUBSCRIPTIONS[0].id)[0]
    backend.activate_role(role, "why", "PT1H")
    assert fake_azure.activations[-1][-1] is True
