from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext, ttk
from typing import Any

from src.core.inspection_query import (
    HOST_COLUMNS,
    VM_COLUMNS,
    InspectionQueryResult,
    InspectionQueryService,
)
from src.db.database import Database
from src.ui.theme import COLORS, FONTS


HOST_FIELD_LABELS = {
    "id": "ID",
    "vc_ip": "VC地址",
    "host_name": "主机名称",
    "cluster": "集群",
    "status": "状态",
    "esxi_version": "ESXi版本",
    "vendor": "厂商",
    "model": "型号",
    "serial_number": "序列号",
    "cpu_model": "CPU型号",
    "cpu_ghz": "CPU频率(GHz)",
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

VM_FIELD_LABELS = {
    "id": "ID",
    "vc_ip": "VC地址",
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
    "vm_portgroups": "端口组",
    "nsx_managed": "是否受NSX纳管",
    "disks": "磁盘",
    "used_space_gb": "已用空间(GB)",
    "folder": "文件夹路径",
    "inspect_time": "巡检时间",
}


class InformationQueryPage(ttk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        app: Any | None = None,
        db_path: str | None = None,
    ) -> None:
        super().__init__(parent, style="Card.TFrame")
        self.app = app
        self.service = InspectionQueryService(db_path=db_path)
        self.db = Database()
        self.region_map = self.db.get_vcenter_region_map()
        self._build_ui()
        self._set_output_text("")

    def _build_ui(self) -> None:
        header = ttk.Frame(self, style="Card.TFrame")
        header.pack(fill=tk.X, padx=12, pady=(12, 6))

        ttk.Label(header, text="信息查询", font=FONTS["title"], style="Title.TLabel").pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="请输入虚拟机 IP、虚拟机名称，或 ESXi 主机名称")
        ttk.Label(header, textvariable=self.status_var, style="Secondary.TLabel").pack(side=tk.RIGHT)

        query_frame = ttk.Frame(self, style="Card.TFrame")
        query_frame.pack(fill=tk.X, padx=12, pady=(0, 8))

        ttk.Label(query_frame, text="查询条件:", style="Secondary.TLabel").pack(side=tk.LEFT)

        self.query_var = tk.StringVar()
        self.query_entry = ttk.Entry(query_frame, textvariable=self.query_var, width=42)
        self.query_entry.pack(side=tk.LEFT, padx=(8, 8), fill=tk.X, expand=True)
        self.query_entry.bind("<Return>", lambda _event: self._on_search())

        ttk.Button(query_frame, text="查询", command=self._on_search).pack(side=tk.LEFT, padx=4)
        ttk.Button(query_frame, text="清空", command=self._on_clear).pack(side=tk.LEFT, padx=4)

        ttk.Label(
            self,
            text="支持输入虚拟机 IP、虚拟机名称，或 ESXi 主机名称 / ESXi IP（来自 VMK 适配器）",
            style="Secondary.TLabel",
        ).pack(fill=tk.X, padx=12, pady=(0, 8))

        result_frame = ttk.Labelframe(self, text="查询结果", style="Card.TLabelframe")
        result_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        text_container = tk.Frame(
            result_frame,
            bg=COLORS["accent_light"],
            highlightthickness=1,
            highlightbackground=COLORS["accent"],
        )
        text_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self.result_text = scrolledtext.ScrolledText(
            text_container,
            wrap=tk.WORD,
            font=FONTS["normal"],
            background="#F4FFF4",
            foreground=COLORS["text_primary"],
            insertbackground=COLORS["text_primary"],
            borderwidth=0,
            highlightthickness=0,
            padx=10,
            pady=10,
        )
        self.result_text.pack(fill=tk.BOTH, expand=True)
        self._set_output_text("")

        self.query_entry.focus_set()

    def _on_search(self) -> None:
        term = self.query_var.get().strip()
        result = self.service.search(term)
        self._render_result(result)

    def _on_clear(self) -> None:
        self.query_var.set("")
        self._set_output_text("")
        self.status_var.set("请输入虚拟机 IP、虚拟机名称，或 ESXi 主机名称")
        self.query_entry.focus_set()

    def _render_result(self, result: InspectionQueryResult) -> None:
        self._set_output_text(self._format_result_text(result), self.query_var.get().strip())

        if result.has_results:
            self.status_var.set(f"查询完成：ESXi {result.host_count} 条，虚拟机 {result.vm_count} 条")
        else:
            self.status_var.set("未找到匹配记录")

    def _set_output_text(self, text: str, highlight_term: str = "") -> None:
        self.result_text.config(state="normal")
        self.result_text.delete("1.0", tk.END)
        if text:
            self.result_text.insert("1.0", text)
            if highlight_term:
                self._highlight_term(highlight_term)
        self.result_text.config(state="disabled")

    def _highlight_term(self, term: str) -> None:
        if not term:
            return
        self.result_text.tag_configure("highlight", foreground="#CC0000", font=("Microsoft YaHei", 10, "bold"))
        start_pos = "1.0"
        while True:
            pos = self.result_text.search(term, start_pos, stopindex=tk.END, nocase=True)
            if not pos:
                break
            end_pos = f"{pos}+{len(term)}c"
            self.result_text.tag_add("highlight", pos, end_pos)
            start_pos = end_pos

    def _format_result_text(self, result: InspectionQueryResult) -> str:
        lines: list[str] = []
        query_text = result.query_text or ""
        lines.append(f"查询条件：{query_text if query_text else '（空）'}")
        lines.append("")

        sections: list[tuple[str, list[dict[str, Any]], list[str], dict[str, str]]] = []
        if result.prefer_vm_first:
            if result.vm_records:
                sections.append(("虚拟机巡检结果", result.vm_records, result.vm_columns, VM_FIELD_LABELS))
            if result.host_records:
                sections.append(("ESXi主机巡检结果", result.host_records, result.host_columns, HOST_FIELD_LABELS))
        else:
            if result.host_records:
                sections.append(("ESXi主机巡检结果", result.host_records, result.host_columns, HOST_FIELD_LABELS))
            if result.vm_records:
                sections.append(("虚拟机巡检结果", result.vm_records, result.vm_columns, VM_FIELD_LABELS))

        for title, records, columns, labels in sections:
            lines.append(f"{title}（{len(records)} 条）")
            lines.append(self._format_records(records, columns, labels))
            lines.append("")

        if not result.host_records and not result.vm_records:
            lines.append("未找到匹配记录。")

        return "\n".join(line for line in lines if line is not None).strip()

    def _format_records(
        self,
        records: list[dict[str, Any]],
        columns: list[str],
        labels: dict[str, str],
    ) -> str:
        blocks: list[str] = []
        for index, record in enumerate(records, start=1):
            block_lines = [f"{index}."]
            block_lines.append(f"区域：{self._get_region(record)}")
            for column in columns:
                label = labels.get(column, column)
                value = record.get(column)
                block_lines.append(f"{label}：{self._format_value(value)}")
            blocks.append("\n".join(block_lines))
        return "\n\n".join(blocks)

    def _get_region(self, record: dict[str, Any]) -> str:
        vc_ip = str(record.get("vc_ip", "") or "")
        return self.region_map.get(vc_ip, "")

    @staticmethod
    def _format_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, float):
            return f"{value:g}"
        return str(value)


def build_information_query_page(
    parent: tk.Widget,
    app: Any | None = None,
    db_path: str | None = None,
) -> InformationQueryPage:
    return InformationQueryPage(parent, app=app, db_path=db_path)


__all__ = [
    "InformationQueryPage",
    "build_information_query_page",
]
