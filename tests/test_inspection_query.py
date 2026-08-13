import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.inspection_query import InspectionQueryService


HOST_COLUMNS = (
    "id",
    "vc_ip",
    "host_name",
    "cluster",
    "status",
    "esxi_version",
    "vendor",
    "model",
    "serial_number",
    "cpu_model",
    "cpu_ghz",
    "cpu_count",
    "cpu_cores",
    "memory_gb",
    "uptime_days",
    "cpu_usage",
    "memory_usage",
    "cert_expiring_soon",
    "vmk_adapters",
    "cert_expiry",
    "inspect_time",
)

VM_COLUMNS = (
    "id",
    "vc_ip",
    "vm_name",
    "cluster",
    "host",
    "power_state",
    "ip_address",
    "memory_gb",
    "cpu_count",
    "uuid",
    "annotation",
    "system_version",
    "guest_os",
    "tools_status",
    "uptime_days",
    "datastore",
    "vm_portgroups",
    "disks",
    "used_space_gb",
    "folder",
    "inspect_time",
)


def _build_test_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE host_inspect (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vc_ip TEXT NOT NULL,
            host_name TEXT NOT NULL,
            cluster TEXT,
            status TEXT,
            esxi_version TEXT,
            vendor TEXT,
            model TEXT,
            serial_number TEXT,
            cpu_model TEXT,
            cpu_ghz REAL,
            cpu_count INTEGER,
            cpu_cores INTEGER,
            memory_gb REAL,
            uptime_days REAL,
            cpu_usage REAL,
            memory_usage REAL,
            cert_expiring_soon TEXT DEFAULT '否',
            vmk_adapters TEXT,
            cert_expiry TEXT,
            inspect_time TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE vm_inspect (
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
            vm_portgroups TEXT,
            disks TEXT,
            used_space_gb REAL,
            folder TEXT,
            inspect_time TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        INSERT INTO host_inspect (
            vc_ip, host_name, cluster, status, esxi_version, vendor, model,
            serial_number, cpu_model, cpu_ghz, cpu_count, cpu_cores, memory_gb,
            uptime_days, cpu_usage, memory_usage, cert_expiring_soon, vmk_adapters,
            cert_expiry, inspect_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "10.0.0.10",
            "esxi-01",
            "cluster-a",
            "connected",
            "8.0.1",
            "Dell",
            "R740",
            "SN-001",
            "Intel Xeon",
            2.3,
            2,
            32,
            256,
            12.5,
            18.2,
            41.7,
            "否",
            "vmk0, vmk1",
            "2026-12-31",
            "2026-06-04 09:00:00",
        ),
    )

    cur.executemany(
        """
        INSERT INTO vm_inspect (
            vc_ip, vm_name, cluster, host, power_state, ip_address, memory_gb,
            cpu_count, uuid, annotation, system_version, guest_os, tools_status,
            uptime_days, datastore, vm_portgroups, disks, used_space_gb, folder,
            inspect_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "10.0.0.10",
                "web-01",
                "cluster-a",
                "esxi-01",
                "poweredOn",
                "192.168.10.11",
                8,
                2,
                "uuid-web-01",
                "production",
                "Windows Server 2019",
                "Windows Server 2019",
                "OK",
                3.5,
                "datastore1",
                "VLAN10",
                "C:40G",
                40,
                "Prod",
                "2026-06-04 09:05:00",
            ),
            (
                "10.0.0.10",
                "web-02",
                "cluster-a",
                "esxi-01",
                "poweredOn",
                "192.168.10.12",
                8,
                2,
                "uuid-web-02",
                "production",
                "Windows Server 2019",
                "Windows Server 2019",
                "OK",
                2.1,
                "datastore1",
                "VLAN10",
                "C:40G",
                41,
                "Prod",
                "2026-06-04 09:06:00",
            ),
        ],
    )

    conn.commit()
    conn.close()


@pytest.fixture()
def inspection_service(tmp_path):
    db_path = tmp_path / "vcenter.db"
    _build_test_db(db_path)
    return InspectionQueryService(db_path=db_path)


def test_query_by_vm_name_returns_full_vm_rows_and_one_host(inspection_service):
    result = inspection_service.search("web")

    assert result.query == "web"
    assert [row["vm_name"] for row in result.vm_records] == ["web-01", "web-02"]
    assert len(result.host_rows) == 1
    assert result.host_records[0]["host_name"] == "esxi-01"

    assert result.host_rows[0] == tuple(result.host_records[0][column] for column in HOST_COLUMNS)
    assert tuple(result.vm_records[0].keys()) == VM_COLUMNS


def test_query_by_vm_ip_returns_related_host(inspection_service):
    result = inspection_service.search("192.168.10.12")

    assert [row["vm_name"] for row in result.vm_records] == ["web-02"]
    assert len(result.host_records) == 1
    assert result.host_records[0]["vc_ip"] == "10.0.0.10"
    assert result.host_records[0]["cpu_cores"] == 32


def test_blank_query_returns_empty_result(inspection_service):
    result = inspection_service.search("   ")

    assert result.vm_rows == []
    assert result.host_rows == []
    assert result.vm_records == []
    assert result.host_records == []
