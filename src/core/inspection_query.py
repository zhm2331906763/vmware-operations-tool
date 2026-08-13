from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.db.database import Database


HOST_COLUMNS = [
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
]

VM_COLUMNS = [
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
    "nsx_managed",
    "disks",
    "used_space_gb",
    "folder",
    "inspect_time",
]


@dataclass(slots=True)
class InspectionQueryResult:
    query_text: str
    host_columns: list[str]
    host_rows: list[tuple[Any, ...]]
    vm_columns: list[str]
    vm_rows: list[tuple[Any, ...]]
    host_records: list[dict[str, Any]] = field(default_factory=list)
    vm_records: list[dict[str, Any]] = field(default_factory=list)
    prefer_vm_first: bool = False

    @property
    def query(self) -> str:
        return self.query_text

    @property
    def host_count(self) -> int:
        return len(self.host_rows)

    @property
    def vm_count(self) -> int:
        return len(self.vm_rows)

    @property
    def has_results(self) -> bool:
        return bool(self.host_rows or self.vm_rows)


class InspectionQueryService:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = Database().db_path
        self.db_path = Path(db_path)
        self._db_uri = self.db_path.resolve().as_uri()
        self.host_columns = self._resolve_columns("host_inspect", HOST_COLUMNS)
        self.vm_columns = self._resolve_columns("vm_inspect", VM_COLUMNS)

    def search(self, query_text: str) -> InspectionQueryResult:
        term = (query_text or "").strip()
        if not term:
            return self._empty_result(term)

        vm_records = self._search_vm_records(term)
        prefer_vm_first = bool(vm_records)

        if vm_records:
            host_records = self._lookup_hosts_for_vms(vm_records)
        else:
            host_records = self._search_host_records(term)
            if host_records:
                vm_records = self._lookup_vms_for_hosts(host_records)

        return self._build_result(term, host_records, vm_records, prefer_vm_first=prefer_vm_first)

    def _empty_result(self, term: str) -> InspectionQueryResult:
        return InspectionQueryResult(
            query_text=term,
            host_columns=list(self.host_columns),
            host_rows=[],
            vm_columns=list(self.vm_columns),
            vm_rows=[],
            host_records=[],
            vm_records=[],
            prefer_vm_first=False,
        )

    def _build_result(
        self,
        term: str,
        host_records: list[dict[str, Any]],
        vm_records: list[dict[str, Any]],
        prefer_vm_first: bool = False,
    ) -> InspectionQueryResult:
        return InspectionQueryResult(
            query_text=term,
            host_columns=list(self.host_columns),
            host_rows=[self._record_to_tuple(record, self.host_columns) for record in host_records],
            vm_columns=list(self.vm_columns),
            vm_rows=[self._record_to_tuple(record, self.vm_columns) for record in vm_records],
            host_records=host_records,
            vm_records=vm_records,
            prefer_vm_first=prefer_vm_first,
        )

    def _resolve_columns(self, table_name: str, preferred_columns: list[str]) -> list[str]:
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            available = {row[1] for row in cursor.fetchall()}
        finally:
            conn.close()
        return [column for column in preferred_columns if column in available]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _search_vm_records(self, term: str) -> list[dict[str, Any]]:
        pattern = f"%{term}%"
        sql = (
            f"SELECT {', '.join(self.vm_columns)} "
            "FROM vm_inspect "
            "WHERE vm_name LIKE ? COLLATE NOCASE "
            "OR ip_address LIKE ? COLLATE NOCASE "
            "OR host LIKE ? COLLATE NOCASE "
            "ORDER BY vm_name, id"
        )
        return self._fetch_all(sql, (pattern, pattern, pattern))

    def _search_host_records(self, term: str) -> list[dict[str, Any]]:
        pattern = f"%{term}%"
        sql = (
            f"SELECT {', '.join(self.host_columns)} "
            "FROM host_inspect "
            "WHERE host_name LIKE ? COLLATE NOCASE "
            "OR vmk_adapters LIKE ? COLLATE NOCASE "
            "ORDER BY host_name, id"
        )
        return self._fetch_all(sql, (pattern, pattern))

    def _lookup_hosts_for_vms(self, vm_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        host_records: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for vm in vm_records:
            vc_ip = vm.get("vc_ip")
            host_name = vm.get("host")
            if not vc_ip or not host_name:
                continue

            key = (str(vc_ip), str(host_name))
            if key in seen:
                continue
            seen.add(key)

            host = self._fetch_one(
                f"SELECT {', '.join(self.host_columns)} FROM host_inspect WHERE vc_ip = ? AND host_name = ?",
                (vc_ip, host_name),
            )
            if host:
                host_records.append(host)

        return host_records

    def _lookup_vms_for_hosts(self, host_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        vm_records: list[dict[str, Any]] = []
        seen_ids: set[int] = set()

        for host in host_records:
            vc_ip = host.get("vc_ip")
            host_name = host.get("host_name")
            if not vc_ip or not host_name:
                continue

            rows = self._fetch_all(
                f"SELECT {', '.join(self.vm_columns)} FROM vm_inspect WHERE vc_ip = ? AND host = ? ORDER BY vm_name, id",
                (vc_ip, host_name),
            )
            for row in rows:
                row_id = row.get("id")
                if isinstance(row_id, int) and row_id in seen_ids:
                    continue
                if isinstance(row_id, int):
                    seen_ids.add(row_id)
                vm_records.append(row)

        return vm_records

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        rows = self._fetch_all(sql, params)
        return rows[0] if rows else None

    @staticmethod
    def _record_to_tuple(record: dict[str, Any], columns: list[str]) -> tuple[Any, ...]:
        return tuple(record.get(column) for column in columns)


def query_inspection(query_text: str, db_path: str | Path | None = None) -> InspectionQueryResult:
    return InspectionQueryService(db_path=db_path).search(query_text)


__all__ = [
    "HOST_COLUMNS",
    "VM_COLUMNS",
    "InspectionQueryResult",
    "InspectionQueryService",
    "query_inspection",
]
