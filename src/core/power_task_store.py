from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
import uuid
from dataclasses import replace
from datetime import datetime
from typing import Iterable

from src.core.power_models import PowerTask, PowerTaskTarget


POWER_TASK_COLUMNS = [
    "id",
    "name",
    "action",
    "schedule_type",
    "schedule_time",
    "schedule_day",
    "enabled",
    "vcenter_name",
    "targets_json",
    "last_run",
    "last_status",
    "created_at",
    "updated_at",
]

VM_INSPECT_COLUMNS = [
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

HOST_INSPECT_COLUMNS = [
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


class PowerTaskStore:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or self._default_db_path()
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_tables()

    def _default_db_path(self) -> str:
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(sys.executable)
            data_dir = os.path.join(exe_dir, "data")
            return os.path.join(data_dir, "vcenter.db")

        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(base_dir, "src", "db", "vcenter.db")

    def get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_tables(self) -> None:
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS power_tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    schedule_type TEXT NOT NULL,
                    schedule_time TEXT NOT NULL,
                    schedule_day TEXT DEFAULT '',
                    enabled INTEGER DEFAULT 1,
                    vcenter_name TEXT DEFAULT '',
                    targets_json TEXT NOT NULL,
                    last_run TEXT,
                    last_status TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_power_tasks_enabled_time "
                "ON power_tasks(enabled, schedule_type, schedule_time, schedule_day)"
            )
            conn.commit()
            conn.close()

    def _split_query_text(self, query_text: str) -> list[str]:
        if not query_text:
            return []
        parts = re.split(r"[\n\r,，;；]+", query_text)
        return [part.strip() for part in parts if part and part.strip()]

    def _fetch_one(self, sql: str, params: tuple) -> tuple | None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        row = cursor.fetchone()
        conn.close()
        return row

    def _fetch_all(self, sql: str, params: tuple = ()) -> list[tuple]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()
        return rows

    def _row_to_target(self, row: tuple) -> PowerTaskTarget:
        return PowerTaskTarget(
            vc_ip=str(row[1] or ""),
            name=str(row[2] or ""),
            cluster=str(row[3] or ""),
            host=str(row[4] or ""),
            ip_address=str(row[6] or ""),
            uuid=str(row[9] or ""),
        )

    def _load_targets_json(self, targets_json: str | None) -> list[PowerTaskTarget]:
        if not targets_json:
            return []
        try:
            payload = json.loads(targets_json)
        except json.JSONDecodeError:
            return []
        return [PowerTaskTarget.from_dict(item) for item in payload if isinstance(item, dict)]

    def _task_from_row(self, row: tuple) -> PowerTask:
        return PowerTask(
            id=str(row[0]),
            name=str(row[1] or ""),
            action=str(row[2] or ""),
            schedule_type=str(row[3] or ""),
            schedule_time=str(row[4] or ""),
            schedule_day=str(row[5] or ""),
            enabled=bool(int(row[6] or 0)),
            vcenter_name=str(row[7] or ""),
            targets=self._load_targets_json(row[8]),
            last_run=str(row[9] or ""),
            last_status=str(row[10] or ""),
            created_at=str(row[11] or ""),
            updated_at=str(row[12] or ""),
        )

    def _serialize_targets(self, targets: Iterable[PowerTaskTarget]) -> str:
        return json.dumps([target.to_dict() for target in targets], ensure_ascii=False)

    def _normalize_schedule_type(self, schedule_type: str) -> str:
        mapping = {"每天": "daily", "每周": "weekly", "仅一次": "once"}
        return mapping.get(schedule_type, schedule_type)

    def _find_vm_rows_by_token(self, token: str) -> list[tuple]:
        token = token.strip()
        if not token:
            return []

        queries = [
            ("SELECT * FROM vm_inspect WHERE uuid = ? ORDER BY inspect_time DESC, id DESC", (token,)),
            ("SELECT * FROM vm_inspect WHERE vm_name = ? ORDER BY inspect_time DESC, id DESC", (token,)),
            ("SELECT * FROM vm_inspect WHERE ip_address = ? ORDER BY inspect_time DESC, id DESC", (token,)),
        ]

        for sql, params in queries:
            rows = self._fetch_all(sql, params)
            if rows:
                return rows
        return []

    def find_vm_inspect_rows(self, query_text: str) -> list[tuple]:
        rows: list[tuple] = []
        seen: set[tuple[str, str, str]] = set()
        for token in self._split_query_text(query_text):
            matched_rows = self._find_vm_rows_by_token(token)
            if not matched_rows:
                continue
            row = matched_rows[0]
            key = (str(row[1] or ""), str(row[2] or ""), str(row[6] or ""))
            if key not in seen:
                rows.append(row)
                seen.add(key)
        return rows

    def get_vm_inspect_by_query(self, query_text: str) -> tuple[list[tuple], list[str]]:
        return self.find_vm_inspect_rows(query_text), VM_INSPECT_COLUMNS

    def find_host_inspect_rows(self, query_text: str) -> list[tuple]:
        tokens = self._split_query_text(query_text)
        rows: list[tuple] = []
        seen: set[tuple[str, str]] = set()
        for token in tokens:
            sql_candidates = [
                ("SELECT * FROM host_inspect WHERE host_name = ? ORDER BY inspect_time DESC, id DESC", (token,)),
                ("SELECT * FROM host_inspect WHERE vc_ip = ? ORDER BY inspect_time DESC, id DESC", (token,)),
            ]
            for sql, params in sql_candidates:
                matched = self._fetch_all(sql, params)
                if matched:
                    row = matched[0]
                    key = (str(row[1] or ""), str(row[2] or ""))
                    if key not in seen:
                        rows.append(row)
                        seen.add(key)
                    break
        return rows

    def find_related_host_rows_for_vm_rows(self, vm_rows: list[tuple]) -> list[tuple]:
        rows: list[tuple] = []
        seen: set[tuple[str, str]] = set()
        for vm_row in vm_rows:
            vc_ip = str(vm_row[1] or "")
            host_name = str(vm_row[4] or "")
            if not vc_ip or not host_name:
                continue
            matched = self._fetch_all(
                "SELECT * FROM host_inspect WHERE vc_ip = ? AND host_name = ? ORDER BY inspect_time DESC, id DESC",
                (vc_ip, host_name),
            )
            if matched:
                row = matched[0]
                key = (str(row[1] or ""), str(row[2] or ""))
                if key not in seen:
                    rows.append(row)
                    seen.add(key)
        return rows

    def build_power_task_from_batch_queries(
        self,
        *,
        task_name: str,
        action: str,
        schedule_type: str,
        schedule_time: str,
        query_text: str,
        schedule_day: str = "",
        task_id: str = "",
        vcenter_name: str = "",
    ) -> PowerTask:
        tokens = self._split_query_text(query_text)
        if not tokens:
            raise ValueError("请输入至少一台虚拟机的 UUID、名称或 IP")

        targets: list[PowerTaskTarget] = []
        missing: list[str] = []
        seen_targets: set[tuple[str, str, str]] = set()

        for token in tokens:
            matched_rows = self._find_vm_rows_by_token(token)
            if not matched_rows:
                missing.append(token)
                continue
            target = self._row_to_target(matched_rows[0])
            target_key = (target.uuid, target.name, target.ip_address)
            if target_key in seen_targets:
                continue
            seen_targets.add(target_key)
            targets.append(target)

        if missing:
            raise ValueError(f"未找到匹配的虚拟机: {', '.join(missing)}")

        task_id = task_id or uuid.uuid4().hex
        return PowerTask(
            id=task_id,
            name=task_name.strip(),
            action=action.strip(),
            schedule_type=self._normalize_schedule_type(schedule_type),
            schedule_time=schedule_time.strip(),
            schedule_day=schedule_day or "",
            enabled=True,
            vcenter_name=vcenter_name.strip(),
            targets=targets,
        )

    def add_power_task(self, task: PowerTask) -> str:
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            task_id = task.id or uuid.uuid4().hex
            cursor.execute(
                """
                INSERT INTO power_tasks (
                    id, name, action, schedule_type, schedule_time, schedule_day,
                    enabled, vcenter_name, targets_json, last_run, last_status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                (
                    task_id,
                    task.name,
                    task.action,
                    task.schedule_type,
                    task.schedule_time,
                    task.schedule_day or "",
                    1 if task.enabled else 0,
                    task.vcenter_name or "",
                    self._serialize_targets(task.targets),
                    task.last_run or "",
                    task.last_status or "",
                ),
            )
            conn.commit()
            conn.close()
            return task_id

    def update_power_task(self, task_id: str, task: PowerTask) -> None:
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE power_tasks
                SET name = ?, action = ?, schedule_type = ?, schedule_time = ?,
                    schedule_day = ?, enabled = ?, vcenter_name = ?, targets_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    task.name,
                    task.action,
                    task.schedule_type,
                    task.schedule_time,
                    task.schedule_day or "",
                    1 if task.enabled else 0,
                    task.vcenter_name or "",
                    self._serialize_targets(task.targets),
                    task_id,
                ),
            )
            conn.commit()
            conn.close()

    def get_power_task(self, task_id: str) -> PowerTask | None:
        row = self._fetch_one(
            "SELECT id, name, action, schedule_type, schedule_time, schedule_day, enabled, "
            "vcenter_name, targets_json, last_run, last_status, created_at, updated_at "
            "FROM power_tasks WHERE id = ?",
            (task_id,),
        )
        if not row:
            return None
        return self._task_from_row(row)

    def get_power_tasks(self) -> list[PowerTask]:
        rows = self._fetch_all(
            "SELECT id, name, action, schedule_type, schedule_time, schedule_day, enabled, "
            "vcenter_name, targets_json, last_run, last_status, created_at, updated_at "
            "FROM power_tasks ORDER BY created_at DESC"
        )
        return [self._task_from_row(row) for row in rows]

    def get_enabled_power_tasks(self) -> list[PowerTask]:
        rows = self._fetch_all(
            "SELECT id, name, action, schedule_type, schedule_time, schedule_day, enabled, "
            "vcenter_name, targets_json, last_run, last_status, created_at, updated_at "
            "FROM power_tasks WHERE enabled = 1 ORDER BY created_at DESC"
        )
        return [self._task_from_row(row) for row in rows]

    def update_power_task_status(self, task_id: str, status: str) -> None:
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE power_tasks SET last_run = CURRENT_TIMESTAMP, last_status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, task_id),
            )
            conn.commit()
            conn.close()

    def set_power_task_enabled(self, task_id: str, enabled: bool) -> None:
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE power_tasks SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (1 if enabled else 0, task_id),
            )
            conn.commit()
            conn.close()

    def delete_power_task(self, task_id: str) -> None:
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM power_tasks WHERE id = ?", (task_id,))
            conn.commit()
            conn.close()

    def upsert_power_task(self, task: PowerTask) -> str:
        existing = self.get_power_task(task.id)
        if existing:
            self.update_power_task(task.id, task)
            return task.id
        return self.add_power_task(task)
