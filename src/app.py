import os
import tkinter as tk
from tkinter import messagebox, ttk

from src.core.power_scheduler import PowerTaskScheduler
from src.core.power_task_store import PowerTaskStore
from src.core.scheduler import TaskScheduler
from src.db.database import Database
from src.ui.batch_operations import BatchOperationsPage
from src.ui.clone import ClonePage
from src.ui.enhanced_widgets import EnhancedStatusBar
from src.ui.host_inspect import HostInspectPage
from src.ui.information_query import InformationQueryPage
from src.ui.schedule import InspectionScheduleTab, PowerTaskTab
from src.ui.theme import FONTS, apply_theme
from src.ui.vc_manager import VCManagerPage
from src.ui.vcenter_cert import VCenterCertPage
from src.ui.vm_inspect import VMInspectPage


class VCenterManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("VCenter管理巡检工具")
        self.root.geometry("1400x850")
        self.root.minsize(1200, 700)

        apply_theme(root)

        self.db = Database()
        self.inspection_scheduler = TaskScheduler(self)
        self.power_store = PowerTaskStore()
        self.power_scheduler = PowerTaskScheduler(self, store=self.power_store, db=self.db)

        self._create_menu()
        self._create_ui()
        self._init_templates()

        self.inspection_scheduler.start()
        self.power_scheduler.start()

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _create_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="退出", command=self._on_closing)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="使用说明", command=self._show_help)
        help_menu.add_command(label="关于", command=self._show_about)

    def _create_ui(self):
        toolbar = ttk.Frame(self.root, style="Toolbar.TFrame")
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        title_label = ttk.Label(
            toolbar,
            text="VCenter管理巡检工具",
            font=FONTS["title"],
        )
        title_label.pack(side=tk.LEFT, padx=10)

        self.notebook = ttk.Notebook(self.root, style="Main.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.vc_page = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.vc_page, text="vCenter管理")
        self.vc_manager = VCManagerPage(self.vc_page, self)
        self.vc_manager.set_refresh_callback(self._on_vc_changed)

        self.host_page = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.host_page, text="ESXi主机巡检")
        self.host_inspect = HostInspectPage(self.host_page, self)

        self.vm_page = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.vm_page, text="虚拟机巡检")
        self.vm_inspect = VMInspectPage(self.vm_page, self)

        self.batch_page = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.batch_page, text="批量操作")
        self.batch_operations = BatchOperationsPage(self.batch_page, self)

        self.clone_page = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.clone_page, text="虚拟机克隆")
        ClonePage(self.clone_page, self)

        self.vcenter_cert_page = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.vcenter_cert_page, text="VCenter证书查询及续订")
        self.vcenter_cert = VCenterCertPage(self.vcenter_cert_page, self)

        self.inspection_schedule_page = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.inspection_schedule_page, text="定时巡检")
        self.inspection_schedule = InspectionScheduleTab(
            self.inspection_schedule_page,
            self,
            self.db,
            self.inspection_scheduler,
        )

        self.power_task_page = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.power_task_page, text="定时开关机")
        self.power_task = PowerTaskTab(
            self.power_task_page,
            self,
            self.db,
            self.power_store,
            self.power_scheduler,
        )

        self.information_query_page = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.information_query_page, text="信息查询")
        self.information_query = InformationQueryPage(self.information_query_page, self)
        self.information_query.pack(fill=tk.BOTH, expand=True)

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=5, pady=(0, 2))

        self.status_bar = EnhancedStatusBar(status_frame)
        self.status_bar.pack(fill=tk.X)

    def _on_tab_changed(self, event):
        self._refresh_all_vc_lists()

    def _on_vc_changed(self):
        self._refresh_all_vc_lists()

    def _refresh_all_vc_lists(self):
        if hasattr(self, "host_inspect"):
            self.host_inspect._refresh_vc_list()
        if hasattr(self, "vm_inspect"):
            self.vm_inspect._refresh_vc_list()
        if hasattr(self, "vcenter_cert"):
            self.vcenter_cert._refresh_vc_list()
        if hasattr(self, "inspection_schedule"):
            self.inspection_schedule.load_tasks()
        if hasattr(self, "power_task"):
            self.power_task.load_tasks()

    def open_batch_operation(self, operation_key):
        if hasattr(self, "batch_operations"):
            self.batch_operations.set_operation(operation_key)
        if hasattr(self, "notebook") and hasattr(self, "batch_page"):
            self.notebook.select(self.batch_page)

    def _init_templates(self):
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
        os.makedirs(template_dir, exist_ok=True)

        templates = {
            "iscsi.xlsx": self._get_iscsi_template(),
            "vmotion.xlsx": self._get_vmotion_template(),
            "modify_remark.xlsx": self._get_remark_template(),
            "rename.xlsx": self._get_rename_template(),
            "vm_clone.xlsx": self._get_clone_template(),
            "vm_resize.xlsx": self._get_vm_resize_template(),
        }

        for filename, data in templates.items():
            filepath = os.path.join(template_dir, filename)
            if not os.path.exists(filepath):
                self._create_template_file(filepath, data)

    def _create_template_file(self, filepath, data):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        for row in data:
            ws.append(row)
        wb.save(filepath)

    def _get_iscsi_template(self):
        return [
            ["VC", "ESXi主机", "iSCSI动态发现IP"],
            ["192.168.1.250", "esxi-01", "192.168.100.10,192.168.100.11"],
        ]

    def _get_vmotion_template(self):
        return [
            ["VC", "虚拟机名称", "迁移后主机", "迁移后存储"],
            ["192.168.1.250", "vm-test-01", "esxi-02", "datastore1"],
        ]

    def _get_remark_template(self):
        return [
            ["VC", "UUID", "备注"],
            ["192.168.1.250", "501ff123-4567-8901-abcd-ef0123456789", "测试虚拟机"],
        ]

    def _get_rename_template(self):
        return [
            ["VC", "UUID", "新名称"],
            ["192.168.1.250", "501ff123-4567-8901-abcd-ef0123456789", "vm-new-01"],
        ]

    def _get_clone_template(self):
        return [
            [
                "VC",
                "主机名称",
                "存储名称",
                "文件夹名称",
                "模板名称",
                "自定义规范名称",
                "虚拟机名称",
                "主机名",
                "CPU数量",
                "内存大小",
                "端口组",
                "IP地址",
                "子网掩码",
                "网关",
                "DNS1",
                "DNS2",
                "硬盘",
                "备注",
            ],
            [
                "192.168.1.250",
                "esxi-01",
                "datastore1",
                "folder1",
                "win2019-template",
                "",
                "vm-new-01",
                "vmnew01",
                "2",
                "4",
                "VLAN100",
                "192.168.1.100",
                "255.255.255.0",
                "192.168.1.1",
                "8.8.8.8",
                "114.114.114.114",
                "100",
                "生产环境",
            ],
        ]

    def _get_vm_resize_template(self):
        return [
            ["VC", "虚拟机名称", "CPU", "内存"],
            ["192.168.1.250", "vm-test-01", "4", "8"],
            ["192.168.1.250", "vm-test-02", "", "16"],
            ["192.168.1.250", "vm-test-03", "8", ""],
        ]

    def _show_about(self):
        messagebox.showinfo(
            "关于",
            "VCenter管理巡检工具\n版本: 2.0\n用于批量管理 vCenter、ESXi 主机和虚拟机。",
        )

    def _show_help(self):
        help_text = """VCenter管理巡检工具 - 使用说明书 (v2.0)

═══════════════════════════════════════════════════════════════════
一、软件概述
═══════════════════════════════════════════════════════════════════
VCenter管理巡检工具是一款用于批量管理VMware vCenter、ESXi主机和虚拟机的自动化工具。
支持多vCenter统一管理，提供巡检、批量操作、克隆、证书管理、定时任务等功能。

═══════════════════════════════════════════════════════════════════
二、功能模块总览
═══════════════════════════════════════════════════════════════════
【vCenter管理】添加、编辑、删除vCenter连接
【ESXi主机巡检】采集ESXi主机硬件、性能、证书信息
【虚拟机巡检】采集虚拟机配置、状态、网络信息
【批量操作】10种批量操作类型（iSCSI、迁移、重命名等）
【虚拟机克隆】从模板批量克隆虚拟机
【VCenter证书查询及续订】VMCA证书查询与续订
【定时巡检】自动定时执行巡检任务
【定时开关机】定时开关虚拟机
【信息查询】智能查询主机和虚拟机信息

═══════════════════════════════════════════════════════════════════
三、vCenter管理
═══════════════════════════════════════════════════════════════════
字段说明:
  • IP地址 [必填]: vCenter服务器IP
  • 区域 [选填]: 自定义区域标识
  • 用户名 [必填]: vCenter登录用户名
  • 密码 [必填]: vCenter登录密码
  • root密码 [选填]: ESXi root密码（用于证书续订）
  • 备注 [选填]: 备注信息

操作: 添加 → 编辑 → 删除 → 测试连接

═══════════════════════════════════════════════════════════════════
四、ESXi主机巡检 - 巡检内容
═══════════════════════════════════════════════════════════════════
采集字段:
  • vCenter, 主机名, 集群, 状态
  • ESXi版本, 厂商, 型号, 序列号
  • CPU型号, CPU主频, CPU数量, CPU核心数
  • 内存(GB), 运行天数
  • CPU使用率, 内存使用率
  • 证书是否即将过期, 证书过期时间
  • VMK适配器

工具栏: 开始巡检 | 一键巡检 | 导出Excel | iSCSI | 端口组 | 本地硬盘 | 存储巡检 | 网卡巡检

═══════════════════════════════════════════════════════════════════
五、虚拟机巡检 - 巡检内容
═══════════════════════════════════════════════════════════════════
采集字段:
  • vCenter, 虚拟机名, 集群, 主机, 存储
  • 是否受NSX纳管, 备注
  • 电源状态, IP地址, 内存(GB), CPU数量
  • UUID, 系统版本, 客户机操作系统
  • Tools状态, 运行天数
  • 磁盘, 端口组, 已用空间(GB)

═══════════════════════════════════════════════════════════════════
六、右键菜单功能
═══════════════════════════════════════════════════════════════════
【ESXi主机右键菜单】
  • iSCSI挂载 - 批量挂载iSCSI存储
  • ESXi证书续订 - 批量续订ESXi证书
  • 开启SSH - 批量开启SSH服务
  • 配置NTP - 批量配置NTP服务器
  • 修改root密码 - 批量修改root密码

【虚拟机右键菜单】
  • 虚拟机迁移 - 迁移虚拟机到目标主机/存储
  • 添加网络适配器 - 添加虚拟网卡
  • 修改备注 - 修改虚拟机备注
  • 批量重命名 - 批量修改虚拟机名称
  • 添加硬盘 - 添加虚拟硬盘
  • CPU内存扩容 - 调整CPU/内存配置

═══════════════════════════════════════════════════════════════════
七、批量操作 - 模板字段说明
═══════════════════════════════════════════════════════════════════
【iSCSI模板】VC[必填] | ESXi主机[必填] | iSCSI动态发现IP[必填]

【虚拟机迁移模板】VC[必填] | 虚拟机名称[必填] | 迁移后主机[至少填一个] | 迁移后存储[至少填一个]

【修改备注模板】VC[必填] | UUID[必填] | 备注[必填]

【批量重命名模板】VC[必填] | UUID[必填] | 新名称[必填]

【CPU内存扩容模板】VC[必填] | 虚拟机名称[必填] | CPU[至少填一个] | 内存[至少填一个]

【虚拟机克隆模板】
  必填: VC, 主机名称, 存储名称, 模板名称, 虚拟机名称, 主机名
  选填: 文件夹名称, 自定义规范名称, CPU数量, 内存大小, 端口组,
        IP地址, 子网掩码, 网关, DNS1, DNS2, 硬盘, 备注

═══════════════════════════════════════════════════════════════════
八、VCenter证书查询及续订
═══════════════════════════════════════════════════════════════════
功能:
  • 查询VMCA证书信息（需配置root密码）
  • 执行VMCA证书续订（管理面可能短时中断）
  • 过期证书会用红色标记

操作: 选择vCenter → 查询证书 → 一键续订(VMCA)

═══════════════════════════════════════════════════════════════════
九、定时巡检
═══════════════════════════════════════════════════════════════════
任务类型: ESXi巡检 | 虚拟机巡检 | 存储巡检 | 存储巡检-跳过不可访问存储
调度方式: 每天 | 每周 | 仅一次
执行时间: HH:MM格式

右键菜单: 立即执行 | 编辑 | 删除

═══════════════════════════════════════════════════════════════════
十、定时开关机
═══════════════════════════════════════════════════════════════════
动作: 开机 | 关机
目标输入格式: UUID / 虚拟机名称 / IP地址（每行一个，支持逗号分隔）

═══════════════════════════════════════════════════════════════════
十一、信息查询
═══════════════════════════════════════════════════════════════════
支持查询:
  • 虚拟机IP地址
  • 虚拟机名称
  • ESXi主机名
  • ESXi IP（来自VMK适配器）

操作: 输入查询条件 → 点击查询/回车 → 查看结果

═══════════════════════════════════════════════════════════════════
十二、打包为EXE
═══════════════════════════════════════════════════════════════════
执行命令: pyinstaller setup.spec

═══════════════════════════════════════════════════════════════════"""

        help_win = tk.Toplevel(self.root)
        help_win.title("VCenter管理巡检工具 - 使用说明书")
        help_win.geometry("850x750")

        text = tk.Text(help_win, wrap=tk.WORD, padx=15, pady=15, font=("Microsoft YaHei", 10))
        text.pack(fill=tk.BOTH, expand=True)
        text.insert("1.0", help_text)
        text.config(state="disabled")

        scrollbar = ttk.Scrollbar(help_win, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.config(yscrollcommand=scrollbar.set)

    def _on_closing(self):
        if messagebox.askyesno("退出", "确定要退出吗？"):
            for scheduler_name in ("inspection_scheduler", "power_scheduler"):
                scheduler = getattr(self, scheduler_name, None)
                if scheduler and hasattr(scheduler, "stop"):
                    try:
                        scheduler.stop()
                    except Exception:
                        pass
            self.root.quit()
            self.root.destroy()

    def update_status(self, message):
        self.status_bar.set_loading(message)
