import tkinter as tk
from tkinter import ttk, messagebox
import os
from src.db.database import Database
from src.ui.theme import apply_theme, TAB_ICONS, COLORS, FONTS
from src.ui.enhanced_widgets import EnhancedStatusBar
from src.ui.vc_manager import VCManagerPage
from src.ui.host_inspect import HostInspectPage
from src.ui.vm_inspect import VMInspectPage
from src.ui.batch_operations import BatchOperationsPage
from src.ui.clone import ClonePage


class VCenterManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Vcenter管理巡检工具-CSDN:小周学学学")
        self.root.geometry("1400x850")
        self.root.minsize(1200, 700)

        apply_theme(root)

        self.db = Database()

        self._create_menu()
        self._create_ui()
        self._init_templates()

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _create_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="📁 文件", menu=file_menu)
        file_menu.add_command(label="退出", command=self._on_closing)

        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="❓ 帮助", menu=help_menu)
        help_menu.add_command(label="📖 使用说明", command=self._show_help)
        help_menu.add_command(label="ℹ️ 关于", command=self._show_about)

    def _create_ui(self):
        toolbar = ttk.Frame(self.root, style='Toolbar.TFrame')
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        title_label = ttk.Label(
            toolbar,
            text="🖥️ Vcenter管理巡检工具",
            font=FONTS['title']
        )
        title_label.pack(side=tk.LEFT, padx=10)

        self.notebook = ttk.Notebook(self.root, style='Main.TNotebook')
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.vc_page = ttk.Frame(self.notebook, style='Card.TFrame')
        self.notebook.add(self.vc_page, text=f" {TAB_ICONS['vCenter管理']} vCenter管理")
        self.vc_manager = VCManagerPage(self.vc_page, self)
        self.vc_manager.set_refresh_callback(self._on_vc_changed)

        self.host_page = ttk.Frame(self.notebook, style='Card.TFrame')
        self.notebook.add(self.host_page, text=f" {TAB_ICONS['ESXi主机巡检']} ESXi主机巡检")
        self.host_inspect = HostInspectPage(self.host_page, self)

        self.vm_page = ttk.Frame(self.notebook, style='Card.TFrame')
        self.notebook.add(self.vm_page, text=f" {TAB_ICONS['虚拟机巡检']} 虚拟机巡检")
        self.vm_inspect = VMInspectPage(self.vm_page, self)

        self.batch_page = ttk.Frame(self.notebook, style='Card.TFrame')
        self.notebook.add(self.batch_page, text=f" {TAB_ICONS['批量操作']} 批量操作")
        BatchOperationsPage(self.batch_page, self)

        self.clone_page = ttk.Frame(self.notebook, style='Card.TFrame')
        self.notebook.add(self.clone_page, text=f" {TAB_ICONS['虚拟机克隆']} 虚拟机克隆")
        ClonePage(self.clone_page, self)

        self.notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)

        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill=tk.X, padx=5, pady=(0, 2))

        self.status_bar = EnhancedStatusBar(status_frame)
        self.status_bar.pack(fill=tk.X)

    def _on_tab_changed(self, event):
        self._refresh_all_vc_lists()

    def _on_vc_changed(self):
        self._refresh_all_vc_lists()

    def _refresh_all_vc_lists(self):
        if hasattr(self, 'host_inspect'):
            self.host_inspect._refresh_vc_list()
        if hasattr(self, 'vm_inspect'):
            self.vm_inspect._refresh_vc_list()

    def _init_templates(self):
        template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')
        os.makedirs(template_dir, exist_ok=True)

        templates = {
            'iscsi.xlsx': self._get_iscsi_template(),
            'vmotion.xlsx': self._get_vmotion_template(),
            'modify_remark.xlsx': self._get_remark_template(),
            'rename.xlsx': self._get_rename_template(),
            'vm_clone.xlsx': self._get_clone_template()
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
            ['VC', 'ESXI主机', 'iSCSI动态发现IP'],
            ['192.168.1.250', 'esxi-01', '192.168.100.10,192.168.100.11']
        ]

    def _get_vmotion_template(self):
        return [
            ['VC', '虚拟机名称', '迁移后主机', '迁移后存储'],
            ['192.168.1.250', 'vm-test-01', 'esxi-02', 'datastore1']
        ]

    def _get_remark_template(self):
        return [
            ['VC', 'UUID', '备注'],
            ['192.168.1.250', '501ff123-4567-8901-abcd-ef0123456789', '测试虚拟机']
        ]

    def _get_rename_template(self):
        return [
            ['VC', 'UUID', '新名称'],
            ['192.168.1.250', '501ff123-4567-8901-abcd-ef0123456789', 'vm-new-01']
        ]

    def _get_clone_template(self):
        return [
            ['VC', '主机名称', '存储名称', '文件夹名称', '模板名称', '自定义规范名称',
             '虚拟机名称', '主机名', 'CPU数量', '内存大小', '端口组', 'IP地址',
             '子网掩码', '网关', 'DNS1', 'DNS2', '硬盘', '备注'],
            ['192.168.1.250', 'esxi-01', 'datastore1', 'folder1', 'win2019-template', '',
             'vm-new-01', 'vmnew01', '2', '4', 'VLAN100', '192.168.1.100',
             '255.255.255.0', '192.168.1.1', '8.8.8.8', '114.114.114.114', '100', '生产环境']
        ]

    def _show_about(self):
        messagebox.showinfo("关于", "vCenter管理巡检工具\n版本: 2.0\n用于批量管理vCenter和ESXi主机")

    def _show_help(self):
        help_text = """【使用说明】

更多工具请关注CSDN-小周学学学

一、vCenter管理
- 添加/删除/测试vCenter连接信息
- 凭据会被保存，关闭程序后再次打开仍然有效
- 支持SSL证书过期时间显示

二、ESXi主机巡检
- 选择vCenter后点击"开始巡检"采集数据
- "一键巡检"可同时巡检所有已添加的vCenter（并发5个）
- 支持搜索主机名、筛选（vCenter/集群/状态/版本/厂商）
- 支持列头筛选和高级筛选
- 可导出当前vCenter或所有vCenter的数据
- "导出iSCSI信息"可导出所有ESXi主机的iSCSI配置

三、虚拟机巡检
- 选择vCenter后点击"开始巡检"采集数据
- "一键巡检"可同时巡检所有已添加的vCenter（并发5个）
- 支持搜索虚拟机名/IP、筛选（vCenter/集群/存储/电源状态/Tools状态）
- 支持列头筛选和高级筛选
- 支持横向滚动查看更多列

四、批量操作
【iSCSI挂载】
- VC: vCenter IP地址（必填）
- ESXi主机: 目标ESXi主机名（必填）
- iSCSI目标IP: 目标iSCSI服务器IP，多个用逗号分隔（必填）
- 效果: 为指定ESXi主机添加iSCSI存储

【虚拟机迁移】
- VC: vCenter IP地址（必填）
- 虚拟机名称: 要迁移的VM名称（必填）
- 迁移后主机: 目标ESXi主机名（可选）
- 迁移后存储: 目标存储名称（可选）
- 效果:
  * 只填主机 = 只迁移计算资源
  * 只填存储 = 只迁移存储资源
  * 两者都填 = 同时迁移计算和存储

【修改备注】
- VC: vCenter IP地址（必填）
- 主机名: 虚拟机名称（必填）
- 备注: 要设置的备注内容（必填）
- 效果: 修改虚拟机的备注/注释

【重命名】
- VC: vCenter IP地址（必填）
- 主机名: 原虚拟机名称（必填）
- 新名称: 新的虚拟机名称（必填）
- 效果: 重命名虚拟机

【分布式交换机/端口组】
Excel文件包含两个Sheet:
- 分布式交换机（Sheet1）:
  * VC: vCenter IP地址（必填）
  * 数据中心: 数据中心名称（必填）
  * 分布式交换机名称: 交换机名称（必填）
  * 默认4个上行链路，不创建默认端口组
  * 已存在的交换机不会重复创建，会跳过
- 分布式端口组（Sheet2）:
  * VC: vCenter IP地址（必填）
  * 分布式交换机名称: 目标交换机名称（必填）
  * 端口组名称: 端口组名称（必填）
  * 端口组VLAN: VLAN ID（必填，填写0表示不标记VLAN）
  * 已存在的端口组不会重复创建，会跳过
- 执行顺序:
  * 交换机Sheet为空 = 只创建端口组
  * 端口组Sheet为空 = 只创建交换机
  * 两者都有 = 先创建交换机再创建端口组

【模板下载】: 每个批量操作都有对应模板，点击下载后按格式填写

五、批量克隆（最常用功能，详细说明）

【Excel模板列说明】（共18列）:
1. VC: vCenter IP地址（必填）
2. 主机名称: 目标ESXi主机名（必填，VM要部署到的目标主机）
3. 存储名称: 目标数据存储名称（必填，VM的虚拟磁盘存放位置）
4. 文件夹名称: VM所在文件夹（可选，不填则放到数据中心根目录；填了则自动创建不存在的文件夹再放入）
5. 模板名称: 克隆源模板名称（必填，存在于vCenter中的VM模板）
6. 自定义规范名称: Windows域或Linux自定义规范（可选，用于OS定制）
7. 虚拟机名称: 新建VM的名称（必填）
8. 主机名: 虚拟机操作系统 hostname（可选，不填则不设置hostname）
9. CPU数量: CPU核心数（可选，不填则保留模板原CPU配置）
10. 内存大小: 内存GB数（可选，不填则保留模板原内存配置）
11. 端口组: 网络端口组名称（可选，不填则保留原有网络）
12. IP地址: 虚拟机IP（可选，配合自定义规范实现IP配置）
13. 子网掩码: 子网掩码（可选，默认255.255.255.0）
14. 网关: 网关地址（可选）
15. DNS1: 主DNS服务器（可选，配合自定义规范使用）
16. DNS2: 备用DNS服务器（可选，配合自定义规范使用）
17. 硬盘: 硬盘大小GB（可选，多个硬盘用换行分隔，如"100\n200"）
18. 备注: VM备注/描述（可选）

【使用场景和示例】:

场景1: 快速克隆（最简单）
- 只填写必填项: VC、主机名称、存储名称、模板名称、虚拟机名称
- 效果: 从模板克隆VM到目标主机和存储，其他保持默认

场景2: 完整配置克隆（最常用）
- 填写所有项包括IP地址、DNS等
- 效果: 完整克隆并通过自定义规范配置OS（IP、hostname、DNS等）
- 注意: 需要在vCenter中预先创建好自定义规范

场景3: 自定义硬件配置
- 填写CPU数量、内存大小、硬盘
- 效果: 克隆时调整VM硬件规格

【重要提示】:
- 模板必须是已存在于vCenter中的VM模板
- 主机名称和存储必须在指定的vCenter中存在
- 如果填写IP/DNS等网络配置，必须同时填写自定义规范名称
- 克隆完成后会自动开机
- 支持5个并发克隆任务，效率更高

六、其他
- 所有vCenter操作都支持并发执行，提高效率
- 状态栏显示当前操作进度
- 按ESC键或关闭按钮安全退出"""

        help_win = tk.Toplevel(self.root)
        help_win.title("使用说明")
        help_win.geometry("700x850")

        text = tk.Text(help_win, wrap=tk.WORD, padx=10, pady=10, font=FONTS['normal'])
        text.pack(fill=tk.BOTH, expand=True)
        text.insert('1.0', help_text)
        text.config(state='disabled')

        scrollbar = ttk.Scrollbar(help_win, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.config(yscrollcommand=scrollbar.set)

    def _on_closing(self):
        if messagebox.askyesno("退出", "确定要退出吗？"):
            self.root.destroy()

    def update_status(self, message):
        self.status_bar.set_loading(message)
