import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import pandas as pd
from src.db.database import Database
from src.core.vcenter_connector import VCenterConnector
from src.core.vm_collector import VMCollector
from src.ui.theme import COLORS, FONTS
from src.ui.enhanced_widgets import EnhancedButton, FilterableTable, ProgressDialog


class VMInspectPage:
    DISPLAY_COLUMNS = ('vCenter', '虚拟机名', '集群', '主机', '备注')
    COLUMN_WIDTHS = {
        'vCenter': 120, '虚拟机名': 200, '集群': 120,
        '主机': 150, '备注': 150
    }
    DB_COLUMN_INDICES = [1, 2, 3, 4, 10]
    DB_UUID_INDEX = 9

    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.db = Database()
        self.vc_list = {}
        self.all_data = []
        self._uuid_map = {}
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

        self.filterable_tree = FilterableTable(
            self.parent,
            columns=self.DISPLAY_COLUMNS,
            column_widths=self.COLUMN_WIDTHS,
            page_size=50
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
        menu.add_command(label=f"修改备注 ({count}台)", command=lambda: self._edit_annotation_batch(selected))
        menu.add_command(label=f"修改名称 ({count}台)", command=lambda: self._edit_vm_name_batch(selected))
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
            data, _ = self.db.get_vm_inspect(None, '', 1, 100000)
        else:
            data, _ = self.db.get_vm_inspect(selected_vc, '', 1, 100000)

        self._raw_data = data
        filtered_data = []
        for row in data:
            new_row = tuple(row[i] for i in self.DB_COLUMN_INDICES)
            new_row = tuple('' if v is None else v for v in new_row)
            filtered_data.append(new_row)

        self.all_data = filtered_data
        self.filterable_tree.set_data(filtered_data)

    def _find_raw_data_by_display(self, display_item):
        vc_name = display_item[1] if len(display_item) > 1 else ''
        for row in self._raw_data:
            db_name = str(row[2]) if len(row) > 2 and row[2] is not None else ''
            if db_name == vc_name:
                return row
        return None

    def _edit_annotation(self, item):
        raw_row = self._find_raw_data_by_display(item)
        if not raw_row:
            messagebox.showwarning("提示", "无法找到虚拟机数据")
            return

        uuid = raw_row[self.DB_UUID_INDEX] if self.DB_UUID_INDEX < len(raw_row) else None
        if not uuid:
            messagebox.showwarning("提示", "无法获取虚拟机UUID")
            return

        vc_ip = raw_row[1] if len(raw_row) > 1 else None
        if not vc_ip:
            messagebox.showwarning("提示", "无法获取vCenter信息")
            return

        user, pwd = self.vc_list.get(vc_ip, (None, None))
        if not user or not pwd:
            messagebox.showwarning("提示", "无法获取vCenter连接信息")
            return

        current_annotation = item[4] if len(item) > 4 else ''
        
        dialog = tk.Toplevel(self.parent)
        dialog.title("修改备注")
        dialog.geometry("450x180")
        dialog.transient(self.parent)
        dialog.grab_set()

        tk.Label(dialog, text=f"虚拟机: {item[1]}", font=FONTS['bold']).pack(pady=(10, 5))
        tk.Label(dialog, text="新备注:").pack(pady=(5, 3))
        entry = tk.Entry(dialog, width=50, font=FONTS['normal'])
        entry.insert(0, current_annotation)
        entry.pack(pady=3)

        def save():
            new_annotation = entry.get()
            dialog.destroy()
            progress = ProgressDialog(self.parent, "修改备注")
            progress.update_status(f"正在连接 {vc_ip}...")

            def run_update():
                try:
                    from src.core.vcenter_connector import VCenterConnector
                    connector = VCenterConnector(vc_ip, user, pwd)
                    success, msg = connector.connect()
                    if not success:
                        progress.close()
                        self.parent.after(0, lambda: messagebox.showerror("错误", f"连接失败: {msg}"))
                        return

                    progress.update_status("正在查找虚拟机...")
                    vm_obj = connector.find_vm_by_uuid(uuid)
                    if not vm_obj:
                        progress.close()
                        connector.disconnect()
                        self.parent.after(0, lambda: messagebox.showerror("错误", "未找到虚拟机"))
                        return

                    progress.update_status("正在修改备注...")
                    success, msg = connector.update_vm_annotation(vm_obj, new_annotation)
                    connector.disconnect()
                    progress.close()

                    if success:
                        self.parent.after(0, lambda: messagebox.showinfo("完成", "备注已更新"))
                        self.parent.after(0, lambda: self._load_all_data())
                    else:
                        self.parent.after(0, lambda: messagebox.showerror("错误", f"修改失败: {msg}"))
                except Exception as e:
                    progress.close()
                    self.parent.after(0, lambda: messagebox.showerror("错误", f"修改失败: {str(e)}"))

            threading.Thread(target=run_update, daemon=True).start()

        tk.Button(dialog, text="保存", command=save, font=FONTS['button'], bg=COLORS['primary'], fg='white').pack(pady=10)
        entry.focus()
        dialog.bind('<Return>', lambda e: save())
        dialog.bind('<Escape>', lambda e: dialog.destroy())

    def _edit_vm_name(self, item):
        raw_row = self._find_raw_data_by_display(item)
        if not raw_row:
            messagebox.showwarning("提示", "无法找到虚拟机数据")
            return

        uuid = raw_row[self.DB_UUID_INDEX] if self.DB_UUID_INDEX < len(raw_row) else None
        if not uuid:
            messagebox.showwarning("提示", "无法获取虚拟机UUID")
            return

        vc_ip = raw_row[1] if len(raw_row) > 1 else None
        if not vc_ip:
            messagebox.showwarning("提示", "无法获取vCenter信息")
            return

        user, pwd = self.vc_list.get(vc_ip, (None, None))
        if not user or not pwd:
            messagebox.showwarning("提示", "无法获取vCenter连接信息")
            return

        current_name = item[1] if len(item) > 1 else ''
        
        dialog = tk.Toplevel(self.parent)
        dialog.title("修改名称")
        dialog.geometry("450x180")
        dialog.transient(self.parent)
        dialog.grab_set()

        tk.Label(dialog, text=f"当前名称: {current_name}", font=FONTS['bold']).pack(pady=(10, 5))
        tk.Label(dialog, text="新名称:").pack(pady=(5, 3))
        entry = tk.Entry(dialog, width=50, font=FONTS['normal'])
        entry.insert(0, current_name)
        entry.pack(pady=3)

        def save():
            new_name = entry.get().strip()
            if not new_name:
                messagebox.showwarning("提示", "名称不能为空")
                return
            dialog.destroy()
            progress = ProgressDialog(self.parent, "修改名称")
            progress.update_status(f"正在连接 {vc_ip}...")

            def run_update():
                try:
                    from src.core.vcenter_connector import VCenterConnector
                    connector = VCenterConnector(vc_ip, user, pwd)
                    success, msg = connector.connect()
                    if not success:
                        progress.close()
                        self.parent.after(0, lambda: messagebox.showerror("错误", f"连接失败: {msg}"))
                        return

                    progress.update_status("正在查找虚拟机...")
                    vm_obj = connector.find_vm_by_uuid(uuid)
                    if not vm_obj:
                        progress.close()
                        connector.disconnect()
                        self.parent.after(0, lambda: messagebox.showerror("错误", "未找到虚拟机"))
                        return

                    progress.update_status("正在修改名称...")
                    success, msg = connector.rename_vm(vm_obj, new_name)
                    connector.disconnect()
                    progress.close()

                    if success:
                        self.parent.after(0, lambda: messagebox.showinfo("完成", "名称已更新"))
                        self.parent.after(0, lambda: self._load_all_data())
                    else:
                        self.parent.after(0, lambda: messagebox.showerror("错误", f"修改失败: {msg}"))
                except Exception as e:
                    progress.close()
                    self.parent.after(0, lambda: messagebox.showerror("错误", f"修改失败: {str(e)}"))

            threading.Thread(target=run_update, daemon=True).start()

        tk.Button(dialog, text="保存", command=save, font=FONTS['button'], bg=COLORS['primary'], fg='white').pack(pady=10)
        entry.focus()
        entry.select_range(0, tk.END)
        dialog.bind('<Return>', lambda e: save())
        dialog.bind('<Escape>', lambda e: dialog.destroy())

    def _edit_annotation_batch(self, selected_items):
        if not selected_items:
            messagebox.showwarning("提示", "请先选择虚拟机")
            return

        raw_rows = []
        for item in selected_items:
            raw_row = self._find_raw_data_by_display(item)
            if raw_row:
                raw_rows.append(raw_row)

        if not raw_rows:
            messagebox.showwarning("提示", "无法获取选中虚拟机数据")
            return

        vc_ip = raw_rows[0][1]
        user, pwd = self.vc_list.get(vc_ip, (None, None))
        if not user or not pwd:
            messagebox.showwarning("提示", "无法获取vCenter连接信息")
            return

        dialog = tk.Toplevel(self.parent)
        dialog.title(f"批量修改备注 ({len(raw_rows)}台)")
        dialog.geometry("500x200")
        dialog.transient(self.parent)
        dialog.grab_set()

        tk.Label(dialog, text=f"已选择 {len(raw_rows)} 台虚拟机", font=FONTS['bold']).pack(pady=(10, 5))
        vm_names = [str(r[2]) for r in raw_rows]
        names_text = "、".join(vm_names[:5])
        if len(vm_names) > 5:
            names_text += f" 等{len(vm_names)}台"
        tk.Label(dialog, text=names_text, fg=COLORS['text_secondary']).pack(pady=3)

        tk.Label(dialog, text="新备注:").pack(pady=(10, 3))
        entry = tk.Entry(dialog, width=50, font=FONTS['normal'])
        entry.pack(pady=3)

        def save():
            new_annotation = entry.get()
            dialog.destroy()
            progress = ProgressDialog(self.parent, "批量修改备注")
            progress.update_status(f"正在连接 {vc_ip}...")

            def run_update():
                try:
                    from src.core.vcenter_connector import VCenterConnector
                    connector = VCenterConnector(vc_ip, user, pwd)
                    success, msg = connector.connect()
                    if not success:
                        progress.close()
                        self.parent.after(0, lambda: messagebox.showerror("错误", f"连接失败: {msg}"))
                        return

                    success_count = 0
                    fail_count = 0
                    total = len(raw_rows)

                    for i, raw_row in enumerate(raw_rows):
                        uuid = raw_row[self.DB_UUID_INDEX] if self.DB_UUID_INDEX < len(raw_row) else None
                        vm_name = str(raw_row[2]) if len(raw_row) > 2 else f"VM{i+1}"
                        if not uuid:
                            fail_count += 1
                            continue

                        progress.update_status(f"正在修改 {i+1}/{total}: {vm_name}")
                        vm_obj = connector.find_vm_by_uuid(uuid)
                        if vm_obj:
                            ok, msg = connector.update_vm_annotation(vm_obj, new_annotation)
                            if ok:
                                success_count += 1
                            else:
                                fail_count += 1
                        else:
                            fail_count += 1

                    connector.disconnect()
                    progress.close()

                    result_msg = f"批量修改完成\n成功: {success_count}台\n失败: {fail_count}台"
                    self.parent.after(0, lambda: messagebox.showinfo("完成", result_msg))
                    self.parent.after(0, lambda: self._load_all_data())
                except Exception as e:
                    progress.close()
                    self.parent.after(0, lambda: messagebox.showerror("错误", f"修改失败: {str(e)}"))

            threading.Thread(target=run_update, daemon=True).start()

        tk.Button(dialog, text="保存", command=save, font=FONTS['button'], bg=COLORS['primary'], fg='white').pack(pady=10)
        entry.focus()
        dialog.bind('<Return>', lambda e: save())
        dialog.bind('<Escape>', lambda e: dialog.destroy())

    def _edit_vm_name_batch(self, selected_items):
        if not selected_items:
            messagebox.showwarning("提示", "请先选择虚拟机")
            return

        raw_rows = []
        for item in selected_items:
            raw_row = self._find_raw_data_by_display(item)
            if raw_row:
                raw_rows.append(raw_row)

        if not raw_rows:
            messagebox.showwarning("提示", "无法获取选中虚拟机数据")
            return

        vc_ip = raw_rows[0][1]
        user, pwd = self.vc_list.get(vc_ip, (None, None))
        if not user or not pwd:
            messagebox.showwarning("提示", "无法获取vCenter连接信息")
            return

        dialog = tk.Toplevel(self.parent)
        dialog.title(f"批量修改名称 ({len(raw_rows)}台)")
        dialog.geometry("550x250")
        dialog.transient(self.parent)
        dialog.grab_set()

        tk.Label(dialog, text=f"已选择 {len(raw_rows)} 台虚拟机", font=FONTS['bold']).pack(pady=(10, 5))

        rule_frame = tk.Frame(dialog)
        rule_frame.pack(fill=tk.X, padx=20, pady=5)

        tk.Label(rule_frame, text="命名规则:").pack(anchor='w')
        rule_var = tk.StringVar(value="prefix")
        tk.Radiobutton(rule_frame, text="前缀", variable=rule_var, value="prefix").pack(anchor='w')
        tk.Radiobutton(rule_frame, text="后缀", variable=rule_var, value="suffix").pack(anchor='w')
        tk.Radiobutton(rule_frame, text="替换", variable=rule_var, value="replace").pack(anchor='w')

        input_frame = tk.Frame(dialog)
        input_frame.pack(fill=tk.X, padx=20, pady=5)
        tk.Label(input_frame, text="内容:").pack(side=tk.LEFT)
        entry = tk.Entry(input_frame, width=40, font=FONTS['normal'])
        entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        def save():
            rule = rule_var.get()
            content = entry.get().strip()
            if not content:
                messagebox.showwarning("提示", "请输入内容")
                return
            dialog.destroy()
            progress = ProgressDialog(self.parent, "批量修改名称")
            progress.update_status(f"正在连接 {vc_ip}...")

            def run_update():
                try:
                    from src.core.vcenter_connector import VCenterConnector
                    connector = VCenterConnector(vc_ip, user, pwd)
                    success, msg = connector.connect()
                    if not success:
                        progress.close()
                        self.parent.after(0, lambda: messagebox.showerror("错误", f"连接失败: {msg}"))
                        return

                    success_count = 0
                    fail_count = 0
                    total = len(raw_rows)

                    for i, raw_row in enumerate(raw_rows):
                        uuid = raw_row[self.DB_UUID_INDEX] if self.DB_UUID_INDEX < len(raw_row) else None
                        old_name = str(raw_row[2]) if len(raw_row) > 2 else ""
                        if not uuid:
                            fail_count += 1
                            continue

                        if rule == "prefix":
                            new_name = f"{content}{old_name}"
                        elif rule == "suffix":
                            new_name = f"{old_name}{content}"
                        else:
                            new_name = content

                        progress.update_status(f"正在修改 {i+1}/{total}: {old_name}")
                        vm_obj = connector.find_vm_by_uuid(uuid)
                        if vm_obj:
                            ok, msg = connector.rename_vm(vm_obj, new_name)
                            if ok:
                                success_count += 1
                            else:
                                fail_count += 1
                        else:
                            fail_count += 1

                    connector.disconnect()
                    progress.close()

                    result_msg = f"批量修改完成\n成功: {success_count}台\n失败: {fail_count}台"
                    self.parent.after(0, lambda: messagebox.showinfo("完成", result_msg))
                    self.parent.after(0, lambda: self._load_all_data())
                except Exception as e:
                    progress.close()
                    self.parent.after(0, lambda: messagebox.showerror("错误", f"修改失败: {str(e)}"))

            threading.Thread(target=run_update, daemon=True).start()

        tk.Button(dialog, text="保存", command=save, font=FONTS['button'], bg=COLORS['primary'], fg='white').pack(pady=10)
        entry.focus()
        dialog.bind('<Return>', lambda e: save())
        dialog.bind('<Escape>', lambda e: dialog.destroy())

    def _start_inspect(self):
        vc_ip = self.vc_combo.get()
        if not vc_ip or vc_ip == '全部':
            messagebox.showwarning("提示", "请选择具体的vCenter")
            return

        user, pwd = self.vc_list[vc_ip]
        progress = ProgressDialog(self.parent, "虚拟机巡检中")

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

                progress.update_status("正在采集虚拟机数据...")

                collector = VMCollector(connector)
                vms = collector.collect_all_vms()

                progress.update_status("正在保存数据...")
                self.db.save_vm_inspect(vms)

                connector.disconnect()

                elapsed = time.time() - start_time
                progress.close()

                self.parent.after(0, lambda: messagebox.showinfo("完成", f"巡检完成，共采集 {len(vms)} 台虚拟机\n耗时: {elapsed:.1f}秒"))
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
        total_vms = [0]
        results = []
        lock = threading.Lock()

        def inspect_single_vc(vc):
            vc_ip, user, pwd = vc[1], vc[2], vc[3]
            try:
                progress.update_status(f"正在连接 {vc_ip}...")

                connector = VCenterConnector(vc_ip, user, pwd)
                success, msg = connector.connect()

                if not success:
                    return {'vc_ip': vc_ip, 'success': False, 'error': msg, 'vms': 0}

                progress.update_status(f"正在采集 {vc_ip} 虚拟机数据...")
                collector = VMCollector(connector)
                vms = collector.collect_all_vms()
                self.db.save_vm_inspect(vms)
                connector.disconnect()

                with lock:
                    completed[0] += 1
                    progress.update_detail(f"已完成 {completed[0]}/{len(vcenters)} 个vCenter")

                return {'vc_ip': vc_ip, 'success': True, 'vms': len(vms), 'error': None}

            except Exception as e:
                with lock:
                    completed[0] += 1
                return {'vc_ip': vc_ip, 'success': False, 'error': str(e), 'vms': 0}

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
                    total_vms[0] += result['vms']

            elapsed = int(time.time() - start_time)
            minutes = elapsed // 60
            seconds = elapsed % 60
            time_str = f"{minutes}分{seconds}秒" if minutes > 0 else f"{seconds}秒"

            failed = sum(1 for r in results if not r['success'])

            progress.close()

            msg = f"一键巡检完成\n总采集: {total_vms[0]} 台虚拟机\n耗时: {time_str}"
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
                data, _ = self.db.get_vm_inspect(None, '', 1, 100000)
            else:
                data, _ = self.db.get_vm_inspect(selected_vc, '', 1, 100000)

            if data:
                df = pd.DataFrame(data, columns=[
                    'ID', 'vCenter', '虚拟机名', '集群', '主机', '电源状态', 'IP地址',
                    '内存(GB)', 'CPU', 'UUID', '备注', 'Tools', '运行天数', '存储', '硬盘',
                    '已用空间(GB)', '文件夹', '巡检时间'
                ])
                df.to_excel(file_path, index=False)
                messagebox.showinfo("提示", f"导出成功: {file_path}")
            else:
                messagebox.showwarning("提示", "没有数据")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败: {str(e)}")
