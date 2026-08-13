import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from src.db.database import Database
from src.core.scheduler import TaskScheduler, TASK_TYPES, SCHEDULE_TYPES, WEEK_DAYS
from src.core.power_models import PowerTask
from src.core.power_scheduler import PowerTaskScheduler
from src.core.power_task_store import PowerTaskStore
from src.ui.information_query import InformationQueryPage
from src.ui.theme import COLORS, FONTS
from src.ui.enhanced_widgets import EnhancedButton


SCHEDULE_LABEL_TO_KEY = {
    "每天": "daily",
    "每周": "weekly",
    "仅一次": "once",
}

SCHEDULE_KEY_TO_LABEL = {
    "daily": "每天",
    "weekly": "每周",
    "once": "仅一次",
}

POWER_ACTION_LABEL_TO_KEY = {
    "开机": "power_on",
    "关机": "power_off",
}

POWER_ACTION_KEY_TO_LABEL = {
    "power_on": "开机",
    "power_off": "关机",
}

DAY_LABEL_TO_KEY = {
    "周一": "0",
    "周二": "1",
    "周三": "2",
    "周四": "3",
    "周五": "4",
    "周六": "5",
    "周日": "6",
}

DAY_KEY_TO_LABEL = {value: key for key, value in DAY_LABEL_TO_KEY.items()}


class SchedulePage:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.db = Database()
        self.inspection_scheduler = TaskScheduler(app)
        self.power_store = PowerTaskStore()
        self.power_scheduler = PowerTaskScheduler(app, store=self.power_store, db=self.db)

        self._create_ui()
        self.inspection_tab.load_tasks()
        self.power_tab.load_tasks()
        self.inspection_scheduler.start()
        self.power_scheduler.start()

    def _create_ui(self):
        self.notebook = ttk.Notebook(self.parent, style="Main.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        inspection_frame = ttk.Frame(self.notebook, style="Card.TFrame")
        power_frame = ttk.Frame(self.notebook, style="Card.TFrame")
        query_frame = ttk.Frame(self.notebook, style="Card.TFrame")

        self.notebook.add(inspection_frame, text=" 定时巡检")
        self.notebook.add(power_frame, text=" 定时开关机")
        self.notebook.add(query_frame, text=" 信息查询")

        self.inspection_tab = InspectionScheduleTab(inspection_frame, self.app, self.db, self.inspection_scheduler)
        self.power_tab = PowerTaskTab(power_frame, self.app, self.db, self.power_store, self.power_scheduler)
        self.query_tab = InformationQueryPage(query_frame, self.app)
        self.query_tab.pack(fill=tk.BOTH, expand=True)

    def refresh_vcenter_lists(self):
        self.inspection_tab.load_tasks()
        self.power_tab.load_tasks()

    def close(self):
        self.inspection_scheduler.stop()
        self.power_scheduler.stop()


class InspectionScheduleTab:
    def __init__(self, parent, app, db: Database, scheduler: TaskScheduler):
        self.parent = parent
        self.app = app
        self.db = db
        self.scheduler = scheduler
        self._create_ui()

    def _create_ui(self):
        toolbar = ttk.Frame(self.parent, style="Card.TFrame")
        toolbar.pack(fill=tk.X, padx=10, pady=5)

        EnhancedButton(toolbar, "添加任务", "➕", command=self._add_task).pack(side=tk.LEFT, padx=2)
        EnhancedButton(toolbar, "刷新", "🔄", command=self.load_tasks).pack(side=tk.LEFT, padx=2)

        table_frame = ttk.Frame(self.parent, style="Card.TFrame")
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        columns = ("id", "任务名称", "任务类型", "调度方式", "执行时间", "保存路径", "状态")
        col_widths = {
            "id": 0,
            "任务名称": 160,
            "任务类型": 140,
            "调度方式": 90,
            "执行时间": 130,
            "保存路径": 220,
            "状态": 180,
        }

        self.tree = ttk.Treeview(table_frame, columns=columns, show="tree headings", height=20)
        self.tree.column("#0", width=0, stretch=False)

        for col in columns:
            if col == "id":
                self.tree.column(col, width=0, stretch=False)
            else:
                self.tree.heading(col, text=col, anchor="center")
                self.tree.column(col, width=col_widths.get(col, 100), anchor="center")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree.bind("<Button-3>", self._show_context_menu)

        style = ttk.Style()
        style.configure("Treeview", rowheight=30, font=FONTS["normal"])
        style.configure("Treeview.Heading", font=FONTS["bold"], background=COLORS["bg_toolbar"], anchor="center")

    def load_tasks(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        tasks = self.db.get_scheduled_tasks()
        for task in tasks:
            task_id = task[0]
            task_name = task[1]
            task_type = TASK_TYPES.get(task[2], task[2])

            schedule_type_key = task[3]
            schedule_type = SCHEDULE_TYPES.get(schedule_type_key, task[3])
            schedule_time = task[4]
            schedule_day = task[5]
            save_path = task[6] or ""
            enabled = bool(task[7])
            last_status = task[9] or ""

            if schedule_type_key == "weekly" and schedule_day:
                schedule_time = f"{WEEK_DAYS.get(schedule_day, '')} {schedule_time}"

            status_text = last_status if last_status else ("已启用" if enabled else "已禁用")

            self.tree.insert(
                "",
                tk.END,
                values=(task_id, task_name, task_type, schedule_type, schedule_time, save_path, status_text),
                tags=(str(task_id),),
            )

    def _show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return

        values = self.tree.item(item, "values")
        task_id = values[0]

        menu = tk.Menu(self.parent, tearoff=0)
        menu.add_command(label="立即执行", command=lambda: self._run_now(task_id))
        menu.add_command(label="编辑", command=lambda: self._edit_task(task_id))
        menu.add_command(label="删除", command=lambda: self._delete_task(task_id))
        menu.post(event.x_root, event.y_root)

    def _run_now(self, task_id):
        tasks = self.db.get_scheduled_tasks()
        for task in tasks:
            if task[0] == int(task_id):
                self.scheduler.run_task_now(task[0], task[1], task[2], task[6])
                messagebox.showinfo("提示", "任务已开始执行")
                return

    def _edit_task(self, task_id):
        tasks = self.db.get_scheduled_tasks()
        task = None
        for t in tasks:
            if t[0] == int(task_id):
                task = t
                break
        if not task:
            return

        self._show_task_dialog(task)

    def _delete_task(self, task_id):
        if messagebox.askyesno("确认", "确定删除此定时任务?"):
            self.db.delete_task(int(task_id))
            self.load_tasks()

    def _add_task(self):
        self._show_task_dialog()

    def _show_task_dialog(self, task=None):
        dialog = tk.Toplevel(self.parent)
        dialog.title("添加定时任务" if not task else "编辑定时任务")
        dialog.geometry("520x420")
        dialog.transient(self.parent)
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=20)
        container.pack(fill=tk.BOTH, expand=True)

        row = 0
        ttk.Label(container, text="任务名称:").grid(row=row, column=0, sticky="w", pady=5)
        name_var = tk.StringVar(value=task[1] if task else "定时巡检")
        ttk.Entry(container, textvariable=name_var, width=30).grid(row=row, column=1, padx=5, pady=5)
        row += 1

        ttk.Label(container, text="任务类型:").grid(row=row, column=0, sticky="w", pady=5)
        type_var = tk.StringVar(value=task[2] if task else "host_inspect")
        type_combo = ttk.Combobox(container, textvariable=type_var, state="readonly", width=25)
        type_combo["values"] = list(TASK_TYPES.keys())
        type_combo.grid(row=row, column=1, padx=5, pady=5)
        row += 1

        ttk.Label(container, text="调度方式:").grid(row=row, column=0, sticky="w", pady=5)
        initial_schedule = SCHEDULE_KEY_TO_LABEL.get(task[3], task[3]) if task else "每天"
        schedule_var = tk.StringVar(value=initial_schedule)
        schedule_combo = ttk.Combobox(container, textvariable=schedule_var, state="readonly", width=25, values=list(SCHEDULE_LABEL_TO_KEY.keys()))
        schedule_combo.grid(row=row, column=1, padx=5, pady=5)

        def on_schedule_change(*args):
            if schedule_var.get() == "每周":
                day_label.grid()
                day_combo.grid()
            else:
                day_label.grid_remove()
                day_combo.grid_remove()

        schedule_var.trace("w", on_schedule_change)
        row += 1

        ttk.Label(container, text="执行时间:").grid(row=row, column=0, sticky="w", pady=5)
        time_var = tk.StringVar(value=task[4] if task else "08:00")
        time_entry = ttk.Entry(container, textvariable=time_var, width=15)
        time_entry.grid(row=row, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(container, text="格式: HH:MM").grid(row=row, column=2, padx=5, pady=5)
        row += 1

        day_label = ttk.Label(container, text="执行星期:")
        day_value = DAY_KEY_TO_LABEL.get(task[5], "周一") if task and task[5] else "周一"
        day_var = tk.StringVar(value=day_value)
        day_combo = ttk.Combobox(container, textvariable=day_var, state="readonly", width=25, values=list(DAY_LABEL_TO_KEY.keys()))

        if schedule_var.get() == "每周":
            day_label.grid(row=row, column=0, sticky="w", pady=5)
            day_combo.grid(row=row, column=1, padx=5, pady=5)
        else:
            day_label.grid_remove()
            day_combo.grid_remove()
        row += 1

        ttk.Label(container, text="保存路径:").grid(row=row, column=0, sticky="w", pady=5)
        path_frame = ttk.Frame(container)
        path_frame.grid(row=row, column=1, columnspan=2, padx=5, pady=5, sticky="ew")
        path_var = tk.StringVar(value=task[6] if task and task[6] else "")
        ttk.Entry(path_frame, textvariable=path_var, width=25).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(path_frame, text="浏览", command=lambda: self._browse_path(path_var)).pack(side=tk.LEFT, padx=2)
        row += 1

        def save():
            task_name = name_var.get().strip()
            task_type = type_var.get()
            schedule_type = schedule_var.get()
            schedule_time = time_var.get().strip()

            schedule_type_key = SCHEDULE_LABEL_TO_KEY.get(schedule_type, "daily")

            schedule_day = "0"
            if schedule_type == "每周":
                schedule_day = DAY_LABEL_TO_KEY.get(day_var.get(), "0")

            save_path = path_var.get().strip()

            if not task_name:
                messagebox.showwarning("提示", "请输入任务名称")
                return
            if not schedule_time:
                messagebox.showwarning("提示", "请输入执行时间")
                return
            if len(schedule_time) != 5 or schedule_time[2] != ":":
                messagebox.showwarning("提示", "执行时间格式错误，请使用 HH:MM")
                return

            if task:
                self.db.update_scheduled_task(
                    task_id=task[0],
                    task_name=task_name,
                    task_type=task_type,
                    schedule_type=schedule_type_key,
                    schedule_time=schedule_time,
                    schedule_day=schedule_day,
                    save_path=save_path,
                )
            else:
                self.db.add_scheduled_task(task_name, task_type, schedule_type_key, schedule_time, schedule_day, save_path)

            dialog.destroy()
            self.load_tasks()
            messagebox.showinfo("完成", "任务已保存")

        btn_frame = ttk.Frame(container)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=20)
        ttk.Button(btn_frame, text="保存", command=save).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def _browse_path(self, path_var):
        path = filedialog.askdirectory()
        if path:
            path_var.set(path)


class PowerTaskTab:
    def __init__(self, parent, app, db: Database, store: PowerTaskStore, scheduler: PowerTaskScheduler):
        self.parent = parent
        self.app = app
        self.db = db
        self.store = store
        self.scheduler = scheduler
        self._create_ui()

    def _create_ui(self):
        toolbar = ttk.Frame(self.parent, style="Card.TFrame")
        toolbar.pack(fill=tk.X, padx=10, pady=5)

        EnhancedButton(toolbar, "添加任务", "➕", command=self._add_task).pack(side=tk.LEFT, padx=2)
        EnhancedButton(toolbar, "刷新", "🔄", command=self.load_tasks).pack(side=tk.LEFT, padx=2)

        table_frame = ttk.Frame(self.parent, style="Card.TFrame")
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        columns = ("id", "任务名称", "动作", "调度方式", "执行时间", "目标数量", "目标摘要", "状态")
        col_widths = {
            "id": 0,
            "任务名称": 150,
            "动作": 90,
            "调度方式": 90,
            "执行时间": 130,
            "目标数量": 80,
            "目标摘要": 280,
            "状态": 220,
        }

        self.tree = ttk.Treeview(table_frame, columns=columns, show="tree headings", height=20)
        self.tree.column("#0", width=0, stretch=False)

        for col in columns:
            if col == "id":
                self.tree.column(col, width=0, stretch=False)
            else:
                self.tree.heading(col, text=col, anchor="center")
                self.tree.column(col, width=col_widths.get(col, 100), anchor="center")

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tree.bind("<Button-3>", self._show_context_menu)

        style = ttk.Style()
        style.configure("Treeview", rowheight=30, font=FONTS["normal"])
        style.configure("Treeview.Heading", font=FONTS["bold"], background=COLORS["bg_toolbar"], anchor="center")

    def load_tasks(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        tasks = self.store.get_power_tasks()
        for task in tasks:
            action_label = POWER_ACTION_KEY_TO_LABEL.get(task.action, task.action)
            schedule_type_label = SCHEDULE_KEY_TO_LABEL.get(task.schedule_type, task.schedule_type)
            schedule_time = task.schedule_time
            if task.schedule_type == "weekly" and task.schedule_day:
                schedule_time = f"{DAY_KEY_TO_LABEL.get(task.schedule_day, '')} {schedule_time}".strip()

            status_text = task.last_status if task.last_status else ("已启用" if task.enabled else "已禁用")

            self.tree.insert(
                "",
                tk.END,
                values=(
                    task.id,
                    task.name,
                    action_label,
                    schedule_type_label,
                    schedule_time,
                    task.target_count,
                    task.target_summary,
                    status_text,
                ),
                tags=(str(task.id),),
            )

    def _show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return

        values = self.tree.item(item, "values")
        task_id = values[0]

        menu = tk.Menu(self.parent, tearoff=0)
        menu.add_command(label="立即执行", command=lambda: self._run_now(task_id))
        menu.add_command(label="编辑", command=lambda: self._edit_task(task_id))
        menu.add_command(label="删除", command=lambda: self._delete_task(task_id))
        menu.post(event.x_root, event.y_root)

    def _run_now(self, task_id):
        if not self.scheduler.run_task_now(str(task_id)):
            messagebox.showwarning("提示", "未找到对应的定时开关机任务")
            return
        messagebox.showinfo("提示", "任务已开始执行")

    def _edit_task(self, task_id):
        task = self.store.get_power_task(str(task_id))
        if not task:
            return
        self._show_task_dialog(task)

    def _delete_task(self, task_id):
        if messagebox.askyesno("确认", "确定删除此定时开关机任务?"):
            self.store.delete_power_task(str(task_id))
            self.load_tasks()

    def _add_task(self):
        self._show_task_dialog()

    def _show_task_dialog(self, task: PowerTask | None = None):
        dialog = tk.Toplevel(self.parent)
        dialog.title("添加定时开关机任务" if not task else "编辑定时开关机任务")
        dialog.geometry("620x560")
        dialog.transient(self.parent)
        dialog.grab_set()

        container = ttk.Frame(dialog, padding=20)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(container, text="任务名称:").grid(row=row, column=0, sticky="w", pady=5)
        name_var = tk.StringVar(value=task.name if task else "定时开关机")
        ttk.Entry(container, textvariable=name_var, width=35).grid(row=row, column=1, padx=5, pady=5, sticky="ew")
        row += 1

        ttk.Label(container, text="动作:").grid(row=row, column=0, sticky="w", pady=5)
        action_label = POWER_ACTION_KEY_TO_LABEL.get(task.action, "开机") if task else "开机"
        action_var = tk.StringVar(value=action_label)
        action_combo = ttk.Combobox(container, textvariable=action_var, state="readonly", width=32, values=list(POWER_ACTION_LABEL_TO_KEY.keys()))
        action_combo.grid(row=row, column=1, padx=5, pady=5, sticky="ew")
        row += 1

        ttk.Label(container, text="调度方式:").grid(row=row, column=0, sticky="w", pady=5)
        schedule_label = SCHEDULE_KEY_TO_LABEL.get(task.schedule_type, task.schedule_type) if task else "每天"
        schedule_var = tk.StringVar(value=schedule_label)
        schedule_combo = ttk.Combobox(container, textvariable=schedule_var, state="readonly", width=32, values=list(SCHEDULE_LABEL_TO_KEY.keys()))
        schedule_combo.grid(row=row, column=1, padx=5, pady=5, sticky="ew")

        def on_schedule_change(*args):
            if schedule_var.get() == "每周":
                day_label.grid()
                day_combo.grid()
            else:
                day_label.grid_remove()
                day_combo.grid_remove()

        schedule_var.trace("w", on_schedule_change)
        row += 1

        ttk.Label(container, text="执行时间:").grid(row=row, column=0, sticky="w", pady=5)
        time_var = tk.StringVar(value=task.schedule_time if task else "23:30")
        time_entry = ttk.Entry(container, textvariable=time_var, width=15)
        time_entry.grid(row=row, column=1, padx=5, pady=5, sticky="w")
        ttk.Label(container, text="格式: HH:MM").grid(row=row, column=2, padx=5, pady=5, sticky="w")
        row += 1

        day_label = ttk.Label(container, text="执行星期:")
        day_value = DAY_KEY_TO_LABEL.get(task.schedule_day, "周一") if task and task.schedule_day else "周一"
        day_var = tk.StringVar(value=day_value)
        day_combo = ttk.Combobox(container, textvariable=day_var, state="readonly", width=32, values=list(DAY_LABEL_TO_KEY.keys()))

        if schedule_var.get() == "每周":
            day_label.grid(row=row, column=0, sticky="w", pady=5)
            day_combo.grid(row=row, column=1, padx=5, pady=5, sticky="ew")
        else:
            day_label.grid_remove()
            day_combo.grid_remove()
        row += 1

        ttk.Label(container, text="目标输入:").grid(row=row, column=0, sticky="nw", pady=5)
        target_frame = ttk.Frame(container)
        target_frame.grid(row=row, column=1, columnspan=2, padx=5, pady=5, sticky="nsew")
        container.rowconfigure(row, weight=1)

        target_text = tk.Text(target_frame, height=14, width=52, font=FONTS["normal"])
        target_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        target_scroll = ttk.Scrollbar(target_frame, orient="vertical", command=target_text.yview)
        target_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        target_text.configure(yscrollcommand=target_scroll.set)

        help_label = ttk.Label(
            container,
            text="支持 UUID、虚拟机名称或 IP，每行一个，也可用逗号分隔。保存时会先在本地静态表中校验存在性。",
            foreground=COLORS["text_secondary"],
            wraplength=480,
            justify="left",
        )
        help_label.grid(row=row + 1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        if task and task.targets:
            default_tokens = [target.uuid or target.name or target.ip_address for target in task.targets]
            target_text.insert("1.0", "\n".join(default_tokens))

        def save():
            task_name = name_var.get().strip()
            action = POWER_ACTION_LABEL_TO_KEY.get(action_var.get(), "power_on")
            schedule_type = SCHEDULE_LABEL_TO_KEY.get(schedule_var.get(), "daily")
            schedule_time = time_var.get().strip()
            schedule_day = "0"
            if schedule_type == "weekly":
                schedule_day = DAY_LABEL_TO_KEY.get(day_var.get(), "0")
            query_text = target_text.get("1.0", tk.END).strip()

            if not task_name:
                messagebox.showwarning("提示", "请输入任务名称")
                return
            if not schedule_time:
                messagebox.showwarning("提示", "请输入执行时间")
                return
            if len(schedule_time) != 5 or schedule_time[2] != ":":
                messagebox.showwarning("提示", "执行时间格式错误，请使用 HH:MM")
                return
            if not query_text:
                messagebox.showwarning("提示", "请输入至少一个目标")
                return

            try:
                built_task = self.store.build_power_task_from_batch_queries(
                    task_name=task_name,
                    action=action,
                    schedule_type=schedule_type,
                    schedule_time=schedule_time,
                    query_text=query_text,
                    schedule_day=schedule_day,
                    task_id=task.id if task else "",
                )
            except ValueError as exc:
                messagebox.showwarning("提示", str(exc))
                return

            if task:
                built_task = PowerTask(
                    id=task.id,
                    name=built_task.name,
                    action=built_task.action,
                    schedule_type=built_task.schedule_type,
                    schedule_time=built_task.schedule_time,
                    schedule_day=built_task.schedule_day,
                    enabled=task.enabled,
                    vcenter_name=task.vcenter_name,
                    targets=built_task.targets,
                    last_run=task.last_run,
                    last_status=task.last_status,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
                self.store.update_power_task(task.id, built_task)
            else:
                self.store.add_power_task(built_task)

            dialog.destroy()
            self.load_tasks()
            messagebox.showinfo("完成", "任务已保存")

        btn_frame = ttk.Frame(container)
        btn_frame.grid(row=row + 2, column=0, columnspan=3, pady=20)
        ttk.Button(btn_frame, text="保存", command=save).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def load_tasks_from_scheduler(self):
        self.load_tasks()
