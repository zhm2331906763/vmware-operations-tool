# -*- mode: python ; coding: utf-8 -*-
import os
import glob

block_cipher = None

vcert_root = 'vCert-6.1.1-20260401'
vcert_datas = [
    (f'{vcert_root}/vCert.py', vcert_root),
    (f'{vcert_root}/lib/*.py', f'{vcert_root}/lib'),
    (f'{vcert_root}/operation/*.py', f'{vcert_root}/operation'),
]

# 递归收集config下全部yaml，并保持原始目录结构
for yaml_file in glob.glob(f'{vcert_root}/config/**/*.yaml', recursive=True):
    rel_dir = os.path.dirname(os.path.relpath(yaml_file, vcert_root))
    dest_dir = os.path.join(vcert_root, rel_dir).replace('\\', '/')
    vcert_datas.append((yaml_file.replace('\\', '/'), dest_dir))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates/*.xlsx', 'templates'),
        ('src/db/vcenter.db', 'src/db'),
        ('assets/vm_ops_icon.ico', 'assets'),
    ] + vcert_datas,
    hiddenimports=[
        'pyVmomi',
        'pyVim',
        'openpyxl',
        'pandas',
        'cryptography',
        'paramiko',
        'src.ui.host_inspect',
        'src.ui.vm_inspect',
        'src.ui.vc_manager',
        'src.ui.vcenter_cert',
        'src.ui.batch_operations',
        'src.ui.clone',
        'src.ui.theme',
        'src.ui.enhanced_widgets',
        'src.db.database',
        'src.core.excel_formatter',
        'src.core.storage_inspector',
        'src.core.vcenter_connector',
        'src.core.host_collector',
        'src.core.vm_collector',
        'src.core.vm_migrator',
        'src.core.vm_cloner',
        'src.core.vm_operations',
        'src.core.iscsi_manager',
        'src.core.iscsi_exporter',
        'src.core.dvswitch_manager',
        'src.core.portgroup_exporter',
        'src.core.concurrent_config',
        'src.core.scheduler',
        'src.ui.schedule',
        'src.ui.information_query',
        'src.core.local_disk_inspector',
        'src.core.host_nic_exporter',
        'src.core.esxi_host_manager',
        'src.core.esxi_root_password_manager',
        'src.core.vm_disk_manager',
        'src.core.vm_resize_manager',
        'src.core.vcenter_vmca_cert_query',
        'src.core.power_models',
        'src.core.power_task_store',
        'src.core.power_scheduler',
        'src.core.inspection_query',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch',
        'torchvision',
        'scipy',
        'matplotlib',
        'IPython',
        'jedi',
        'PIL',
        'cv2',
        'tensorflow',
        'sklearn',
        'seaborn',
        'plotly',
        'sympy',
        'statsmodels',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='vm运维工具_20260813',
    icon='assets/vm_ops_icon.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
