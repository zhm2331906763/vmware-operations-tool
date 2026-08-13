# 定时开关机与信息查询 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 `定时巡检` 后面新增 `定时开关机` 板块，保留批量输入 IP / 虚拟机名称时的存在性校验；再在其后新增 `信息查询` 板块，基于本地静态巡检表按 IP 或虚拟机名称查出 ESXi 与 VM 巡检的全部字段，并最终打包成可交付的 `VCenterManager_0604.exe`。

**Architecture:** 保持现有巡检能力不动，把新能力拆成独立的“后台服务 + UI 面板 + 数据库访问”三层。`定时开关机` 参考 `D:\vm-shutdown\vm_timer_tool` 的做法，保存 VM 目标引用、按 UUID 优先回找、支持一次/每天/每周调度；但为了不打散现有巡检调度，建议作为一套独立的 power-task 存储与执行模块接入 `定时巡检` 页里的第二个内页。`信息查询` 直接查本地 SQLite 的 `host_inspect` / `vm_inspect`，把两张表的完整行展示出来，不再依赖在线 vCenter。

**Tech Stack:** Python 3.11+, `Tkinter`, `sqlite3`, `pyVmomi`, `openpyxl`, `PyInstaller`

---

### Task 1: Add a dedicated power-task store and scheduler, while preserving VM existence validation

**Files:**
- Modify: `src/db/database.py`
- Modify: `src/core/vcenter_connector.py`
- Create: `src/core/power_scheduler.py`
- Create: `src/core/power_models.py`
- Modify: `src/ui/schedule.py`
- Modify: `tests/test_power_scheduler.py`
- Modify: `tests/test_vcenter_connector.py`

目标是把 `D:\vm-shutdown` 里的关键设计搬进来，但不破坏现有巡检任务表。这里不要把开关机任务硬塞进 `scheduled_tasks`，而是新增一张独立表，避免和现有巡检任务字段互相污染。

- [ ] **Step 1: 写出会先失败的测试，锁定“批量输入必须全都可解析且可追溯”**

```python
def test_create_power_task_from_queries_requires_all_targets_exist(tmp_path):
    controller = build_controller(tmp_path, fake_connector=FakeConnector)
    controller.seed_vm_inspect([
        {"vc_ip": "10.0.0.10", "vm_name": "alpha", "uuid": "uuid-1", "host": "esxi-1", "ip_address": "10.0.0.11"},
        {"vc_ip": "10.0.0.10", "vm_name": "beta", "uuid": "uuid-2", "host": "esxi-2", "ip_address": "10.0.0.12"},
    ])

    task = controller.create_power_task_from_batch_queries(
        vcenter_name="prod",
        task_name="night power on",
        action="power_on",
        schedule_type="daily",
        schedule_time="23:30",
        query_text="alpha\n10.0.0.12",
    )

    assert [ref.uuid for ref in task.target_refs] == ["uuid-1", "uuid-2"]
    assert task.action == "power_on"
```

```python
def test_create_power_task_rejects_missing_vm_entries(tmp_path):
    controller = build_controller(tmp_path, fake_connector=FakeConnector)
    controller.seed_vm_inspect([{"vc_ip": "10.0.0.10", "vm_name": "alpha", "uuid": "uuid-1", "host": "esxi-1", "ip_address": "10.0.0.11"}])

    with pytest.raises(ValueError, match="未找到匹配的虚拟机"):
        controller.create_power_task_from_batch_queries(
            vcenter_name="prod",
            task_name="bad task",
            action="power_off",
            schedule_type="once",
            schedule_time="23:30",
            query_text="missing-vm",
        )
```

- [ ] **Step 2: 运行测试，确认当前代码没有这些能力**

Run:
`pytest tests/test_power_scheduler.py -v`

Expected:
首次运行应失败，因为新的 power-task store、查询解析、以及任务创建接口还没有实现。

- [ ] **Step 3: 实现独立的 power-task 数据结构与数据库表**

```python
@dataclass(slots=True)
class PowerTaskTarget:
    uuid: str = ""
    name: str = ""
    host: str = ""
    ip_address: str = ""
    cluster: str = ""


@dataclass(slots=True)
class PowerTask:
    id: str
    name: str
    action: str
    schedule_type: str
    schedule_time: str
    schedule_day: str = ""
    enabled: bool = True
    vcenter_name: str = ""
    targets: list[PowerTaskTarget] = field(default_factory=list)
    last_run: str = ""
    last_status: str = ""
    created_at: str = ""
    updated_at: str = ""
```

```sql
CREATE TABLE IF NOT EXISTS power_tasks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    action TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    schedule_time TEXT NOT NULL,
    schedule_day TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    vcenter_name TEXT DEFAULT '',
    targets_json TEXT NOT NULL,
    last_run TEXT,
    last_status TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

`src/db/database.py` 需要新增这些方法：

```python
def add_power_task(self, task: PowerTask) -> str: ...
def get_power_tasks(self) -> list[tuple]: ...
def get_enabled_power_tasks(self) -> list[tuple]: ...
def update_power_task_status(self, task_id: str, status: str) -> None: ...
def delete_power_task(self, task_id: str) -> None: ...
def get_vm_inspect_by_query(self, query_text: str) -> tuple[list[tuple], list[str]]: ...
```

- [ ] **Step 4: 把 `vCenterConnector` 补成和 vm_timer_tool 一样可按 UUID / 名称 / IP 回找 VM**

`src/core/vcenter_connector.py` 当前只有 `find_vm_by_uuid()` 和 `get_vm_by_name()`，没有 `get_vm_by_ip()`，而 power-task 执行时要按 `UUID -> 名称 -> IP` 依次回找。补上下面这个方法，并在执行路径里统一调用：

```python
def get_vm_by_ip(self, ip_address):
    if not self.is_connected():
        return None
    container = self.content.viewManager.CreateContainerView(
        self.content.rootFolder, [vim.VirtualMachine], True
    )
    try:
        for vm in container.view:
            guest = getattr(vm, "guest", None)
            if getattr(guest, "ipAddress", "") == ip_address:
                return vm
        return None
    finally:
        container.Destroy()
```

- [ ] **Step 5: 实现 power-task 调度器和执行器**

`src/core/power_scheduler.py` 负责：
- 周期性读取 `power_tasks`
- 到点后把任务标成执行中
- 按目标引用批量连接 vCenter 并执行 `power_on` / `power_off`
- 失败时把 `last_status` 写成可直接在 UI 里看的中文结果
- 一次性任务执行后自动失效，重复任务保留启用状态

执行顺序要和 `vm_timer_tool` 一致：

```python
def resolve_vm_ref(client, ref):
    if ref.uuid:
        vm = client.find_vm_by_uuid(ref.uuid)
        if vm:
            return vm
    if ref.name:
        vm = client.get_vm_by_name(ref.name)
        if vm:
            return vm
    if ref.ip_address:
        vm = client.get_vm_by_ip(ref.ip_address)
        if vm:
            return vm
    return None
```

`src/ui/schedule.py` 里保留现有巡检页，新增一个第二内页 `定时开关机`，不要把它混到巡检任务表里。

- [ ] **Step 6: 运行测试，确认任务创建、执行、一次性失效都通过**

Run:
`pytest tests/test_power_scheduler.py -v tests/test_vcenter_connector.py -v`

Expected:
批量解析测试、缺失 VM 拒绝测试、以及执行顺序测试都通过。

- [ ] **Step 7: 提交前清理**

确认 `power_tasks` 的 JSON 序列化和反序列化能跨重启恢复，`last_status` 会在 UI 列表里直接显示，不需要额外查库。

---

### Task 2: Add a static-table information query panel that returns full ESXi and VM inspection rows

**Files:**
- Modify: `src/db/database.py`
- Create: `src/core/inspection_query.py`
- Create: `src/ui/information_query.py`
- Modify: `src/ui/schedule.py`
- Modify: `tests/test_inspection_query.py`

信息查询要完全基于本地静态表，不再打活体 vCenter。输入框接受 IP 或虚拟机名称，先查 `vm_inspect`，再按 VM 的 `vc_ip + host` 关联查 `host_inspect`，同时也允许直接按 ESXi 主机名查主机表。结果区必须显示巡检表里的所有字段，不做截断。

- [ ] **Step 1: 写出会先失败的查询测试，固定查询语义**

```python
def test_query_by_vm_name_returns_vm_row_and_related_host_row(tmp_path):
    db = build_database(tmp_path)
    db.save_host_inspect([
        {
            "vc_ip": "10.0.0.10",
            "host_name": "esxi-1",
            "cluster": "cluster-a",
            "status": "green",
            "esxi_version": "8.0.2",
            "vendor": "Dell",
            "model": "R650",
            "serial_number": "SN-1",
            "cpu_model": "Xeon",
            "cpu_ghz": 3.0,
            "cpu_count": 2,
            "cpu_cores": 32,
            "memory_gb": 256,
            "uptime_days": 12,
            "cpu_usage": 10,
            "memory_usage": 42,
            "cert_expiring_soon": "否",
            "vmk_adapters": "vmk0",
            "cert_expiry": "2027-01-01",
        }
    ])
    db.save_vm_inspect([
        {
            "vc_ip": "10.0.0.10",
            "vm_name": "app-01",
            "cluster": "cluster-a",
            "host": "esxi-1",
            "power_state": "poweredOn",
            "ip_address": "10.0.0.21",
            "memory_gb": 8,
            "cpu_count": 2,
            "uuid": "uuid-1",
            "annotation": "",
            "system_version": "Ubuntu 22.04",
            "guest_os": "Ubuntu Linux (64-bit)",
            "tools_status": "toolsOk",
            "uptime_days": 2,
            "datastore": "ds1",
            "vm_portgroups": "VLAN100",
            "disks": "40G",
            "used_space_gb": 10,
            "folder": "prod",
        }
    ])

    result = InspectionQueryService(db).query("app-01")
    assert result.vm_rows[0][2] == "app-01"
    assert result.host_rows[0][2] == "esxi-1"
```

```python
def test_query_by_ip_returns_matching_vm_and_host_fields(tmp_path):
    db = build_database(tmp_path)
    ...
    result = InspectionQueryService(db).query("10.0.0.21")
    assert result.vm_rows[0][6] == "10.0.0.21"
    assert "cpu_usage" in result.host_columns
    assert "guest_os" in result.vm_columns
```

- [ ] **Step 2: 运行测试，确认当前没有统一查询层**

Run:
`pytest tests/test_inspection_query.py -v`

Expected:
失败，说明查询服务和数据库辅助方法还没实现。

- [ ] **Step 3: 给数据库增加“按静态表查全字段”的辅助方法**

`src/db/database.py` 需要新增面向查询面板的方法，直接返回原始行，不要提前裁剪列：

```python
def find_host_inspect_rows(self, query_text: str) -> list[tuple]: ...
def find_vm_inspect_rows(self, query_text: str) -> list[tuple]: ...
def find_related_host_rows_for_vm_rows(self, vm_rows: list[tuple]) -> list[tuple]: ...
```

建议查询规则如下：
- 如果输入是 IP，先匹配 `vm_inspect.ip_address`
- 如果输入是名称，优先匹配 `vm_inspect.vm_name` 和 `host_inspect.host_name`
- 对每个命中的 VM，再用它的 `vc_ip + host` 反查 ESXi 主机行
- 如果输入本身就是 ESXi 主机名，也直接返回主机行

- [ ] **Step 4: 实现查询服务，输出完整列名和完整行**

`src/core/inspection_query.py` 建议提供一个轻量结果对象：

```python
@dataclass(slots=True)
class InspectionQueryResult:
    query_text: str
    host_columns: list[str]
    host_rows: list[tuple]
    vm_columns: list[str]
    vm_rows: list[tuple]
```

UI 不要混合两类字段，建议分成两个结果表：
- ESXi 巡检结果表：显示 `host_inspect` 的全部字段
- VM 巡检结果表：显示 `vm_inspect` 的全部字段

这样用户能直接看到完整信息，不需要横向滚动到看不清的单表。

- [ ] **Step 5: 把查询面板接到 `定时开关机` 后面**

`src/ui/schedule.py` 里把原有巡检页改成一个内层 `ttk.Notebook`，顺序固定为：
1. `定时巡检`
2. `定时开关机`
3. `信息查询`

`src/ui/information_query.py` 负责：
- 单行输入 / 多行输入
- 点击查询
- 显示 ESXi 结果和 VM 结果
- 提供清空按钮

- [ ] **Step 6: 运行测试，确认查出来的是完整字段而不是裁剪列**

Run:
`pytest tests/test_inspection_query.py -v`

Expected:
测试要验证返回的列数与 `host_inspect` / `vm_inspect` 的全字段一致，而不是只返回几列摘要。

---

### Task 3: Integrate the new schedule notebook and rebuild `VCenterManager_0604.exe`

**Files:**
- Modify: `src/ui/schedule.py`
- Modify: `src/app.py`
- Modify: `setup.spec`
- Modify: `requirements.txt` if a new dependency is introduced
- Modify: `README.md` if the deliverable name or usage instructions need to mention the new sections

这一步只做收尾集成和打包，不再引入新的业务逻辑。目标是保证用户打开 exe 后，能按顺序看到 `定时巡检 -> 定时开关机 -> 信息查询`，并且新模块都被 PyInstaller 打进包里。

- [ ] **Step 1: 补齐 PyInstaller 的 hiddenimports 和数据文件**

`setup.spec` 当前只包含巡检和旧模块的 hiddenimports。新功能至少要加入：

```python
hiddenimports += [
    'src.core.power_scheduler',
    'src.core.power_models',
    'src.core.inspection_query',
    'src.ui.information_query',
]
```

如果新的 UI 面板还拆了别的辅助模块，也要一并加入，避免打包后点击界面时报 `ModuleNotFoundError`。

- [ ] **Step 2: 把 exe 名称改成当天交付名**

`setup.spec` 里的：

```python
name='VCenterManager_0603'
```

改成：

```python
name='VCenterManager_0604'
```

这样当天生成的成品就和用户要求一致，不需要手工改名。

- [ ] **Step 3: 先跑最小验证，再跑完整打包**

Run:
`python -m pytest tests/test_power_scheduler.py tests/test_inspection_query.py -v`

Expected:
核心新增逻辑通过。

Then run:
`pyinstaller --noconfirm setup.spec`

Expected:
`dist\\VCenterManager_0604\\VCenterManager_0604.exe` 或等价输出目录中生成可启动程序。

- [ ] **Step 4: 启动成品检查三件事**

必须在打包后的 exe 里确认：
- `定时巡检` 仍然正常
- `定时开关机` 能创建任务并保留 VM 校验
- `信息查询` 能查出 host / VM 全字段

如果任一模块在 exe 中打不开，先修 `setup.spec`，不要手工拷源码去“碰巧能跑”。

- [ ] **Step 5: 交付前的最终清单**

确认以下内容都就位：
- `VCenterManager_0604.exe`
- 依赖已被打包，不要求用户额外安装 Python
- 新增的任务数据能跨重启读回
- 查询页返回的字段完整且顺序稳定

---

## Self-Review Checklist

- `定时开关机` 的保存、调度、执行、失效逻辑都有单独文件和单独测试，不会和现有巡检表互相污染。
- 批量输入 IP / VM 名称时，所有条目都必须在静态表中解析成功，否则直接报错拒绝保存。
- `信息查询` 只读本地 SQLite，不依赖在线 vCenter，且返回 `host_inspect` / `vm_inspect` 的完整字段。
- UI 内层顺序是 `定时巡检 -> 定时开关机 -> 信息查询`，符合用户要求的“后面再放一个板块”。
- `setup.spec` 已更新为当天交付名 `VCenterManager_0604`，并把新模块纳入打包。
- 计划中没有 `TBD`、`TODO`、`later` 之类占位描述。

