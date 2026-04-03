import tkinter as tk
from tkinter import ttk
import sqlite3


class FilterableTable(ttk.Frame):
    """带筛选功能的表格组件"""
    
    def __init__(self, parent, columns, column_widths=None, page_size=50):
        super().__init__(parent)
        self.columns = columns
        self.column_widths = column_widths or {}
        self.page_size = page_size
        self.data = []
        self.filtered_data = []
        self.current_page = 1
        self.total_pages = 1
        self.total_count = 0
        self.filters = {}
        self.on_page_change = None
        self.on_select = None
        
        self._create_ui()
    
    def _create_ui(self):
        # 搜索框
        search_frame = ttk.Frame(self)
        search_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(search_frame, text="搜索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=5)
        self.search_entry.bind('<Return>', lambda e: self._on_search())
        
        ttk.Button(search_frame, text="搜索", command=self._on_search).pack(side=tk.LEFT)
        ttk.Button(search_frame, text="重置", command=self._on_reset).pack(side=tk.LEFT, padx=5)
        
        # 表头筛选区域
        self.header_frame = ttk.Frame(self)
        self.header_frame.pack(fill=tk.X, padx=5)
        
        self.filter_combos = {}
        
        # 表格区域 - 使用Canvas实现横向滚动
        table_container = ttk.Frame(self)
        table_container.pack(fill=tk.BOTH, expand=True, padx=5)
        
        # 横向滚动条
        h_scroll = ttk.Scrollbar(table_container, orient='horizontal')
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        
        # 纵向滚动条
        v_scroll = ttk.Scrollbar(table_container, orient='vertical')
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 画布
        self.canvas = tk.Canvas(table_container, borderwidth=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)
        h_scroll.configure(command=self.canvas.xview)
        v_scroll.configure(command=self.canvas.yview)
        
        # 表格框架
        self.tree_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window(0, 0, window=self.tree_frame, anchor='nw')
        
        # 表格
        self.tree = ttk.Treeview(self.tree_frame, columns=self.columns, show='headings', 
                                 selectmode='browse', height=15)
        self.tree.pack(side=tk.LEFT)
        
        # 设置列
        for col in self.columns:
            width = self.column_widths.get(col, 100)
            self.tree.heading(col, text=col, command=lambda c=col: self._sort_by_column(c))
            self.tree.column(col, width=width, minwidth=50)
        
        # 绑定选择事件
        self.tree.bind('<<TreeviewSelect>>', self._on_select)
        
        # 调整canvas大小
        self.tree_frame.bind('<Configure>', self._on_frame_configure)
        
        # 分页控件
        page_frame = ttk.Frame(self)
        page_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.page_label = ttk.Label(page_frame, text="")
        self.page_label.pack(side=tk.LEFT)
        
        ttk.Button(page_frame, text="首页", command=self._go_first).pack(side=tk.RIGHT)
        ttk.Button(page_frame, text="上一页", command=self._go_prev).pack(side=tk.RIGHT)
        ttk.Button(page_frame, text="下一页", command=self._go_next).pack(side=tk.RIGHT)
        ttk.Button(page_frame, text="末页", command=self._go_last).pack(side=tk.RIGHT)
        
        self.page_entry = ttk.Entry(page_frame, width=5)
        self.page_entry.pack(side=tk.RIGHT, padx=5)
        self.page_entry.bind('<Return>', lambda e: self._go_page())
        ttk.Label(page_frame, text="跳转:").pack(side=tk.RIGHT)
    
    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
    
    def _create_filters(self):
        """创建列筛选下拉框"""
        for widget in self.header_frame.winfo_children():
            widget.destroy()
        
        self.filter_combos = {}
        
        for col in self.columns:
            frame = ttk.Frame(self.header_frame)
            frame.pack(side=tk.LEFT, padx=2)
            
            combo = ttk.Combobox(frame, values=['全部'], width=12, state='readonly')
            combo.pack()
            combo.set('全部')
            combo.bind('<<ComboboxSelected>>', lambda e, c=col: self._on_filter_change(c))
            
            self.filter_combos[col] = combo
            ttk.Label(frame, text=col, font=('Arial', 8)).pack()
    
    def _on_filter_change(self, column):
        """筛选变更"""
        combo = self.filter_combos[column]
        value = combo.get()
        
        if value == '全部':
            self.filters.pop(column, None)
        else:
            self.filters[column] = value
        
        self.current_page = 1
        self._apply_filters()
    
    def _apply_filters(self):
        """应用筛选"""
        if not self.data:
            self.filtered_data = []
        else:
            self.filtered_data = self.data.copy()
            
            for col, value in self.filters.items():
                if value and value != '全部':
                    col_idx = self.columns.index(col) if col in self.columns else -1
                    if col_idx >= 0:
                        self.filtered_data = [row for row in self.filtered_data 
                                              if col_idx < len(row) and str(row[col_idx]) == value]
        
        self.total_count = len(self.filtered_data)
        self.total_pages = max(1, (self.total_count + self.page_size - 1) // self.page_size)
        self._refresh_table()
    
    def set_data(self, data, total, page=1):
        """设置数据"""
        self.data = data
        self.total_count = total
        self.current_page = page
        self.total_pages = max(1, (total + self.page_size - 1) // self.page_size)
        
        # 更新筛选下拉框
        self._update_filter_values()
        
        self.filtered_data = data
        self._refresh_table()
    
    def _update_filter_values(self):
        """更新筛选下拉框的值"""
        if not self.data:
            return
        
        for col in self.columns:
            col_idx = self.columns.index(col) if col in self.columns else -1
            if col_idx >= 0:
                values = set()
                for row in self.data:
                    if col_idx < len(row) and row[col_idx]:
                        values.add(str(row[col_idx]))
                values = sorted(['全部'] + list(values))
                if col in self.filter_combos:
                    self.filter_combos[col]['values'] = values
    
    def _refresh_table(self):
        # 清空表格
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # 插入数据
        for row in self.filtered_data:
            self.tree.insert('', tk.END, values=row)
        
        # 更新分页信息
        self.page_label.config(
            text=f"共 {self.total_count} 条, 第 {self.current_page}/{self.total_pages} 页"
        )
    
    def _on_search(self):
        if self.on_page_change:
            self.on_page_change(1, 1, search=self.search_var.get())
    
    def _on_reset(self):
        self.search_var.set('')
        for combo in self.filter_combos.values():
            combo.set('全部')
        self.filters = {}
        if self.on_page_change:
            self.on_page_change(1, 1)
    
    def _go_first(self):
        self.current_page = 1
        if self.on_page_change:
            self.on_page_change(1, self.total_pages)
    
    def _go_prev(self):
        if self.current_page > 1:
            self.current_page -= 1
            if self.on_page_change:
                self.on_page_change(self.current_page, self.total_pages)
    
    def _go_next(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            if self.on_page_change:
                self.on_page_change(self.current_page, self.total_pages)
    
    def _go_last(self):
        self.current_page = self.total_pages
        if self.on_page_change:
            self.on_page_change(self.total_pages, self.total_pages)
    
    def _go_page(self):
        try:
            page = int(self.page_entry.get())
            if 1 <= page <= self.total_pages:
                self.current_page = page
                if self.on_page_change:
                    self.on_page_change(page, self.total_pages)
        except:
            pass
    
    def _sort_by_column(self, column):
        """排序"""
        # 简化实现，实际可以通过数据库排序
        pass
    
    def _on_select(self, event):
        if self.on_select:
            selection = self.tree.selection()
            if selection:
                item = self.tree.item(selection[0])
                self.on_select(item['values'])
    
    def get_selected(self):
        """获取选中行"""
        selection = self.tree.selection()
        if selection:
            item = self.tree.item(selection[0])
            return item['values']
        return None


class ProgressDialog:
    """进度对话框"""
    
    def __init__(self, parent, title="处理中"):
        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.geometry("400x150")
        self.window.transient(parent)
        self.window.grab_set()
        
        ttk.Label(self.window, text="请稍候，正在处理...", font=('Arial', 12)).pack(pady=20)
        
        self.progress = ttk.Progressbar(self.window, mode='indeterminate', length=350)
        self.progress.pack(pady=10)
        self.progress.start()
        
        self.status_label = ttk.Label(self.window, text="")
        self.status_label.pack(pady=10)
    
    def update_status(self, message):
        self.status_label.config(text=message)
        self.window.update()
    
    def close(self):
        self.progress.stop()
        self.window.destroy()


class ConfirmDialog:
    """确认对话框"""
    
    @staticmethod
    def ask(title, message):
        from tkinter import messagebox
        return messagebox.askyesno(title, message)
    
    @staticmethod
    def info(title, message):
        from tkinter import messagebox
        messagebox.showinfo(title, message)
    
    @staticmethod
    def error(title, message):
        from tkinter import messagebox
        messagebox.showerror(title, message)
    
    @staticmethod
    def warning(title, message):
        from tkinter import messagebox
        messagebox.showwarning(title, message)


class FileSelector:
    """文件选择器"""
    
    @staticmethod
    def open_file(parent, title="选择文件", file_types=None):
        from tkinter import filedialog
        if file_types is None:
            file_types = [("Excel文件", "*.xlsx"), ("所有文件", "*.*")]
        return filedialog.askopenfilename(parent=parent, title=title, filetypes=file_types)
    
    @staticmethod
    def save_file(parent, title="保存文件", default_ext=".xlsx", file_types=None):
        from tkinter import filedialog
        if file_types is None:
            file_types = [("Excel文件", "*.xlsx"), ("所有文件", "*.*")]
        return filedialog.asksaveasfilename(parent=parent, title=title, 
                                           defaultextension=default_ext, filetypes=file_types)