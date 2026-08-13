from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.power_scheduler import PowerTaskScheduler, resolve_vm_ref
from src.core.power_models import PowerTaskTarget
from src.core.power_task_store import PowerTaskStore


def _create_vm_inspect_table(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS vm_inspect (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vc_ip TEXT NOT NULL,
            vm_name TEXT NOT NULL,
            cluster TEXT,
            host TEXT,
            power_state TEXT,
            ip_address TEXT,
            memory_gb REAL,
            cpu_count INTEGER,
            uuid TEXT,
            annotation TEXT,
            system_version TEXT,
            guest_os TEXT,
            tools_status TEXT,
            uptime_days REAL,
            datastore TEXT,
            disks TEXT,
            vm_portgroups TEXT,
            used_space_gb REAL,
            folder TEXT,
            inspect_time TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def _seed_vm_rows(db_path: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    for row in rows:
        cursor.execute(
            """
            INSERT INTO vm_inspect (
                vc_ip, vm_name, cluster, host, power_state, ip_address, memory_gb,
                cpu_count, uuid, annotation, system_version, guest_os, tools_status,
                uptime_days, datastore, disks, vm_portgroups, used_space_gb, folder
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("vc_ip"),
                row.get("vm_name"),
                row.get("cluster"),
                row.get("host"),
                row.get("power_state"),
                row.get("ip_address"),
                row.get("memory_gb"),
                row.get("cpu_count"),
                row.get("uuid"),
                row.get("annotation"),
                row.get("system_version"),
                row.get("guest_os"),
                row.get("tools_status"),
                row.get("uptime_days"),
                row.get("datastore"),
                row.get("disks"),
                row.get("vm_portgroups"),
                row.get("used_space_gb"),
                row.get("folder"),
            ),
        )
    conn.commit()
    conn.close()


class FakeConnector:
    instances: list["FakeConnector"] = []

    def __init__(self, ip, user, password):
        self.ip = ip
        self.user = user
        self.password = password
        self.connected = False
        self.disconnect_called = False
        self.find_vm_by_uuid_calls: list[str] = []
        self.get_vm_by_name_calls: list[str] = []
        self.get_vm_by_ip_calls: list[str] = []
        self.power_on_calls = 0
        self.power_off_calls = 0
        self.vm = SimpleNamespace(name="resolved-vm", guest=SimpleNamespace(ipAddress="10.0.0.11"))
        FakeConnector.instances.append(self)

    def connect(self):
        self.connected = True
        return True, "ok"

    def disconnect(self):
        self.disconnect_called = True

    def find_vm_by_uuid(self, uuid):
        self.find_vm_by_uuid_calls.append(uuid)
        return self.vm if uuid == "uuid-1" else None

    def get_vm_by_name(self, name):
        self.get_vm_by_name_calls.append(name)
        return self.vm if name == "alpha" else None

    def get_vm_by_ip(self, ip):
        self.get_vm_by_ip_calls.append(ip)
        return self.vm if ip == "10.0.0.11" else None

    def power_on_vm(self, vm):
        self.power_on_calls += 1
        return True, "power on"

    def power_off_vm(self, vm):
        self.power_off_calls += 1
        return True, "power off"


def test_create_power_task_from_queries_requires_all_targets_exist(tmp_path):
    db_path = tmp_path / "vcenter.db"
    _create_vm_inspect_table(db_path)
    _seed_vm_rows(
        db_path,
        [
            {
                "vc_ip": "10.0.0.10",
                "vm_name": "alpha",
                "uuid": "uuid-1",
                "host": "esxi-1",
                "ip_address": "10.0.0.11",
            },
            {
                "vc_ip": "10.0.0.10",
                "vm_name": "beta",
                "uuid": "uuid-2",
                "host": "esxi-2",
                "ip_address": "10.0.0.12",
            },
        ],
    )

    store = PowerTaskStore(db_path=str(db_path))
    task = store.build_power_task_from_batch_queries(
        task_name="night power on",
        action="power_on",
        schedule_type="daily",
        schedule_time="23:30",
        query_text="alpha\n10.0.0.12",
    )

    assert [target.uuid for target in task.targets] == ["uuid-1", "uuid-2"]
    assert task.action == "power_on"


def test_create_power_task_rejects_missing_vm_entries(tmp_path):
    db_path = tmp_path / "vcenter.db"
    _create_vm_inspect_table(db_path)
    _seed_vm_rows(
        db_path,
        [
            {
                "vc_ip": "10.0.0.10",
                "vm_name": "alpha",
                "uuid": "uuid-1",
                "host": "esxi-1",
                "ip_address": "10.0.0.11",
            }
        ],
    )

    store = PowerTaskStore(db_path=str(db_path))
    with pytest.raises(ValueError, match="未找到匹配的虚拟机"):
        store.build_power_task_from_batch_queries(
            task_name="bad task",
            action="power_off",
            schedule_type="once",
            schedule_time="23:30",
            query_text="missing-vm",
        )


def test_once_power_task_is_disabled_after_execution(tmp_path):
    FakeConnector.instances.clear()

    db_path = tmp_path / "vcenter.db"
    _create_vm_inspect_table(db_path)
    _seed_vm_rows(
        db_path,
        [
            {
                "vc_ip": "10.0.0.10",
                "vm_name": "alpha",
                "uuid": "uuid-1",
                "host": "esxi-1",
                "ip_address": "10.0.0.11",
            }
        ],
    )

    store = PowerTaskStore(db_path=str(db_path))
    task = store.build_power_task_from_batch_queries(
        task_name="night power on",
        action="power_on",
        schedule_type="once",
        schedule_time="23:30",
        query_text="alpha",
        task_id="task-1",
    )
    store.add_power_task(task)

    fake_db = SimpleNamespace(get_vcenters=lambda: [(1, "10.0.0.10", "admin", "secret")])
    scheduler = PowerTaskScheduler(
        store=store,
        db=fake_db,
        connector_factory=FakeConnector,
        poll_interval=1,
    )

    scheduler.process_once(now=datetime(2026, 6, 4, 23, 30))

    stored_task = store.get_power_task("task-1")
    assert stored_task is not None
    assert stored_task.enabled is False
    assert stored_task.last_status.startswith("成功 1 台")
    assert FakeConnector.instances[0].find_vm_by_uuid_calls == ["uuid-1"]
    assert FakeConnector.instances[0].power_on_calls == 1


def test_resolve_vm_ref_prefers_uuid_then_name_then_ip():
    class OrderConnector:
        def __init__(self):
            self.calls = []
            self.vm = object()

        def find_vm_by_uuid(self, uuid):
            self.calls.append(("uuid", uuid))
            return None

        def get_vm_by_name(self, name):
            self.calls.append(("name", name))
            return self.vm

        def get_vm_by_ip(self, ip):
            self.calls.append(("ip", ip))
            return self.vm

    connector = OrderConnector()
    target = PowerTaskTarget(uuid="uuid-9", name="alpha", ip_address="10.0.0.11")

    found = resolve_vm_ref(connector, target)

    assert found is connector.vm
    assert connector.calls == [("uuid", "uuid-9"), ("name", "alpha")]
