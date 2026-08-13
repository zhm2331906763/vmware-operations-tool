import threading
import tkinter as tk
from tkinter import ttk
from .theme import COLORS, FONTS


class ColumnFilterPanel(tk.Toplevel):
    def __init__(self, parent, column_name, unique_values, current_filter, callback, x, y, width):
        super().__init__(parent)
        self.column_name = column_name
        self.unique_values = sorted(set(v for v in unique_values if v))
        self.current_filter = set(current_filter) if current_filter else set()
        self.callback = callback
        self.width = int(max(width, 250))

        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.geometry(f"{self.width}x320+{int(x)}+{int(y)}")
        self.resizable(False, False)

        container = tk.Frame(self, bg=COLORS['bg_card'], bd=1, relief='solid')
        container.pack(fill=tk.BOTH, expand=True)

        title_frame = tk.Frame(container, bg=COLORS['primary'])
        title_frame.pack(fill=tk.X)
        tk.Label(title_frame, text=f"  筛选 - {column_name}", bg=COLORS['primary'],
                 fg='white', font=FONTS['bold']).pack(side=tk.LEFT, fill=tk.X, expand=True, anchor='w')
        tk.Button(title_frame, text="✕", bg=COLORS['primary'], fg='white',
                  bd=0, font=('Arial', 9, 'bold'), command=self.destroy).pack(side=tk.RIGHT, padx=5)

        search_frame = tk.Frame(container, bg=COLORS['bg_card'])
        search_frame.pack(fill=tk.X, padx=8, pady=(8, 5))

        tk.Label(search_frame, text="🔍", bg=COLORS['bg_card'], font=FONTS['normal']).pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search_frame, textvariable=self.search_var, font=FONTS['normal'])
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.search_entry.bind('<KeyRelease>', lambda e: self._filter_list())
        self.search_entry.focus()

        list_frame = tk.Frame(container, bg=COLORS['bg_card'])
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=5)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.listbox = tk.Listbox(list_frame, selectmode='extended', height=8,
                                  font=FONTS['normal'], yscrollcommand=scrollbar.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.bind('<Double-Button-1>', lambda e: self._on_ok())

        btn_frame = tk.Frame(container, bg=COLORS['bg_card'])
        btn_frame.pack(fill=tk.X, padx=8, pady=3)

        tk.Button(btn_frame, text="全选", command=self._select_all, font=FONTS['small']).pack(side=tk.LEFT, padx=2)
        tk.Button(btn_frame, text="反选", command=self._reverse_select, font=FONTS['small']).pack(side=tk.LEFT, padx=2)

        self.status_label = tk.Label(btn_frame, text="", font=FONTS['small'], fg=COLORS['text_secondary'])
        self.status_label.pack(side=tk.RIGHT)

        confirm_frame = tk.Frame(container, bg=COLORS['bg_card'])
        confirm_frame.pack(fill=tk.X, padx=8, pady=(3, 8))

        tk.Button(confirm_frame, text="取消", command=self.destroy, font=FONTS['button']).pack(side=tk.RIGHT, padx=2)
        tk.Button(confirm_frame, text="确定", command=self._on_ok, font=FONTS['button']).pack(side=tk.RIGHT, padx=2)

        self._populate_list(self.unique_values)
        self._update_status()

        self.bind('<Escape>', lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _populate_list(self, values):
        self.listbox.delete(0, tk.END)
        for val in values:
            self.listbox.insert(tk.END, str(val))
            idx = self.listbox.size() - 1
            if str(val) in self.current_filter:
                self.listbox.selection_set(idx)

    def _filter_list(self):
        search_text = self.search_var.get().strip().lower()
        if not search_text:
            self._populate_list(self.unique_values)
        else:
            filtered = [v for v in self.unique_values if search_text in str(v).lower()]
            self._populate_list(filtered)
        self._update_status()

    def _select_all(self):
        self.listbox.selection_set(0, tk.END)
        self._update_status()

    def _reverse_select(self):
        for idx in range(self.listbox.size()):
            if self.listbox.selection_includes(idx):
                self.listbox.selection_clear(idx)
            else:
                self.listbox.select_set(idx)
        self._update_status()

    def _update_status(self):
        selected = len(self.listbox.curselection())
        total = self.listbox.size()
        self.status_label.config(text=f"已选: {selected}/{total}")

    def _on_ok(self):
        selected = [self.listbox.get(idx) for idx in self.listbox.curselection()]
        self.callback(selected)
        self.destroy()


class FilterableTable(ttk.Frame):
    def __init__(
        self,
        parent,
        columns,
        column_widths=None,
        page_size=50,
        filter_columns=None,
        row_style_callback=None,
    ):
        super().__init__(parent)
        self.columns = list(columns)
        self.column_widths = column_widths or {}
        self.page_size = page_size
        self.filter_columns = set(filter_columns) if filter_columns else set(columns)
        self.row_style_callback = row_style_callback
        self.all_data = []
        self.filtered_data = []
        self.current_page = 1
        self.total_pages = 1
        self.total_count = 0
        self.filters = {}
        self._col_indices = {}
        self._filter_buttons = {}
        self._setup_ui()

    def _setup_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=tk.X, padx=5, pady=5)

        search_frame = ttk.Frame(toolbar)
        search_frame.pack(side=tk.LEFT)

        ttk.Label(search_frame, text="🔍").pack(side=tk.LEFT)
        self.search_entry = ttk.Entry(search_frame, width=20)
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_entry.bind('<KeyRelease>', lambda e: self._on_search())
        ttk.Button(search_frame, text="搜索", command=self._on_search).pack(side=tk.LEFT, padx=2)
        ttk.Button(search_frame, text="重置", command=self._on_reset).pack(side=tk.LEFT, padx=2)

        filter_frame = ttk.Frame(toolbar)
        filter_frame.pack(side=tk.LEFT, padx=20)

        ttk.Label(filter_frame, text="筛选:").pack(side=tk.LEFT, padx=(0, 5))

        for col in self.columns:
            if col in self.filter_columns:
                btn_text = f"{col} ▼"
                if col in self.filters and self.filters[col]:
                    btn_text = f"{col} ✓({len(self.filters[col])})"
                btn = ttk.Button(filter_frame, text=btn_text,
                                 command=lambda c=col: self._show_filter_popup(c))
                btn.pack(side=tk.LEFT, padx=2)
                self._filter_buttons[col] = btn

        table_frame = ttk.Frame(self, style='Card.TFrame')
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5)

        col_widths = [self.column_widths.get(col, 100) for col in self.columns]

        vsb = ttk.Scrollbar(table_frame, orient='vertical')
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        hsb = ttk.Scrollbar(table_frame, orient='horizontal')
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

        self.tree = ttk.Treeview(
            table_frame,
            columns=self.columns,
            show='tree headings',
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
            selectmode='extended',
            height=18
        )
        vsb.configure(command=self.tree.yview)
        hsb.configure(command=self.tree.xview)

        for i, (col, width) in enumerate(zip(self.columns, col_widths)):
            self._col_indices[col] = i
            self.tree.heading(col, text=col, anchor='center')
            self.tree.column(col, width=width, minwidth=50, anchor='center')

        self.tree.column('#0', width=0, stretch=False)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        style = ttk.Style()
        style.configure('Treeview', rowheight=28, font=FONTS['normal'])
        style.configure('Treeview.Heading', font=FONTS['bold'], background=COLORS['bg_toolbar'],
                        foreground=COLORS['text_primary'], anchor='center')
        style.map('Treeview', background=[('selected', COLORS['row_selected'])])
        self.tree.tag_configure('nsx_managed', background='#E2F0D9')

        page_frame = ttk.Frame(self)
        page_frame.pack(fill=tk.X, padx=5, pady=5)

        self.page_label = ttk.Label(page_frame, text="")
        self.page_label.pack(side=tk.LEFT)

        self.status_label = ttk.Label(page_frame, text="", foreground=COLORS['text_secondary'])
        self.status_label.pack(side=tk.LEFT, padx=20)

        ttk.Button(page_frame, text="首页", command=self._go_first).pack(side=tk.RIGHT)
        ttk.Button(page_frame, text="上一页", command=self._go_prev).pack(side=tk.RIGHT)
        ttk.Button(page_frame, text="下一页", command=self._go_next).pack(side=tk.RIGHT)
        ttk.Button(page_frame, text="末页", command=self._go_last).pack(side=tk.RIGHT)

    def _show_filter_popup(self, column):
        col_idx = self._col_indices.get(column, 0)
        
        unique_values = []
        for row in self.all_data:
            if col_idx < len(row) and row[col_idx] is not None:
                unique_values.append(str(row[col_idx]))

        current_filter = list(self.filters.get(column, []))

        btn = self._filter_buttons.get(column)
        if btn:
            x = btn.winfo_rootx()
            y = btn.winfo_rooty() + btn.winfo_height() + 2
        else:
            x = self.winfo_pointerx()
            y = self.winfo_pointery()

        col_width = self.column_widths.get(column, 250)

        popup = ColumnFilterPanel(
            self.tree, column, unique_values, current_filter,
            lambda selected: self._apply_filter(column, selected, col_idx),
            x, y, max(col_width, 250)
        )

    def _apply_filter(self, column, selected, col_idx):
        if not selected:
            self.filters.pop(column, None)
        else:
            all_values = set()
            for row in self.all_data:
                if col_idx < len(row) and row[col_idx]:
                    all_values.add(str(row[col_idx]))
            if len(selected) == len(all_values):
                self.filters.pop(column, None)
            else:
                self.filters[column] = set(selected)

        self._update_filter_buttons()
        self._apply_all_filters()

    def _update_filter_buttons(self):
        for col, btn in self._filter_buttons.items():
            if col in self.filters and self.filters[col]:
                count = len(self.filters[col])
                btn.config(text=f"{col} ✓({count})")
            else:
                btn.config(text=f"{col} ▼")

    def _apply_all_filters(self):
        self.filtered_data = list(self.all_data)

        for col_name, selected_values in self.filters.items():
            if not selected_values:
                continue
            col_idx = self._col_indices.get(col_name)
            if col_idx is None:
                continue
            self.filtered_data = [
                row for row in self.filtered_data
                if col_idx < len(row) and str(row[col_idx]) in selected_values
            ]

        search_text = self.search_entry.get().strip().lower()
        if search_text:
            self.filtered_data = [
                row for row in self.filtered_data
                if any(search_text in str(cell).lower() for cell in row if cell)
            ]

        self.total_count = len(self.filtered_data)
        self.total_pages = max(1, (self.total_count + self.page_size - 1) // self.page_size)
        self.current_page = 1
        self._refresh_table()

    def _on_search(self):
        self._apply_all_filters()

    def _on_reset(self):
        self.search_entry.delete(0, tk.END)
        self.filters = {}
        self._update_filter_buttons()
        self.filtered_data = list(self.all_data)
        self.total_count = len(self.all_data)
        self.total_pages = max(1, (self.total_count + self.page_size - 1) // self.page_size)
        self.current_page = 1
        self._refresh_table()

    def _go_first(self):
        self.current_page = 1
        self._refresh_table()

    def _go_prev(self):
        if self.current_page > 1:
            self.current_page -= 1
            self._refresh_table()

    def _go_next(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self._refresh_table()

    def _go_last(self):
        self.current_page = self.total_pages
        self._refresh_table()

    def _refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        start_idx = (self.current_page - 1) * self.page_size
        end_idx = start_idx + self.page_size
        page_data = self.filtered_data[start_idx:end_idx]

        for row in page_data:
            display_row = []
            row_tags = ()
            if self.row_style_callback:
                try:
                    row_tags = self.row_style_callback(row) or ()
                except Exception:
                    row_tags = ()
            for i, val in enumerate(row):
                if i < len(self.columns):
                    if val is None:
                        display_row.append('')
                    elif isinstance(val, float) and self.columns[i] in ('CPU使用率', '内存使用率'):
                        display_row.append(f'{val}%')
                    else:
                        display_row.append(str(val))
            self.tree.insert('', tk.END, values=display_row, tags=row_tags)

        self.page_label.config(text=f"第 {self.current_page}/{self.total_pages} 页，共 {self.total_count} 条")
        self.status_label.config(text=f"显示 {len(page_data)} 条" if page_data else "无数据")

    def set_data(self, data, preserve_view=False):
        self.all_data = list(data) if data else []

        if preserve_view:
            current_search = self.search_entry.get().strip()
            current_filters = {k: set(v) for k, v in self.filters.items()}
            current_page = self.current_page

            self.filtered_data = list(self.all_data)
            self.total_count = len(self.all_data)
            self.total_pages = max(1, (self.total_count + self.page_size - 1) // self.page_size)
            self.filters = current_filters
            self._update_filter_buttons()
            self._apply_all_filters()

            if current_search:
                self.search_entry.delete(0, tk.END)
                self.search_entry.insert(0, current_search)
            self.current_page = min(max(1, current_page), self.total_pages)
            self._refresh_table()
            return

        self.filtered_data = list(self.all_data)
        self.total_count = len(self.all_data)
        self.total_pages = max(1, (self.total_count + self.page_size - 1) // self.page_size)
        self.current_page = 1
        self._on_reset()

    def get_selected(self):
        selection = self.tree.selection()
        if selection:
            item = self.tree.item(selection[0])
            return item['values']
        return None

    def get_all_selected(self):
        selection = self.tree.selection()
        results = []
        for item_id in selection:
            item = self.tree.item(item_id)
            results.append(item['values'])
        return results

    def bind_context_menu(self, callback):
        self.tree.bind('<Button-3>', lambda e: callback(e))

    def get_item_at_point(self, event):
        item_id = self.tree.identify_row(event.y)
        if item_id:
            item = self.tree.item(item_id)
            return item['values']
        return None


class EnhancedButton(ttk.Button):
    def __init__(self, parent, text, emoji=None, command=None, **kwargs):
        display_text = f"{emoji} {text}" if emoji else text
        super().__init__(parent, text=display_text, command=command, **kwargs)
        self.bind('<Enter>', lambda e: self.configure(cursor='hand2'))
        self.bind('<Leave>', lambda e: None)


class ProgressDialog(tk.Toplevel):
    def __init__(self, parent, title="处理中", determinate=False, maximum=100):
        super().__init__(parent)
        self.title(title)
        self.geometry("400x150")
        self.transient(parent)
        self.grab_set()
        self.configure(bg=COLORS['bg_card'])
        self._determinate = determinate
        self._maximum = max(1, int(maximum or 100))

        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.title_label = ttk.Label(main_frame, text="请稍候，正在处理...", font=FONTS['title'])
        self.title_label.pack(pady=(0, 15))

        mode = 'determinate' if determinate else 'indeterminate'
        self.progress = ttk.Progressbar(main_frame, mode=mode, length=350, maximum=self._maximum)
        if determinate:
            self.progress['value'] = 0
        self.progress.pack(pady=10)
        if not determinate:
            self.progress.start(10)

        self.status_label = ttk.Label(main_frame, text="")
        self.status_label.pack(pady=10)

    def update_status(self, message):
        self._run_ui(lambda: self._set_status(message))

    def set_determinate(self, maximum, value=0, detail=None):
        def _apply():
            self._determinate = True
            self._maximum = max(1, int(maximum or 1))
            self.progress.stop()
            self.progress.config(mode='determinate', maximum=self._maximum)
            self.progress['value'] = max(0, min(int(value), self._maximum))
            if detail is not None:
                self._set_status(detail)
        self._run_ui(_apply)

    def update_progress(self, current, total=None, message=None):
        def _apply():
            if total is not None:
                self._maximum = max(1, int(total or 1))
                self.progress.config(maximum=self._maximum)
            if self.progress.cget('mode') != 'determinate':
                self.progress.stop()
                self.progress.config(mode='determinate')
            self.progress['value'] = max(0, min(int(current), int(self._maximum)))
            if message is not None:
                self._set_status(message)
        self._run_ui(_apply)

    def update_detail(self, message):
        self._run_ui(lambda: self._set_status(message))

    def _set_status(self, message):
        self.status_label.config(text=message)
        self.update_idletasks()

    def _run_ui(self, callback):
        if threading.current_thread() is threading.main_thread():
            callback()
            return
        try:
            self.after(0, callback)
        except Exception:
            pass

    def close(self):
        def _close():
            try:
                self.progress.stop()
            except Exception:
                pass
            try:
                self.destroy()
            except Exception:
                pass
        self._run_ui(_close)


class EnhancedStatusBar(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        self.icon_label = ttk.Label(self, text="✅", font=('Arial', 10))
        self.icon_label.pack(side=tk.LEFT, padx=(5, 2))
        self.text_label = ttk.Label(self, text="就绪", font=FONTS['small'])
        self.text_label.pack(side=tk.LEFT)

    def set_status(self, icon, text):
        self.icon_label.config(text=icon)
        self.text_label.config(text=text)

    def set_ready(self):
        self.set_status("✅", "就绪")

    def set_loading(self, message=""):
        self.set_status("⏳", message or "处理中...")

    def set_success(self, message=""):
        self.set_status("✅", message or "完成")

    def set_error(self, message=""):
        self.set_status("❌", message or "错误")

    def set_warning(self, message=""):
        self.set_status("⚠️", message or "警告")


SimpleFilterTable = FilterableTable
FilterableTreeview = FilterableTable
