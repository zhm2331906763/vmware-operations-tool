import tkinter as tk
from tkinter import ttk, messagebox
import threading
from src.db.database import Database
from src.core.vcenter_connector import VCenterConnector
from src.core.host_collector import HostCollector
from src.ui.theme import COLORS, FONTS
from src.ui.enhanced_widgets import EnhancedButton


class VCManagerPage:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.db = Database()
        self.refresh_callback = None
        self._create_ui()
        self._load_vcenters()

    def set_refresh_callback(self, callback):
        self.refresh_callback = callback

    def _notify_refresh(self):
        if self.refresh_callback:
            self.refresh_callback()

    def _create_ui(self):
        toolbar = ttk.Frame(self.parent, style='Card.TFrame')
        toolbar.pack(fill=tk.X, padx=10, pady=5)

        btn_frame = ttk.Frame(toolbar)
        btn_frame.pack(fill=tk.X)

        EnhancedButton(btn_frame, "添加", "➕", command=self._add_vc).pack(side=tk.LEFT, padx=2)
        EnhancedButton(btn_frame, "编辑", "✏️", command=self._edit_vc).pack(side=tk.LEFT, padx=2)
        EnhancedButton(btn_frame, "删除", "🗑️", command=self._delete_vc).pack(side=tk.LEFT, padx=2)
        EnhancedButton(btn_frame, "测试连接", "🔗", command=self._test_connection).pack(side=tk.LEFT, padx=2)
        EnhancedButton(btn_frame, "刷新", "🔄", command=self._load_vcenters).pack(side=tk.LEFT, padx=2)

        table_frame = ttk.Frame(self.parent)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        h_scroll = ttk.Scrollbar(table_frame, orient='horizontal')
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        v_scroll = ttk.Scrollbar(table_frame, orient='vertical')
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('ID', 'IP地址', '区域', '用户名', 'SSL证书过期', 'root密码', '备注', '创建时间', '更新时间')
        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings',
                                 xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        h_scroll.configure(command=self.tree.xview)
        v_scroll.configure(command=self.tree.yview)

        widths = {'ID': 50, 'IP地址': 140, '区域': 120, '用户名': 120, 'SSL证书过期': 120,
                  'root密码': 90, '备注': 150, '创建时间': 140, '更新时间': 140}

        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=widths.get(col, 120), minwidth=80)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree.tag_configure('odd', background=COLORS['row_alt'])
        self.tree.tag_configure('even', background=COLORS['bg_card'])

    def _load_vcenters(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        vcenters = self.db.get_vcenters()

        for i, vc in enumerate(vcenters):
            vc_id, ip, user, pwd, remark, created, updated, root_pwd, region = vc
            cert_expiry = self._get_vc_cert_expiry(ip)
            root_pwd_status = "已配置" if root_pwd else "未配置"
            tags = 'odd' if i % 2 == 0 else 'even'
            self.tree.insert(
                '',
                tk.END,
                values=(vc_id, ip, region or '', user, cert_expiry, root_pwd_status, remark, created, updated),
                tags=tags
            )

    def _get_vc_cert_expiry(self, ip):
        try:
            import ssl
            import socket
            from cryptography import x509
            from cryptography.hazmat.backends import default_backend

            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

            with socket.create_connection((ip, 443), timeout=3) as sock:
                with context.wrap_socket(sock, server_hostname=ip) as ssock:
                    cert_der = ssock.getpeercert(binary_form=True)

            if not cert_der:
                return "获取失败"

            cert = x509.load_der_x509_certificate(cert_der, default_backend())
            not_after = cert.not_valid_after_utc if hasattr(cert, 'not_valid_after_utc') else cert.not_valid_after
            if not_after.tzinfo:
                not_after = not_after.replace(tzinfo=None)
            return not_after.strftime('%Y-%m-%d')
        except Exception as e:
            return f"获取失败"

    def _add_vc(self):
        self._show_vc_dialog()

    def _edit_vc(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请选择要编辑的vCenter")
            return

        item = self.tree.item(selection[0])
        values = item['values']
        vc_id = values[0]
        vc_data = next((v for v in self.db.get_vcenters() if v[0] == vc_id), None)
        if not vc_data:
            messagebox.showerror("错误", "未找到vCenter信息")
            return
        self._show_vc_dialog(vc_data)

    def _delete_vc(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请选择要删除的vCenter")
            return

        if messagebox.askyesno("确认", "确定要删除选中的vCenter吗？"):
            item = self.tree.item(selection[0])
            vc_id = item['values'][0]
            self.db.delete_vcenter(vc_id)
            self._load_vcenters()
            self._notify_refresh()
            messagebox.showinfo("提示", "删除成功")

    def _test_connection(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("提示", "请选择要测试的vCenter")
            return

        item = self.tree.item(selection[0])
        vc_id = item['values'][0]

        vcenters = self.db.get_vcenters()
        vc = next((v for v in vcenters if v[0] == vc_id), None)
        if not vc:
            messagebox.showerror("错误", "未找到vCenter信息")
            return

        ip, user, password = vc[1], vc[2], vc[3]

        progress = tk.Toplevel(self.parent)
        progress.title("测试连接")
        progress.geometry("300x120")
        progress.transient(self.parent)
        progress.grab_set()

        ttk.Label(progress, text=f"正在连接 {ip}...").pack(pady=20)

        def test():
            connector = VCenterConnector(ip, user, password)
            success, msg = connector.test_connection()
            progress.destroy()
            if success:
                messagebox.showinfo("测试结果", f"连接成功!\n{msg}")
            else:
                messagebox.showerror("测试结果", f"连接失败\n{msg}")

        threading.Thread(target=test, daemon=True).start()

    def _show_vc_dialog(self, vc_data=None):
        dialog = tk.Toplevel(self.parent)
        dialog.title("添加vCenter" if not vc_data else "编辑vCenter")
        dialog.geometry("480x430")
        dialog.transient(self.parent)
        dialog.grab_set()

        dialog.configure(bg=COLORS['bg_card'])

        main_frame = ttk.Frame(dialog, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="IP地址:", font=FONTS['normal']).grid(row=0, column=0, sticky=tk.W, pady=8)
        ip_entry = ttk.Entry(main_frame, width=35)
        ip_entry.grid(row=0, column=1, pady=8)

        ttk.Label(main_frame, text="区域:", font=FONTS['normal']).grid(row=1, column=0, sticky=tk.W, pady=8)
        region_var = tk.StringVar()
        region_entry = ttk.Entry(main_frame, textvariable=region_var, width=35)
        region_entry.grid(row=1, column=1, pady=8)

        ttk.Label(main_frame, text="用户名:", font=FONTS['normal']).grid(row=2, column=0, sticky=tk.W, pady=8)
        user_entry = ttk.Entry(main_frame, width=35)
        user_entry.grid(row=2, column=1, pady=8)

        ttk.Label(main_frame, text="密码:", font=FONTS['normal']).grid(row=3, column=0, sticky=tk.W, pady=8)
        pwd_entry = ttk.Entry(main_frame, width=35, show='*')
        pwd_entry.grid(row=3, column=1, pady=8)

        ttk.Label(main_frame, text="root密码(可选):", font=FONTS['normal']).grid(row=4, column=0, sticky=tk.W, pady=8)
        root_pwd_entry = ttk.Entry(main_frame, width=35, show='*')
        root_pwd_entry.grid(row=4, column=1, pady=8)

        tip_label = ttk.Label(
            main_frame,
            text="未配置root密码时，无法执行VMCA证书查询及续订",
            font=FONTS['small'],
            foreground=COLORS['warning']
        )
        tip_label.grid(row=5, column=0, columnspan=2, sticky=tk.W)

        ttk.Label(main_frame, text="备注:", font=FONTS['normal']).grid(row=6, column=0, sticky=tk.NW, pady=8)
        remark_text = tk.Text(main_frame, width=30, height=5, font=FONTS['normal'])
        remark_text.grid(row=6, column=1, pady=8)

        if vc_data:
            ip_entry.insert(0, vc_data[1])
            user_entry.insert(0, vc_data[2])
            pwd_entry.insert(0, vc_data[3])
            root_pwd_entry.insert(0, vc_data[7] or '')
            region_var.set(vc_data[8] or '')
            remark_text.insert('1.0', vc_data[4] or '')

        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=20)

        def save():
            ip = ip_entry.get().strip()
            region = region_entry.get().strip()
            user = user_entry.get().strip()
            pwd = pwd_entry.get()
            root_pwd = root_pwd_entry.get()
            remark = remark_text.get('1.0', tk.END).strip()

            if not ip or not user or not pwd:
                messagebox.showwarning("提示", "请填写完整信息")
                return

            if vc_data:
                self.db.update_vcenter(vc_data[0], ip, user, pwd, remark, root_pwd, region)
            else:
                self.db.add_vcenter(ip, user, pwd, remark, root_pwd, region)

            self._load_vcenters()
            self._notify_refresh()
            dialog.destroy()
            messagebox.showinfo("提示", "保存成功")

        ttk.Button(btn_frame, text="保存", command=save, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy, width=10).pack(side=tk.LEFT, padx=5)
