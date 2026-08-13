import threading
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

from src.db.database import Database
from src.core.vcenter_vmca_cert_query import VCenterVmcaCertQuery
from src.ui.enhanced_widgets import EnhancedButton
from src.ui.theme import COLORS


class VCenterCertPage:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.db = Database()
        self.vcenters = []
        self._create_ui()
        self._refresh_vc_list()

    def _create_ui(self):
        toolbar = ttk.Frame(self.parent, style='Card.TFrame')
        toolbar.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(toolbar, text='vCenter:').pack(side=tk.LEFT, padx=(0, 6))
        self.vc_var = tk.StringVar()
        self.vc_combo = ttk.Combobox(toolbar, textvariable=self.vc_var, width=36, state='readonly')
        self.vc_combo.pack(side=tk.LEFT, padx=(0, 8))

        self.query_btn = EnhancedButton(toolbar, '查询证书', '🔎', command=self._start_query)
        self.query_btn.pack(side=tk.LEFT, padx=2)

        self.renew_btn = EnhancedButton(toolbar, '一键续订(VMCA)', '🔁', command=self._start_renew)
        self.renew_btn.pack(side=tk.LEFT, padx=2)

        self.refresh_btn = EnhancedButton(toolbar, '刷新vCenter列表', '🔄', command=self._refresh_vc_list)
        self.refresh_btn.pack(side=tk.LEFT, padx=2)

        self.status_var = tk.StringVar(value='请选择 vCenter 后执行查询')
        ttk.Label(toolbar, textvariable=self.status_var, foreground=COLORS['text_secondary']).pack(side=tk.RIGHT)

        progress_frame = ttk.Frame(self.parent)
        progress_frame.pack(fill=tk.X, padx=10, pady=(0, 4))
        self.progress_var = tk.DoubleVar(value=0)
        self.progress = ttk.Progressbar(
            progress_frame,
            orient='horizontal',
            mode='determinate',
            maximum=100,
            variable=self.progress_var
        )
        self.progress.pack(fill=tk.X, side=tk.LEFT, expand=True)
        self.progress_text_var = tk.StringVar(value='0%')
        ttk.Label(progress_frame, textvariable=self.progress_text_var, width=6).pack(side=tk.LEFT, padx=(8, 0))

        table_frame = ttk.Frame(self.parent)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        v_scroll = ttk.Scrollbar(table_frame, orient='vertical')
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        columns = ('vCenter', '证书类型', '创建时间', '过期时间', '离过期还剩余(天)')
        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings', yscrollcommand=v_scroll.set)
        v_scroll.configure(command=self.tree.yview)

        widths = {
            'vCenter': 180,
            '证书类型': 300,
            '创建时间': 180,
            '过期时间': 180,
            '离过期还剩余(天)': 140,
        }

        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=widths.get(col, 120), minwidth=80)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree.tag_configure('expired', foreground=COLORS['danger'])
        self.tree.tag_configure('warning', foreground=COLORS['warning'])

        log_frame = ttk.LabelFrame(self.parent, text='执行日志')
        log_frame.pack(fill=tk.BOTH, expand=False, padx=10, pady=(0, 8))
        self.log_text = ScrolledText(log_frame, height=9, wrap=tk.WORD, font=('Consolas', 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.log_text.configure(state=tk.DISABLED)

    def _refresh_vc_list(self):
        self.vcenters = self.db.get_vcenters()
        vc_options = ['全部vCenter'] + [vc[1] for vc in self.vcenters]
        self.vc_combo['values'] = vc_options
        if vc_options:
            self.vc_var.set(vc_options[0])

    def _get_selected_vcenters(self):
        selected = self.vc_var.get().strip()
        if not selected or selected == '全部vCenter':
            return self.vcenters
        return [vc for vc in self.vcenters if vc[1] == selected]

    def _start_query(self):
        selected_vcs = self._get_selected_vcenters()
        if not selected_vcs:
            messagebox.showwarning('提示', '请先配置vCenter')
            return

        missing_root = [vc[1] for vc in selected_vcs if not (vc[7] or '').strip()]
        if missing_root:
            messagebox.showwarning(
                '提示',
                '以下vCenter未配置root密码，无法执行VMCA证书查询：\n' + '\n'.join(missing_root)
            )

        runnable = [vc for vc in selected_vcs if (vc[7] or '').strip()]
        if not runnable:
            return

        for item in self.tree.get_children():
            self.tree.delete(item)

        self.query_btn.configure(state=tk.DISABLED)
        self.renew_btn.configure(state=tk.DISABLED)
        self.status_var.set('正在查询证书，请稍候...')
        self.progress_var.set(0)
        self.progress_text_var.set('0%')

        def worker():
            rows = []
            errors = []

            for vc in runnable:
                vc_ip = vc[1]
                root_pwd = vc[7] or ''
                query = VCenterVmcaCertQuery(vc_ip, root_pwd, port=22)
                ok, result = query.query_vmca_certificates()

                if not ok:
                    errors.append(f'{vc_ip}: {result}')
                    continue

                for cert in result:
                    rows.append((
                        vc_ip,
                        cert['cert_type'],
                        cert['created_time'],
                        cert['expiry_time'],
                        cert['days_left'],
                    ))

            self.parent.after(0, lambda: self._on_query_done(rows, errors))

        threading.Thread(target=worker, daemon=True).start()

    def _on_query_done(self, rows, errors):
        for row in rows:
            days_left = row[4]
            tags = ''
            if days_left < 0:
                tags = 'expired'
            elif days_left <= 30:
                tags = 'warning'
            self.tree.insert('', tk.END, values=row, tags=(tags, ) if tags else ())

        self.query_btn.configure(state=tk.NORMAL)
        self.renew_btn.configure(state=tk.NORMAL)
        self.progress_var.set(100)
        self.progress_text_var.set('100%')

        if errors:
            self.status_var.set(f'查询完成：成功 {len(rows)} 条，失败 {len(errors)} 个vCenter')
            messagebox.showwarning('部分失败', '\n'.join(errors[:10]))
        else:
            self.status_var.set(f'查询完成：共 {len(rows)} 条证书记录')

    def _append_log(self, text):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text + '\n')
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _start_renew(self):
        selected_vcs = self._get_selected_vcenters()
        if not selected_vcs:
            messagebox.showwarning('提示', '请先配置vCenter')
            return

        if not messagebox.askyesno(
            '确认',
            '续订将执行VMCA相关证书重签并重启vCenter相关服务，期间管理面可能短时中断。\n是否继续？'
        ):
            return

        missing_root = [vc[1] for vc in selected_vcs if not (vc[7] or '').strip()]
        if missing_root:
            messagebox.showwarning(
                '提示',
                '以下vCenter未配置root密码，无法执行VMCA证书续订：\n' + '\n'.join(missing_root)
            )

        missing_sso = [vc[1] for vc in selected_vcs if not (vc[2] or '').strip() or not (vc[3] or '').strip()]
        if missing_sso:
            messagebox.showwarning(
                '提示',
                '以下vCenter未配置管理账号或密码，无法执行VMCA证书续订：\n' + '\n'.join(missing_sso)
            )

        runnable = [
            vc for vc in selected_vcs
            if (vc[7] or '').strip() and (vc[2] or '').strip() and (vc[3] or '').strip()
        ]
        if not runnable:
            return

        self.query_btn.configure(state=tk.DISABLED)
        self.renew_btn.configure(state=tk.DISABLED)
        self.status_var.set('正在执行VMCA证书续订，请稍候...')
        self.progress_var.set(0)
        self.progress_text_var.set('0%')
        self._append_log('=' * 80)
        self._append_log('开始执行VMCA证书续订...')

        def worker():
            success_count = 0
            failed = []
            logs = []

            total_vc = len(runnable)
            stage_percent_map = {
                'connecting': 5,
                'preparing': 12,
                'uploading': 15,
                'bundle_ready': 20,
                'running': 50,
                'cert_done': 75,
                'restarting': 85,
                'done': 100,
            }

            def emit_progress(vc_index, vc_ip, stage, message, percent=None):
                def _ui():
                    self._append_log(f'[{vc_ip}] {message}')
                    self.status_var.set(f'[{vc_ip}] {message}')
                    base = (vc_index / total_vc) * 100.0
                    local_percent = percent if percent is not None else stage_percent_map.get(stage, 0)
                    overall = min(100.0, base + (local_percent / total_vc))
                    self.progress_var.set(overall)
                    self.progress_text_var.set(f'{int(overall)}%')
                    if stage == 'cert_done':
                        messagebox.showinfo('进度提示', f'{vc_ip}\n证书续订已完成，下一步开始重启所有服务。')
                    elif stage == 'restarting':
                        messagebox.showinfo('进度提示', f'{vc_ip}\n正在重启所有服务，请耐心等待。')
                self.parent.after(0, _ui)

            for idx, vc in enumerate(runnable):
                vc_ip = vc[1]
                vc_user = vc[2]
                vc_pwd = vc[3]
                root_pwd = vc[7] or ''

                logs.append(f'[{vc_ip}] 开始续订...')
                manager = VCenterVmcaCertQuery(vc_ip, root_pwd, port=22)
                ok, result = manager.renew_vmca_certificates(
                    vc_user,
                    vc_pwd,
                    progress_cb=lambda stage, message, percent=None, _idx=idx, _vc_ip=vc_ip: emit_progress(
                        _idx, _vc_ip, stage, message, percent
                    ),
                )
                if ok:
                    success_count += 1
                    logs.append(f'[{vc_ip}] 续订完成')
                    if result:
                        logs.append(f'[{vc_ip}] 输出摘要:\n{result[-2000:]}')
                else:
                    failed.append((vc_ip, result))
                    logs.append(f'[{vc_ip}] 续订失败: {result}')
                logs.append('-' * 80)

            self.parent.after(0, lambda: self._on_renew_done(success_count, failed, logs))

        threading.Thread(target=worker, daemon=True).start()

    def _on_renew_done(self, success_count, failed, logs):
        for line in logs:
            self._append_log(line)

        self.query_btn.configure(state=tk.NORMAL)
        self.renew_btn.configure(state=tk.NORMAL)
        self.progress_var.set(100)
        self.progress_text_var.set('100%')

        total = success_count + len(failed)
        self.status_var.set(f'续订完成：成功 {success_count}/{total}，失败 {len(failed)}')

        if failed:
            brief = '\n'.join([f'{ip}: {msg}' for ip, msg in failed][:5])
            messagebox.showwarning('续订部分失败', brief)
        else:
            messagebox.showinfo('提示', 'VMCA证书续订执行完成')
