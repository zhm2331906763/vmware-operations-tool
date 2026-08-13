from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import datetime

from src.core.power_models import PowerTask, PowerTaskTarget
from src.core.power_task_store import PowerTaskStore
from src.core.vcenter_connector import VCenterConnector
from src.db.database import Database


def resolve_vm_ref(client, ref: PowerTaskTarget):
    if ref.uuid:
        vm = client.find_vm_by_uuid(ref.uuid)
        if vm:
            return vm
    if ref.name:
        vm = client.get_vm_by_name(ref.name)
        if vm:
            return vm
    if ref.ip_address:
        vm = client.get_vm_by_ip(ref.ip_address)
        if vm:
            return vm
    return None


class PowerTaskScheduler:
    def __init__(
        self,
        app=None,
        store: PowerTaskStore | None = None,
        db: Database | None = None,
        connector_factory=VCenterConnector,
        poll_interval: int = 30,
    ):
        self.app = app
        self.store = store or PowerTaskStore()
        self.db = db or Database()
        self.connector_factory = connector_factory
        self.poll_interval = poll_interval
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._last_checked: dict[str, str] = {}

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _normalize_schedule_type(self, schedule_type: str) -> str:
        mapping = {"每天": "daily", "每周": "weekly", "仅一次": "once"}
        return mapping.get(schedule_type, schedule_type)

    def _get_vcenter_credentials(self, vc_ip: str):
        for vc in self.db.get_vcenters():
            if str(vc[1]) == str(vc_ip):
                return vc[2], vc[3]
        return None, None

    def _run_loop(self):
        while self._running:
            try:
                self.process_once()
            except Exception as exc:
                print(f"Power scheduler error: {exc}")
            time.sleep(self.poll_interval)

    def process_once(self, now: datetime | None = None):
        now = now or datetime.now()
        current_time = now.strftime("%H:%M")
        current_weekday = str(now.weekday() % 7)

        tasks = self.store.get_enabled_power_tasks()
        for task in tasks:
            normalized_type = self._normalize_schedule_type(task.schedule_type)
            if not self._should_run(task, normalized_type, current_time, current_weekday, now):
                continue

            if normalized_type == "once":
                self.store.set_power_task_enabled(task.id, False)

            self._mark_task_seen(task, normalized_type, current_time, now)
            self.execute_task(task)

    def _should_run(self, task: PowerTask, schedule_type: str, current_time: str, current_weekday: str, now: datetime) -> bool:
        if schedule_type == "daily" and current_time == task.schedule_time:
            last_run = self._last_checked.get(task.id)
            return last_run != current_time

        if schedule_type == "weekly" and current_time == task.schedule_time and str(task.schedule_day or "") == current_weekday:
            week_key = f"{task.id}_{now.strftime('%Y-%W')}"
            last_run = self._last_checked.get(week_key)
            return last_run != week_key

        if schedule_type == "once" and current_time == task.schedule_time:
            last_run = self._last_checked.get(task.id)
            return last_run != current_time

        return False

    def _mark_task_seen(self, task: PowerTask, schedule_type: str, current_time: str, now: datetime) -> None:
        if schedule_type == "weekly":
            week_key = f"{task.id}_{now.strftime('%Y-%W')}"
            self._last_checked[week_key] = week_key
        else:
            self._last_checked[task.id] = current_time

    def execute_task(self, task: PowerTask):
        self.store.update_power_task_status(task.id, "运行中")

        if not task.targets:
            self.store.update_power_task_status(task.id, "失败: 任务没有目标")
            return False, "任务没有目标"

        results: list[str] = []
        success_count = 0
        fail_count = 0

        targets_by_vc: dict[str, list[PowerTaskTarget]] = defaultdict(list)
        for target in task.targets:
            targets_by_vc[target.vc_ip or ""].append(target)

        for vc_ip, targets in targets_by_vc.items():
            if not vc_ip:
                for target in targets:
                    results.append(f"{target.display_name or target.ip_address or target.uuid}: 失败: 缺少 vCenter 信息")
                    fail_count += 1
                continue

            user, pwd = self._get_vcenter_credentials(vc_ip)
            if not user or not pwd:
                for target in targets:
                    results.append(f"{target.display_name or target.ip_address or target.uuid}: 失败: 未找到 vCenter 登录信息")
                    fail_count += 1
                continue

            connector = self.connector_factory(vc_ip, user, pwd)
            connected = False
            try:
                connected, msg = connector.connect()
                if not connected:
                    for target in targets:
                        results.append(f"{target.display_name or target.ip_address or target.uuid}: 失败: {msg}")
                        fail_count += 1
                    continue

                for target in targets:
                    vm = resolve_vm_ref(connector, target)
                    if not vm:
                        results.append(f"{target.display_name or target.ip_address or target.uuid}: 失败: 未找到虚拟机")
                        fail_count += 1
                        continue

                    if task.action == "power_on":
                        ok, msg = connector.power_on_vm(vm)
                    elif task.action == "power_off":
                        ok, msg = connector.power_off_vm(vm)
                    else:
                        ok, msg = False, f"不支持的动作: {task.action}"

                    if ok:
                        success_count += 1
                        results.append(f"{target.display_name or target.ip_address or target.uuid}: 成功")
                    else:
                        fail_count += 1
                        results.append(f"{target.display_name or target.ip_address or target.uuid}: 失败: {msg}")
            finally:
                if connected:
                    connector.disconnect()

        summary = f"成功 {success_count} 台，失败 {fail_count} 台"
        if results:
            summary = f"{summary} | " + "；".join(results[:6])
            if len(results) > 6:
                summary += f"；等{len(results)}条明细"

        self.store.update_power_task_status(task.id, summary)
        return fail_count == 0, summary

    def run_task_now(self, task_id: str):
        task = self.store.get_power_task(task_id)
        if not task:
            return False

        threading.Thread(target=self.execute_task, args=(task,), daemon=True).start()
        return True

    def is_running(self):
        return self._running
