# VMware Operations Tool

Windows desktop operations tool for VMware vCenter and ESXi environments.

## Features

- vCenter connection management
- ESXi host and virtual machine inspection
- Storage, port group, iSCSI, local disk, and host NIC inspection
- Excel batch operations for common VM and ESXi tasks
- VM migration, cloning, resize, disk, and network operations
- Certificate queries and scheduled inspection tasks
- Tkinter desktop UI with a Windows application icon

## Requirements

- Python 3.10 or newer
- VMware vCenter access

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

The local vCenter database is created under `src/db/vcenter.db` and is intentionally ignored by Git because it contains connection credentials and runtime data.

## Build Windows EXE

```bash
pyinstaller --clean --noconfirm setup.spec
```

The generated executable is written to `dist/`.

## Project Layout

- `src/core/`: VMware collection and operations
- `src/ui/`: Tkinter desktop pages
- `src/db/`: SQLite persistence layer
- `templates/`: Excel batch-operation templates
- `vCert-6.1.1-20260401/`: certificate management dependency
- `assets/`: application icon sources
- `tests/`: automated tests
