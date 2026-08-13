from __future__ import annotations

import concurrent.futures
import os
import threading
import time
from datetime import datetime

import pandas as pd

from src.core.concurrent_config import ConcurrentConfig
from src.core.excel_formatter import format_excel_file, highlight_column_cells
from src.core.host_collector import HostCollector
from src.core.nsx_utils import derive_vm_nsx_managed
from src.core.storage_inspector import StorageInspector
from src.core.vcenter_connector import VCenterConnector
from src.core.vm_collector import VMCollector
from src.db.database import Database


TASK_TYPES = {
    "host_inspect": "ESXi巡检",
    "vm_inspect": "虚拟机巡检",
    "storage_inspect": "存储巡检",
    "storage_inspect_skip_inaccessible": "存储巡检-跳过不可访问存储",
}

SCHEDULE_TYPES = {
    "daily": "每天",
    "weekly": "每周",
    "once": "仅一次",
}

WEEK_DAYS = {
    "0": "周一",
    "1": "周二",
    "2": "周三",
    "3": "周四",
    "4": "周五",
    "5": "周六",
    "6": "周日",
}


class TaskScheduler:
    def __init__(self, app=None):
        self.db = Database()
        self.app = app
        self._running = False
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _normalize_schedule_type(self, schedule_type):
        mapping = {
            "每天": "daily",
            "姣忓ぉ": "daily",
            "每周": "weekly",
            "姣忓懆": "weekly",
            "仅一次": "once",
            "浠呬竴娆?": "once",
        }
        return mapping.get(schedule_type, schedule_type)

    def _run_loop(self):
        last_checked = {}

        while self._running:
            try:
                tasks = self.db.get_enabled_tasks()
                now = datetime.now()
                current_time = now.strftime("%H:%M")
                current_date = now.strftime("%Y-%m-%d")
                current_weekday = str(now.weekday() % 7)

                for task in tasks:
                    task_id = task[0]
                    task_name = task[1]
                    task_type = task[2]
                    schedule_type = self._normalize_schedule_type(task[3])
                    schedule_time = task[4]
                    schedule_day = task[5]
                    save_path = task[6]

                    should_run = False
                    if schedule_type == "daily" and current_time == schedule_time:
                        day_key = f"{task_id}_{current_date}"
                        should_run = last_checked.get(day_key) != day_key
                        if should_run:
                            last_checked[day_key] = day_key
                    elif schedule_type == "weekly" and current_time == schedule_time and schedule_day == current_weekday:
                        week_key = f"{task_id}_{now.strftime('%Y-%W')}"
                        should_run = last_checked.get(week_key) != week_key
                        if should_run:
                            last_checked[week_key] = week_key
                    elif schedule_type == "once" and current_time == schedule_time:
                        once_key = f"{task_id}_{current_date}_{current_time}"
                        should_run = last_checked.get(once_key) != once_key
                        if should_run:
                            last_checked[once_key] = once_key
                            self.db.update_task(task_id, enabled=0)

                    if should_run:
                        self._execute_task(task_id, task_name, task_type, save_path)
            except Exception as exc:
                print(f"[Scheduler] loop error: {exc}")

            time.sleep(30)

    def _execute_task(self, task_id, task_name, task_type, save_path, target_mode="", target_values="", target_payload=""):
        try:
            self.db.update_task_status(task_id, "运行中...")

            if task_type in ("host_inspect", "vm_inspect", "storage_inspect", "storage_inspect_skip_inaccessible"):
                file_path, detail = self._run_inspection_task(task_type, save_path)
                if file_path:
                    self.db.update_task_status(task_id, f"成功 - {detail} | 文件: {os.path.basename(file_path)}")
                else:
                    self.db.update_task_status(task_id, f"成功 - {detail}")
                return

            self.db.update_task_status(task_id, f"失败: 不支持的任务类型 {task_type}")
        except Exception as exc:
            self.db.update_task_status(task_id, f"失败: {exc}")

    def _run_inspection_task(self, task_type, save_path):
        vcenters = self.db.get_vcenters()
        if not vcenters:
            return "", "无vCenter配置"

        region_map = self.db.get_vcenter_region_map()
        workers = ConcurrentConfig.get_optimal_workers("vc_inspect", len(vcenters))
        workers = min(max(1, workers), len(vcenters))

        if task_type in ("storage_inspect", "storage_inspect_skip_inaccessible"):
            storage_rows: list[dict] = []
            skip_inaccessible = task_type == "storage_inspect_skip_inaccessible"

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(self._collect_storage_for_vcenter, vc, skip_inaccessible): vc
                    for vc in vcenters
                }
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    storage_rows.extend(result.get("storage", []))

            if not save_path or not storage_rows:
                return "", f"存储巡检完成，共 {len(storage_rows)} 条记录"

            os.makedirs(save_path, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = "存储巡检_跳过不可访问存储" if skip_inaccessible else "存储巡检"
            file_path = os.path.join(save_path, f"{prefix}_{timestamp}.xlsx")
            StorageInspector.save_to_excel(file_path, storage_rows, region_map=region_map)
            return file_path, f"存储巡检完成，共 {len(storage_rows)} 条记录"

        all_rows: list[dict] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(self._collect_for_vcenter, vc, task_type): vc for vc in vcenters}
            for future in concurrent.futures.as_completed(futures):
                rows = future.result()
                all_rows.extend(rows)

        if not save_path or not all_rows:
            detail = "0条记录" if not all_rows else f"{len(all_rows)}条记录"
            return "", f"{TASK_TYPES.get(task_type, task_type)}完成，共 {detail}"

        os.makedirs(save_path, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if task_type == "host_inspect":
            file_path = os.path.join(save_path, f"ESXi巡检_{timestamp}.xlsx")
            self._export_host_report(file_path, all_rows, region_map)
            return file_path, f"ESXi巡检完成，共 {len(all_rows)} 条记录"

        file_path = os.path.join(save_path, f"虚拟机巡检_{timestamp}.xlsx")
        self._export_vm_report(file_path, all_rows, region_map)
        return file_path, f"虚拟机巡检完成，共 {len(all_rows)} 条记录"

    def _collect_for_vcenter(self, vc, task_type):
        vc_ip, user, pwd = vc[1], vc[2], vc[3]
        connector = VCenterConnector(vc_ip, user, pwd)
        success, msg = connector.connect()
        if not success:
            raise RuntimeError(f"{vc_ip}: {msg}")

        try:
            if task_type == "host_inspect":
                collector = HostCollector(connector)
                hosts = collector.collect_all_hosts()
                self.db.save_host_inspect(hosts, vc_ip=vc_ip)
                return hosts

            if task_type == "vm_inspect":
                collector = VMCollector(connector)
                vms = collector.collect_all_vms()
                self.db.save_vm_inspect(vms, vc_ip=vc_ip)
                return vms

            raise RuntimeError(f"不支持的任务类型: {task_type}")
        finally:
            connector.disconnect()

    def _collect_storage_for_vcenter(self, vc, skip_inaccessible=False):
        vc_ip, user, pwd = vc[1], vc[2], vc[3]
        connector = VCenterConnector(vc_ip, user, pwd)
        success, msg = connector.connect()
        if not success:
            raise RuntimeError(f"{vc_ip}: {msg}")

        try:
            inspector = StorageInspector(connector)
            storage_rows = inspector.collect_all_datastores(skip_inaccessible=skip_inaccessible)

            return {"storage": storage_rows}
        finally:
            connector.disconnect()

    def _export_host_report(self, file_path, rows, region_map):
        columns = [
            "区域",
            "vCenter",
            "主机名",
            "集群",
            "状态",
            "ESXi版本",
            "厂商",
            "型号",
            "序列号",
            "CPU型号",
            "CPU主频(GHz)",
            "CPU数量",
            "CPU核心数",
            "内存(GB)",
            "运行天数",
            "CPU使用率",
            "内存使用率",
            "证书是否即将过期",
            "VMK适配器",
            "证书过期时间",
            "巡检时间",
        ]
        title_map = {
            "vc_ip": "vCenter",
            "host_name": "主机名",
            "cluster": "集群",
            "status": "状态",
            "esxi_version": "ESXi版本",
            "vendor": "厂商",
            "model": "型号",
            "serial_number": "序列号",
            "cpu_model": "CPU型号",
            "cpu_ghz": "CPU主频(GHz)",
            "cpu_count": "CPU数量",
            "cpu_cores": "CPU核心数",
            "memory_gb": "内存(GB)",
            "uptime_days": "运行天数",
            "cpu_usage": "CPU使用率",
            "memory_usage": "内存使用率",
            "cert_expiring_soon": "证书是否即将过期",
            "vmk_adapters": "VMK适配器",
            "cert_expiry": "证书过期时间",
            "inspect_time": "巡检时间",
        }
        df = pd.DataFrame(rows)
        for column in title_map:
            if column not in df.columns:
                df[column] = ""
        if "vc_ip" in df.columns:
            df.insert(0, "区域", df["vc_ip"].map(lambda x: region_map.get(str(x), "") if pd.notna(x) else ""))
        else:
            df.insert(0, "区域", "")
        df = df[list(title_map.keys())]
        df = df.rename(columns=title_map)
        df = df.reindex(columns=columns)
        df.to_excel(file_path, index=False)
        format_excel_file(file_path)
        highlight_column_cells(file_path, "证书是否即将过期", ["是"])

    def _export_vm_report(self, file_path, rows, region_map):
        export_rows = []
        for row in rows:
            row = dict(row)
            vm_portgroups = row.get("vm_portgroups", "")
            row["nsx_managed"] = row.get("nsx_managed") or derive_vm_nsx_managed(vm_portgroups)
            export_rows.append(row)

        columns = [
            "区域",
            "vCenter",
            "虚拟机名称",
            "集群",
            "主机",
            "电源状态",
            "IP地址",
            "内存(GB)",
            "CPU数量",
            "UUID",
            "备注",
            "系统版本",
            "客户机操作系统",
            "Tools状态",
            "运行天数",
            "存储",
            "磁盘",
            "端口组",
            "是否受NSX纳管",
            "已用空间(GB)",
            "文件夹",
            "巡检时间",
        ]
        title_map = {
            "vc_ip": "vCenter",
            "vm_name": "虚拟机名称",
            "cluster": "集群",
            "host": "主机",
            "power_state": "电源状态",
            "ip_address": "IP地址",
            "memory_gb": "内存(GB)",
            "cpu_count": "CPU数量",
            "uuid": "UUID",
            "annotation": "备注",
            "system_version": "系统版本",
            "guest_os": "客户机操作系统",
            "tools_status": "Tools状态",
            "uptime_days": "运行天数",
            "datastore": "存储",
            "disks": "磁盘",
            "vm_portgroups": "端口组",
            "nsx_managed": "是否受NSX纳管",
            "used_space_gb": "已用空间(GB)",
            "folder": "文件夹",
            "inspect_time": "巡检时间",
        }
        df = pd.DataFrame(export_rows)
        for column in title_map:
            if column not in df.columns:
                df[column] = ""
        if "vc_ip" in df.columns:
            df.insert(0, "区域", df["vc_ip"].map(lambda x: region_map.get(str(x), "") if pd.notna(x) else ""))
        else:
            df.insert(0, "区域", "")
        df = df[list(title_map.keys())]
        df = df.rename(columns=title_map)
        df = df.reindex(columns=columns)
        df.to_excel(file_path, index=False)
        format_excel_file(file_path, highlight_column="是否受NSX纳管", highlight_values={"是", "yes", "true", "1", "y", "nsx"})

    def run_task_now(self, task_id, task_name=None, task_type=None, save_path=None):
        if task_type is None:
            task = next((row for row in self.db.get_scheduled_tasks() if str(row[0]) == str(task_id)), None)
            if not task:
                return
            task_type = task[2]
            save_path = task[6]

        threading.Thread(
            target=self._execute_task,
            args=(task_id, task_name, task_type, save_path),
            daemon=True,
        ).start()

    def is_running(self):
        return self._running
