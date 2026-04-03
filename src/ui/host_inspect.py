import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import pandas as pd
from src.db.database import Database
from src.core.vcenter_connector import VCenterConnector
from src.core.host_collector import HostCollector
from src.ui.theme import COLORS, FONTS
from src.ui.enhanced_widgets import EnhancedButton, FilterableTable, ProgressDialog


class HostInspectPage:
    DISPLAY_COLUMNS = ('vCenter', '主机名', '集群', 'CPU使用率', '内存使用率')
    COLUMN_WIDTHS = {
        'vCenter': 120, '主机名': 180, '集群': 120,
        'CPU使用率': 80, '内存使用率': 80
    }
    DB_COLUMN_INDICES = [1, 2, 3, 15, 16]
    DB_VC_IP_INDEX = 1
    DB_HOST_NAME_INDEX = 2

    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.db = Database()
        self.vc_list = {}
        self.all_data = []
        self._host_info_map = {}
        self._create_ui()

    def _create_ui(self):
        toolbar = ttk.Frame(self.parent, style='Card.TFrame')
        toolbar.pack(fill=tk.X, padx=10, pady=5)

        vc_frame = ttk.Frame(toolbar)
        vc_frame.pack(side=tk.LEFT)

        ttk.Label(vc_frame, text="vCenter:").pack(side=tk.LEFT)
        self.vc_combo = ttk.Combobox(vc_frame, width=20, state='readonly')
        self.vc_combo.pack(side=tk.LEFT, padx=5)
        self.vc_combo.bind('<<ComboboxSelected>>', lambda e: self._on_vc_selected())

        btn_frame = ttk.Frame(toolbar)
        btn_frame.pack(side=tk.LEFT, padx=10)

        EnhancedButton(btn_frame, "开始巡检", "🔍", command=self._start_inspect).pack(side=tk.LEFT, padx=2)
        EnhancedButton(btn_frame, "一键巡检", "🚀", command=self._start_all_inspect).pack(side=tk.LEFT, padx=2)
        EnhancedButton(btn_frame, "导出Excel", "📊", command=self._export_excel).pack(side=tk.LEFT, padx=2)
        EnhancedButton(btn_frame, "iSCSI", "💾", command=self._export_iscsi).pack(side=tk.LEFT, padx=2)
        EnhancedButton(btn_frame, "端口组", "🔀", command=self._export_portgroup).pack(side=tk.LEFT, padx=2)

        self.filterable_tree = FilterableTable(
            self.parent,
            columns=self.DISPLAY_COLUMNS,
            column_widths=self.COLUMN_WIDTHS,
            page_size=50,
            filter_columns=('vCenter', '集群')
        )
        self.filterable_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.filterable_tree.bind_context_menu(self._show_context_menu)

        self._load_vc_list()
        self._load_all_data()

        self.parent.bind('<Visibility>', lambda e: self._refresh_vc_list())

    def _show_context_menu(self, event):
        clicked_item = self.filterable_tree.tree.identify_row(event.y)
        if clicked_item:
            current_selection = self.filterable_tree.tree.selection()
            if clicked_item not in current_selection:
                self.filterable_tree.tree.selection_set(clicked_item)
        
        selected = self.filterable_tree.get_all_selected()
        if not selected:
            return

        count = len(selected)
        menu = tk.Menu(self.parent, tearoff=0)
        menu.add_command(label=f"iSCSI挂载 ({count}台)", command=lambda: self._iscsi_mount_batch(selected))
        menu.post(event.x_root, event.y_root)

    def _load_vc_list(self):
        vcenters = self.db.get_vcenters()
        self.vc_list = {vc[1]: (vc[2], vc[3]) for vc in vcenters}
        vc_options = ['全部'] + list(self.vc_list.keys())
        self.vc_combo['values'] = vc_options
        if vc_options:
            self.vc_combo.current(0)

    def _refresh_vc_list(self):
        vcenters = self.db.get_vcenters()
        self.vc_list = {vc[1]: (vc[2], vc[3]) for vc in vcenters}
        current = self.vc_combo.get()
        vc_options = ['全部'] + list(self.vc_list.keys())
        self.vc_combo['values'] = vc_options
        if current in vc_options:
            self.vc_combo.set(current)
        else:
            self.vc_combo.current(0)
            self._load_all_data()

    def _on_vc_selected(self):
        self._load_all_data()

    def _load_all_data(self):
        selected_vc = self.vc_combo.get()
        if selected_vc == '全部':
            data, _ = self.db.get_host_inspect(None, '', 1, 100000)
        else:
            data, _ = self.db.get_host_inspect(selected_vc, '', 1, 100000)

        self._host_info_map = {}
        filtered_data = []
        for row in data:
            new_row = tuple(row[i] for i in self.DB_COLUMN_INDICES)
            new_row = tuple('' if v is None else v for v in new_row)
            filtered_data.append(new_row)
            vc_ip = row[self.DB_VC_IP_INDEX] if self.DB_VC_IP_INDEX < len(row) else None
            host_name = row[self.DB_HOST_NAME_INDEX] if self.DB_HOST_NAME_INDEX < len(row) else None
            if vc_ip and host_name:
                self._host_info_map[new_row] = (vc_ip, host_name)

        self.all_data = filtered_data
        self.filterable_tree.set_data(filtered_data)

    def _iscsi_mount_batch(self, selected_items):
        if not selected_items:
            messagebox.showwarning("提示", "请先选择主机")
            return

        host_info_list = []
        for item in selected_items:
            host_info = self._host_info_map.get(item)
            if host_info:
                host_info_list.append(host_info)

        if not host_info_list:
            messagebox.showwarning("提示", "无法获取选中主机信息")
            return

        dialog = tk.Toplevel(self.parent)
        dialog.title(f"批量iSCSI挂载 ({len(host_info_list)}台)")
        dialog.geometry("500x220")
        dialog.transient(self.parent)
        dialog.grab_set()

        tk.Label(dialog, text=f"已选择 {len(host_info_list)} 台主机", font=FONTS['bold']).pack(pady=(10, 5))

        form_frame = tk.Frame(dialog)
        form_frame.pack(fill=tk.X, padx=20, pady=5)

        tk.Label(form_frame, text="iSCSI Target IP:").grid(row=0, column=0, sticky='w', pady=5)
        target_entry = tk.Entry(form_frame, width=30, font=FONTS['normal'])
        target_entry.grid(row=0, column=1, padx=5, pady=5)

        tk.Label(form_frame, text="iSCSI IQN:").grid(row=1, column=0, sticky='w', pady=5)
        iqn_entry = tk.Entry(form_frame, width=30, font=FONTS['normal'])
        iqn_entry.grid(row=1, column=1, padx=5, pady=5)

        def do_mount():
            target_ip = target_entry.get().strip()
            iqn = iqn_entry.get().strip()
            if not target_ip:
                messagebox.showwarning("提示", "请输入iSCSI Target IP")
                return
            dialog.destroy()
            progress = ProgressDialog(self.parent, "批量iSCSI挂载")
            progress.update_status("开始批量挂载...")

            def run_mount():
                from pyVmomi import vim
                from src.core.vcenter_connector import VCenterConnector
                import ssl
                from pyVim.connect import SmartConnect

                try:
                    context = ssl._create_unverified_context()
                    si = SmartConnect(host=host_info_list[0][0], user=self.vc_list.get(host_info_list[0][0], (None, None))[0],
                                      pwd=self.vc_list.get(host_info_list[0][0], (None, None))[1], sslContext=context)
                    content = si.RetrieveContent()

                    success_count = 0
                    fail_count = 0
                    total = len(host_info_list)

                    for i, (vc_ip, host_name) in enumerate(host_info_list):
                        progress.update_status(f"正在处理 {i+1}/{total}: {host_name}")
                        try:
                            host_obj = None
                            for dc in content.rootFolder.childEntity:
                                if hasattr(dc, 'hostFolder'):
                                    for host_cluster in dc.hostFolder.childEntity:
                                        if hasattr(host_cluster, 'host'):
                                            for h in host_cluster.host:
                                                if h.name == host_name:
                                                    host_obj = h
                                                    break

                            if not host_obj:
                                fail_count += 1
                                continue

                            hss = host_obj.configManager.storageSystem
                            hba = None
                            for hba_device in host_obj.config.storageDevice.hostBusAdapter:
                                if isinstance(hba_device, vim.host.InternetScsiHba):
                                    hba = hba_device.device
                                    break

                            if hba:
                                send_target = vim.host.InternetScsiHba.SendTarget(address=target_ip, port=3260)
                                hss.AddInternetScsiSendTargets(hba, [send_target])
                                success_count += 1
                            else:
                                fail_count += 1
                        except:
                            fail_count += 1

                    si.Disconnect()
                    progress.close()
                    result_msg = f"批量挂载完成\n成功: {success_count}台\n失败: {fail_count}台"
                    self.parent.after(0, lambda: messagebox.showinfo("完成", result_msg))
                except Exception as e:
                    progress.close()
                    self.parent.after(0, lambda: messagebox.showerror("错误", f"挂载失败: {str(e)}"))

            threading.Thread(target=run_mount, daemon=True).start()

        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="挂载", command=do_mount, font=FONTS['button'], bg=COLORS['primary'], fg='white').pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="取消", command=dialog.destroy, font=FONTS['button']).pack(side=tk.LEFT, padx=5)

    def _start_inspect(self):
        vc_ip = self.vc_combo.get()
        if not vc_ip or vc_ip == '全部':
            messagebox.showwarning("提示", "请选择具体的vCenter")
            return

        user, pwd = self.vc_list[vc_ip]
        progress = ProgressDialog(self.parent, "主机巡检中")

        def run_inspect():
            try:
                start_time = time.time()
                progress.update_status(f"正在连接 {vc_ip}...")

                connector = VCenterConnector(vc_ip, user, pwd)
                success, msg = connector.connect()

                if not success:
                    progress.close()
                    self.parent.after(0, lambda: messagebox.showerror("错误", f"连接失败: {msg}"))
                    return

                progress.update_status("正在采集主机数据...")

                collector = HostCollector(connector)
                hosts = collector.collect_all_hosts()

                progress.update_status("正在保存数据...")
                self.db.save_host_inspect(hosts)

                connector.disconnect()

                elapsed = time.time() - start_time
                progress.close()

                self.parent.after(0, lambda: messagebox.showinfo("完成", f"巡检完成，共采集 {len(hosts)} 台主机\n耗时: {elapsed:.1f}秒"))
                self.parent.after(0, lambda: self._load_all_data())

            except Exception as e:
                progress.close()
                self.parent.after(0, lambda: messagebox.showerror("错误", f"巡检失败: {str(e)}"))

        threading.Thread(target=run_inspect, daemon=True).start()

    def _start_all_inspect(self):
        vcenters = self.db.get_vcenters()
        if not vcenters:
            messagebox.showwarning("提示", "没有已添加的vCenter")
            return

        progress = ProgressDialog(self.parent, "一键巡检中")

        start_time = time.time()
        completed = [0]
        total_hosts = [0]
        results = []
        lock = threading.Lock()

        def inspect_single_vc(vc):
            vc_ip, user, pwd = vc[1], vc[2], vc[3]
            try:
                progress.update_status(f"正在连接 {vc_ip}...")

                connector = VCenterConnector(vc_ip, user, pwd)
                success, msg = connector.connect()

                if not success:
                    return {'vc_ip': vc_ip, 'success': False, 'error': msg, 'hosts': 0}

                progress.update_status(f"正在采集 {vc_ip} 主机数据...")
                collector = HostCollector(connector)
                hosts = collector.collect_all_hosts()
                self.db.save_host_inspect(hosts)
                connector.disconnect()

                with lock:
                    completed[0] += 1
                    progress.update_detail(f"已完成 {completed[0]}/{len(vcenters)} 个vCenter")

                return {'vc_ip': vc_ip, 'success': True, 'hosts': len(hosts), 'error': None}

            except Exception as e:
                with lock:
                    completed[0] += 1
                return {'vc_ip': vc_ip, 'success': False, 'error': str(e), 'hosts': 0}

        def run_inspect():
            from concurrent.futures import ThreadPoolExecutor, as_completed
            from src.core.concurrent_config import ConcurrentConfig

            max_workers = ConcurrentConfig.get_optimal_workers('vc_inspect')
            max_workers = min(max_workers, len(vcenters))

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(inspect_single_vc, vc): vc for vc in vcenters}

                for future in as_completed(futures):
                    result = future.result()
                    results.append(result)
                    total_hosts[0] += result['hosts']

            elapsed = int(time.time() - start_time)
            minutes = elapsed // 60
            seconds = elapsed % 60
            time_str = f"{minutes}分{seconds}秒" if minutes > 0 else f"{seconds}秒"

            failed = sum(1 for r in results if not r['success'])

            progress.close()

            msg = f"一键巡检完成\n总采集: {total_hosts[0]} 台主机\n耗时: {time_str}"
            if failed > 0:
                msg += f"\n失败: {failed} 个vCenter"

            self.parent.after(0, lambda: messagebox.showinfo("完成", msg))
            self.parent.after(0, lambda: self._on_vc_selected())

        threading.Thread(target=run_inspect, daemon=True).start()

    def _export_excel(self):
        from tkinter import filedialog

        file_path = filedialog.asksaveasfilename(
            parent=self.parent,
            title="保存Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx")]
        )

        if not file_path:
            return

        try:
            selected_vc = self.vc_combo.get()
            if selected_vc == '全部':
                data, _ = self.db.get_host_inspect(None, '', 1, 100000)
            else:
                data, _ = self.db.get_host_inspect(selected_vc, '', 1, 100000)

            if data:
                df = pd.DataFrame(data, columns=[
                    'ID', 'vCenter', '主机名', '集群', '状态', 'ESXi版本', '厂商', '型号',
                    '序列号', 'CPU型号', '主频', 'CPU数', '核心数', '内存(GB)', '运行天数',
                    'CPU使用率', '内存使用率', 'VMK适配器', '证书过期', '巡检时间'
                ])
                df.to_excel(file_path, index=False)
                messagebox.showinfo("提示", f"导出成功: {file_path}")
            else:
                messagebox.showwarning("提示", "没有数据")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败: {str(e)}")

    def _export_iscsi(self):
        from tkinter import filedialog
        from src.core.iscsi_exporter import ISCSIExporter

        vcenters = self.db.get_vcenters()
        if not vcenters:
            messagebox.showwarning("提示", "没有已添加的vCenter")
            return

        file_path = filedialog.asksaveasfilename(
            parent=self.parent,
            title="保存iSCSI信息",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx")],
            initialfile="esxi_iscsi_iqn.xlsx"
        )

        if not file_path:
            return

        progress = ProgressDialog(self.parent, "导出iSCSI信息")

        def run_export():
            try:
                start_time = time.time()
                exporter = ISCSIExporter()
                results = exporter.export_iscsi(
                    vcenters,
                    status_callback=lambda msg: progress.update_status(msg)
                )

                elapsed = time.time() - start_time

                if results:
                    exporter.save_to_excel(file_path)
                    progress.close()
                    self.parent.after(0, lambda: messagebox.showinfo("完成", f"导出成功，共 {len(results)} 条记录\n耗时: {elapsed:.1f}秒"))
                else:
                    progress.close()
                    self.parent.after(0, lambda: messagebox.showwarning("提示", "未获取到iSCSI信息"))

            except Exception as e:
                progress.close()
                self.parent.after(0, lambda: messagebox.showerror("错误", f"导出失败: {str(e)}"))

        threading.Thread(target=run_export, daemon=True).start()

    def _export_portgroup(self):
        from tkinter import filedialog
        import traceback
        from src.core.portgroup_exporter import PortGroupExporter

        vcenters = self.db.get_vcenters()
        if not vcenters:
            messagebox.showwarning("提示", "没有已添加的vCenter")
            return

        file_path = filedialog.asksaveasfilename(
            parent=self.parent,
            title="保存端口组信息",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx")],
            initialfile="portgroup_info.xlsx"
        )

        if not file_path:
            return

        progress = ProgressDialog(self.parent, "导出端口组信息")

        def run_export():
            try:
                exporter = PortGroupExporter()

                def update_status(msg):
                    progress.update_status(msg)

                progress.update_status(f"开始收集 {len(vcenters)} 个vCenter...")

                results, total_time = exporter.export_all_vcenters(vcenters, status_callback=update_status)

                progress.update_status(f"收集完成，共 {len(results)} 个端口组 (耗时: {total_time:.1f}s)")

                if results:
                    progress.update_status("正在写入Excel...")
                    exporter.save_to_excel(file_path, results)
                    progress.close()
                    self.parent.after(0, lambda: messagebox.showinfo("完成", f"导出成功，共 {len(results)} 条记录"))
                else:
                    progress.close()
                    self.parent.after(0, lambda: messagebox.showwarning("提示", "未获取到端口组信息"))

            except Exception as e:
                error_msg = f"导出失败: {str(e)}"
                print(traceback.format_exc())
                progress.close()
                self.parent.after(0, lambda: messagebox.showerror("错误", error_msg))

        threading.Thread(target=run_export, daemon=True).start()
