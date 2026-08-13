from __future__ import annotations

from types import SimpleNamespace

from src.core.vcenter_connector import VCenterConnector


class FakeContainerView:
    def __init__(self, view):
        self.view = view
        self.destroyed = False

    def Destroy(self):
        self.destroyed = True


class FakeViewManager:
    def __init__(self, view):
        self._view = view
        self.container = None

    def CreateContainerView(self, root_folder, vim_types, recursive):
        self.container = FakeContainerView(self._view)
        return self.container


class FakeContent:
    def __init__(self, view):
        self.viewManager = FakeViewManager(view)
        self.rootFolder = object()


def test_get_vm_by_ip_returns_matching_vm():
    vm = SimpleNamespace(guest=SimpleNamespace(ipAddress="10.0.0.21"))
    connector = VCenterConnector("10.0.0.10", "user", "pass")
    connector.si = object()
    connector.content = FakeContent([vm])

    found = connector.get_vm_by_ip("10.0.0.21")

    assert found is vm
    assert connector.content.viewManager.container.destroyed is True


def test_get_vm_by_ip_returns_none_when_not_found():
    vm = SimpleNamespace(guest=SimpleNamespace(ipAddress="10.0.0.21"))
    connector = VCenterConnector("10.0.0.10", "user", "pass")
    connector.si = object()
    connector.content = FakeContent([vm])

    found = connector.get_vm_by_ip("10.0.0.99")

    assert found is None
    assert connector.content.viewManager.container.destroyed is True
