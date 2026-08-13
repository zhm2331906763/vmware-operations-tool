# VCenter管理巡检工具 UI重构设计方案

## 版本信息
- 设计日期: 2026-07-19
- 版本: 1.0
- 状态: 待实施

---

## 1. 项目背景

### 1.1 现状问题
当前项目使用Python tkinter构建UI界面，存在以下问题：
- 界面美观度不足，不符合现代应用标准
- 组件库有限，难以实现复杂交互
- 样式定制困难，维护成本高

### 1.2 重构目标
- 使用现代化技术栈重写UI层
- 保持现有Python核心业务逻辑可复用
- 提升用户体验和开发效率
- 生成独立的exe安装包

---

## 2. 技术方案选择

### 2.1 方案对比

| 方案 | 优点 | 缺点 | 包体积 | 学习成本 |
|------|------|------|--------|----------|
| Electron + React | 生态成熟、组件丰富、开发效率高 | 包体积大(~150MB+) | 大 | 低 |
| Tauri + React | 轻量(~10MB)、性能好、安全性高 | 需要Rust、生态较小 | 小 | 中 |
| Python + PyWebIO | 纯Python、复用现有代码 | 界面受限、部署麻烦 | 小 | 低 |
| Flutter Desktop | 跨平台、UI美观 | 需要Dart、Python集成复杂 | 中 | 高 |

### 2.2 最终选择：Electron + React

**选择理由：**
1. **开发效率最高** - React组件生态丰富，MUI等成熟UI库
2. **Python集成简单** - 通过child_process调用Python脚本
3. **打包方便** - electron-builder直接打包成exe
4. **UI美观度高** - 可以做出专业级的管理后台界面

---

## 3. 系统架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Electron Application                     │
├─────────────────────────────────────────────────────────────┤
│  Renderer Process (React + TypeScript)                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  UI Layer (MUI v5 - Material Design)                  │  │
│  │  ├── Pages: vCenter管理 / ESXi巡检 / VM巡检 / ...     │  │
│  │  ├── Components: Table / Form / Dialog / Charts       │  │
│  │  └── State: Zustand Store                             │  │
│  └───────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  Main Process (Node.js)                                     │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  ├── IPC Handlers (ipcMain/ipcRenderer)               │  │
│  │  ├── Python Process Manager                           │  │
│  │  └── File System Operations                           │  │
│  └───────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  Python Core (复用现有 src/core/)                           │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  ├── vcenter_connector.py                             │  │
│  │  ├── host_collector.py                                │  │
│  │  ├── vm_collector.py                                  │  │
│  │  ├── batch_operations.py                              │  │
│  │  └── database.py                                      │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 目录结构

```
vm-manager-electron/
├── electron/                          # Electron主进程
│   ├── main.js                       # 主进程入口
│   ├── preload.js                    # 预加载脚本(安全桥接)
│   ├── ipc-handlers.js               # IPC通信处理
│   └── python-runner.js              # Python子进程管理
├── src/                              # React前端源码
│   ├── main.tsx                      # React入口
│   ├── App.tsx                       # 根组件
│   ├── components/                   # 通用组件
│   │   ├── Layout/                   # 布局组件
│   │   │   ├── Sidebar.tsx           # 侧边栏
│   │   │   ├── Header.tsx            # 顶部栏
│   │   │   └── StatusBar.tsx         # 状态栏
│   │   ├── Table/                    # 表格组件
│   │   │   ├── FilterableTable.tsx   # 可筛选表格
│   │   │   └── ProgressDialog.tsx    # 进度对话框
│   │   └── Form/                     # 表单组件
│   │       └── VCenterForm.tsx       # vCenter表单
│   ├── pages/                        # 页面组件
│   │   ├── VCenterManager/           # vCenter管理
│   │   │   └── index.tsx
│   │   ├── HostInspect/              # ESXi主机巡检
│   │   │   └── index.tsx
│   │   ├── VMInspect/                # 虚拟机巡检
│   │   │   └── index.tsx
│   │   ├── BatchOperations/          # 批量操作
│   │   │   └── index.tsx
│   │   ├── VMClone/                  # 虚拟机克隆
│   │   │   └── index.tsx
│   │   ├── CertManager/              # 证书管理
│   │   │   └── index.tsx
│   │   ├── ScheduledTasks/           # 定时任务
│   │   │   └── index.tsx
│   │   └── InfoQuery/                # 信息查询
│   │       └── index.tsx
│   ├── services/                     # API服务层
│   │   ├── vcenter.ts                # vCenter相关API
│   │   ├── host.ts                   # 主机相关API
│   │   ├── vm.ts                     # 虚拟机相关API
│   │   └── batch.ts                  # 批量操作API
│   ├── stores/                       # 状态管理
│   │   ├── vcenterStore.ts
│   │   └── appStore.ts
│   ├── types/                        # TypeScript类型
│   │   └── index.ts
│   └── utils/                        # 工具函数
│       └── index.ts
├── python-core/                      # Python核心逻辑(软链接或复制)
│   ├── src/
│   │   ├── core/
│   │   └── db/
│   └── requirements.txt
├── public/                           # 静态资源
│   └── icon.ico                      # 应用图标
├── package.json
├── tsconfig.json
├── vite.config.ts
├── electron-builder.yml              # 打包配置
└── README.md
```

---

## 4. UI设计规范

### 4.1 设计风格
- **设计系统**: Material Design 3
- **UI库**: MUI (Material UI) v5
- **主题**: 支持亮色/暗色主题切换
- **配色方案**: 
  - 主色: #1976D2 (蓝色)
  - 辅助色: #FF9800 (橙色)
  - 成功: #4CAF50 (绿色)
  - 警告: #FF9800 (橙色)
  - 错误: #F44336 (红色)

### 4.2 布局设计

#### 主布局
```
┌────────────────────────────────────────────────────────────┐
│  Logo  VCenter管理巡检工具 v2.0              [设置] [帮助] │
├────────┬───────────────────────────────────────────────────┤
│        │  面包屑导航 > 当前页面                            │
│  侧    ├───────────────────────────────────────────────────┤
│  边    │                                                   │
│  栏    │              主内容区域                            │
│        │                                                   │
│  ┌──┐  │  ┌─────────────────────────────────────────────┐ │
│  │VC│  │  │                                             │ │
│  ├──┤  │  │         (表格/表单/图表/操作区)              │ │
│  │ES│  │  │                                             │ │
│  ├──┤  │  │                                             │ │
│  │VM│  │  └─────────────────────────────────────────────┘ │
│  ├──┤  │  ┌─────────────────────────────────────────────┐ │
│  │批│  │  │  状态栏: 连接状态 | 任务进度 | 版本信息      │ │
│  │量│  │  └─────────────────────────────────────────────┘ │
│  ├──┤  │                                                  │
│  │克│  │                                                  │
│  │隆│  │                                                  │
│  └──┘  │                                                  │
└────────┴───────────────────────────────────────────────────┘
```

#### 侧边栏菜单项
```
┌─────────────────┐
│ 🔧 vCenter管理  │
├─────────────────┤
│ 🖥️ ESXi主机巡检 │
├─────────────────┤
│ 💻 虚拟机巡检   │
├─────────────────┤
│ 📦 批量操作     │
├─────────────────┤
│ 📋 虚拟机克隆   │
├─────────────────┤
│ 🔐 证书管理     │
├─────────────────┤
│ ⏰ 定时任务     │
├─────────────────┤
│ 🔍 信息查询     │
└─────────────────┘
```

---

## 5. 核心页面设计

### 5.1 vCenter管理页面

**功能：**
- 添加/编辑/删除vCenter连接
- 测试连接有效性
- 显示SSL证书过期时间
- 显示root密码配置状态

**表格列：**
| 列名 | 宽度 | 说明 |
|------|------|------|
| ☐ | 40px | 选择框 |
| IP地址 | 150px | vCenter服务器IP |
| 区域 | 120px | 自定义区域标识 |
| 用户名 | 120px | 登录用户名 |
| SSL证书过期 | 130px | 证书过期日期 |
| root密码 | 100px | 已配置/未配置 |
| 备注 | 150px | 备注信息 |
| 操作 | 100px | 编辑/删除/测试 |

**操作按钮：**
- 添加vCenter
- 批量删除
- 测试连接
- 刷新

---

### 5.2 ESXi主机巡检页面

**功能：**
- 选择vCenter进行巡检
- 一键巡检所有vCenter
- 导出Excel报告
- iSCSI信息导出
- 端口组信息导出
- 本地硬盘巡检
- 存储巡检

**表格列：**
| 列名 | 宽度 | 说明 |
|------|------|------|
| vCenter | 130px | 所属vCenter |
| 主机名 | 200px | ESXi主机名称 |
| 集群 | 140px | 所属集群 |
| CPU使用率 | 90px | 当前CPU使用率 |
| 内存使用率 | 90px | 当前内存使用率 |
| 证书是否即将过期 | 140px | 是/否 |

**过滤器：**
- vCenter下拉框
- 集群下拉框
- 证书状态下拉框
- 搜索框

**右键菜单：**
- iSCSI挂载
- ESXi证书续订
- 开启SSH
- 配置NTP
- 修改root密码

---

### 5.3 虚拟机巡检页面

**功能：**
- 选择vCenter进行巡检
- 一键巡检所有vCenter
- 导出Excel报告

**表格列：**
| 列名 | 宽度 | 说明 |
|------|------|------|
| vCenter | 130px | 所属vCenter |
| 虚拟机名 | 220px | 虚拟机名称 |
| 集群 | 150px | 所属集群 |
| 主机 | 170px | 所在ESXi主机 |
| 存储 | 270px | 关联的数据存储 |
| 是否受NSX纳管 | 120px | NSX网络管理状态 |

**右键菜单：**
- 虚拟机迁移
- 添加网络适配器
- 修改备注
- 批量重命名
- 添加硬盘
- CPU内存扩容

---

### 5.4 批量操作页面

**功能：**
- 选择操作类型
- 下载Excel模板
- 上传填写好的Excel
- 执行批量操作
- 显示执行结果

**操作类型：**
- 添加iSCSI
- 虚拟机迁移
- 修改备注
- 批量重命名
- 创建分布式交换机
- ESXi证书续订
- 开启SSH
- 配置NTP
- 添加硬盘
- CPU内存扩容

**结果展示：**
- 序号
- 状态(成功/失败)
- 详情
- 进度条

---

### 5.5 虚拟机克隆页面

**功能：**
- 上传克隆配置Excel
- 执行克隆操作
- 显示克隆进度

**Excel模板字段：**
| 字段 | 必填 | 说明 |
|-----|-----|------|
| VC | 是 | vCenter IP地址 |
| 主机名称 | 是 | 目标ESXi主机 |
| 存储名称 | 是 | 目标数据存储 |
| 文件夹名称 | 选填 | 目标文件夹 |
| 模板名称 | 是 | 源模板名称 |
| 自定义规范名称 | 选填 | 自定义规范 |
| 虚拟机名称 | 是 | 新虚拟机名称 |
| 主机名 | 是 | 虚拟机hostname |
| CPU数量 | 选填 | CPU核数 |
| 内存大小 | 选填 | 内存GB |
| 端口组 | 选填 | 网络端口组 |
| IP地址 | 选填 | 静态IP |
| 子网掩码 | 选填 | 默认255.255.255.0 |
| 网关 | 选填 | 网关地址 |
| DNS1 | 选填 | 主DNS |
| DNS2 | 选填 | 备DNS |
| 硬盘 | 选填 | 硬盘大小(GB) |
| 备注 | 选填 | 备注信息 |

---

### 5.6 证书管理页面

**功能：**
- 选择vCenter查询VMCA证书
- 一键续订VMCA证书
- 显示证书详细信息

**表格列：**
| 列名 | 宽度 | 说明 |
|------|------|------|
| vCenter | 180px | vCenter地址 |
| 证书类型 | 300px | 证书类型 |
| 创建时间 | 180px | 证书创建时间 |
| 过期时间 | 180px | 证书过期时间 |
| 离过期还剩余(天) | 140px | 剩余天数 |

**颜色标识：**
- 红色: 已过期
- 橙色: 即将过期(30天内)
- 绿色: 正常

---

### 5.7 定时任务页面

**功能：**
- 管理定时巡检任务
- 管理定时开关机任务
- 立即执行任务
- 编辑/删除任务

**任务类型：**
- ESXi巡检
- 虚拟机巡检
- 存储巡检
- 存储巡检-跳过不可访问存储

**调度方式：**
- 每天
- 每周
- 仅一次

---

### 5.8 信息查询页面

**功能：**
- 智能查询主机和虚拟机信息
- 支持多种查询条件
- 高亮显示查询结果

**支持的查询条件：**
- 虚拟机IP地址
- 虚拟机名称
- ESXi主机名
- ESXi IP

---

## 6. 前后端通信设计

### 6.1 IPC通信协议

```typescript
// 类型定义
interface PythonRequest {
  action: string;
  params: Record<string, any>;
}

interface PythonResponse {
  success: boolean;
  data?: any;
  error?: string;
}

// 渲染进程调用示例
const result = await window.electronAPI.executePython({
  action: 'host_inspect',
  params: { vc_ip: '192.168.1.1' }
});
```

### 6.2 API映射

| 前端Action | Python模块 | 函数 |
|-----------|-----------|------|
| vcenter.list | database.py | get_vcenters() |
| vcenter.add | database.py | add_vcenter() |
| vcenter.test | vcenter_connector.py | test_connection() |
| host.inspect | host_collector.py | collect_all_hosts() |
| vm.inspect | vm_collector.py | collect_all_vms() |
| batch.iscsi | iscsi_manager.py | add_iscsi_target() |
| batch.migrate | vm_migrator.py | migrate_vm() |
| cert.query | vcenter_vmca_cert_query.py | query_vmca_certificates() |
| cert.renew | vcenter_vmca_cert_query.py | renew_vmca_certificates() |

---

## 7. 打包配置

### 7.1 electron-builder.yml

```yaml
appId: com.vmware.manager
productName: vm运维工具
copyright: Copyright © 2026

directories:
  output: dist-electron

files:
  - dist/**
  - electron/**/*
  - python-core/**/*
  - !python-core/__pycache__/**
  - !python-core/**/*.pyc

win:
  target:
    - target: nsis
      arch:
        - x64
  icon: public/icon.ico

nsis:
  oneClick: false
  allowToChangeInstallationDirectory: true
  createDesktopShortcut: true
  createStartMenuShortcut: true

extraResources:
  - from: python-core
    to: python-core
```

### 7.2 打包命令

```bash
# 开发模式
npm run dev

# 构建前端
npm run build

# 打包exe
npm run build:electron
```

---

## 8. 开发计划

### 8.1 阶段划分

| 阶段 | 内容 | 预计时间 |
|------|------|----------|
| 第一阶段 | 项目初始化、基础架构搭建 | 2天 |
| 第二阶段 | vCenter管理、ESXi巡检页面 | 3天 |
| 第三阶段 | 虚拟机巡检、批量操作页面 | 3天 |
| 第四阶段 | 虚拟机克隆、证书管理页面 | 2天 |
| 第五阶段 | 定时任务、信息查询页面 | 2天 |
| 第六阶段 | 测试、优化、打包 | 2天 |
| **总计** | | **14天** |

### 8.2 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Python子进程性能 | 大量数据时可能卡顿 | 异步处理、进度反馈 |
| 打包体积过大 | 下载和安装慢 | 优化依赖、考虑按需加载 |
| 跨平台兼容性 | macOS/Linux可能有问题 | 优先保证Windows |

---

## 9. 验收标准

### 9.1 功能验收
- [ ] 所有9个功能模块正常工作
- [ ] Python核心逻辑正确调用
- [ ] 数据展示正确
- [ ] 导出功能正常

### 9.2 性能验收
- [ ] 页面加载时间 < 2秒
- [ ] 巡检100台主机 < 30秒
- [ ] 批量操作响应及时

### 9.3 体验验收
- [ ] 界面美观，符合Material Design规范
- [ ] 操作流畅，无明显卡顿
- [ ] 错误提示友好

---

## 10. 附录

### 10.1 依赖清单

**前端依赖：**
```json
{
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "@mui/material": "^5.15.0",
    "@mui/icons-material": "^5.15.0",
    "@emotion/react": "^11.11.0",
    "@emotion/styled": "^11.11.0",
    "zustand": "^4.4.0",
    "recharts": "^2.10.0"
  },
  "devDependencies": {
    "typescript": "^5.3.0",
    "vite": "^5.0.0",
    "electron": "^28.0.0",
    "electron-builder": "^24.0.0"
  }
}
```

**Python依赖（复用现有）：**
- pyvmomi>=7.0
- openpyxl>=3.0
- pandas>=1.3
- cryptography>=41.0
- paramiko>=3.4
