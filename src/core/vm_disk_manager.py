import ssl
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
from pyVim.task import WaitForTask


class VMDiskManager:
    def __init__(self, connector):
        self.connector = connector

    def _get_vm_by_name(self, vm_name):
        content = self.connector.content
        vm_view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True
        )
        for vm in vm_view.view:
            if vm.name == vm_name:
                vm_view.Destroy()
                return vm
        vm_view.Destroy()
        return None

    def _get_datastore_from_vm(self, vm):
        for device in vm.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualDisk) and hasattr(device.backing, 'datastore'):
                if device.backing.datastore:
                    return device.backing.datastore
        return None

    def _get_vm_disk_info(self, vm):
        unit_number = 0
        controller = None
        last_datastore = None
        disk_count = 0

        for device in vm.config.hardware.device:
            if hasattr(device.backing, 'fileName'):
                disk_count += 1
                unit_number = int(device.unitNumber) + 1
                if unit_number == 7:
                    unit_number += 1
                if unit_number >= 16:
                    return None, None, None, None

                if hasattr(device.backing, 'datastore'):
                    last_datastore = device.backing.datastore

            if isinstance(device, vim.vm.device.VirtualSCSIController):
                controller = device

        return unit_number, controller, last_datastore, disk_count

    def add_disk(self, vm_name, disk_size_gb, datastore_name=None):
        try:
            vm = self._get_vm_by_name(vm_name)
            if not vm:
                return False, f"虚拟机 {vm_name} 未找到"

            content = self.connector.content
            ds_view = content.viewManager.CreateContainerView(
                content.rootFolder, [vim.Datastore], True
            )
            ds_map = {ds.name: ds for ds in ds_view.view}
            ds_view.Destroy()

            target_datastore = None
            target_datastore_name = None

            unit_number, controller, last_ds, disk_count = self._get_vm_disk_info(vm)

            if controller is None:
                return False, "未找到SCSI控制器"

            if unit_number is None:
                return False, "不支持超过15个硬盘"

            if datastore_name and datastore_name.strip():
                if datastore_name.strip() not in ds_map:
                    return False, f"数据存储 {datastore_name} 未找到"
                target_datastore = ds_map[datastore_name.strip()]
                target_datastore_name = datastore_name.strip()
                ds_display = target_datastore_name
            else:
                if not last_ds:
                    return False, "无法获取虚拟机现有硬盘的存储位置"
                target_datastore = last_ds
                target_datastore_name = last_ds.name
                ds_display = last_ds.name

            spec = vim.vm.ConfigSpec()
            dev_changes = []

            new_disk_kb = int(disk_size_gb) * 1024 * 1024

            disk_spec = vim.vm.device.VirtualDeviceSpec()
            disk_spec.fileOperation = "create"
            disk_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.add
            disk_spec.device = vim.vm.device.VirtualDisk()

            disk_spec.device.backing = vim.vm.device.VirtualDisk.FlatVer2BackingInfo()
            disk_spec.device.backing.fileName = f"[{target_datastore_name}]"
            disk_spec.device.backing.datastore = target_datastore
            disk_spec.device.backing.thinProvisioned = True
            disk_spec.device.backing.diskMode = 'persistent'

            disk_spec.device.unitNumber = unit_number
            disk_spec.device.capacityInKB = new_disk_kb
            disk_spec.device.controllerKey = controller.key

            dev_changes.append(disk_spec)
            spec.deviceChange = dev_changes

            WaitForTask(vm.ReconfigVM_Task(spec=spec))

            return True, f"已添加 {disk_size_gb}GB 硬盘 (存储: {ds_display})"

        except Exception as e:
            return False, str(e)

    def add_multiple_disks(self, vm_name, disk_sizes, datastore_name=None):
        results = []
        for size in disk_sizes:
            ok, msg = self.add_disk(vm_name, size, datastore_name)
            results.append((size, ok, msg))
        return results