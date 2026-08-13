from pyVmomi import vim
from pyVim.task import WaitForTask


class VMResizeManager:
    def __init__(self, connector):
        self.connector = connector

    def resize_vm_resources(self, vm_name, cpu_count=None, memory_gb=None):
        try:
            vm = self.connector.get_vm_by_name(vm_name)
            if not vm:
                return False, f"找不到虚拟机 (主机名: {vm_name})"

            if cpu_count is None and memory_gb is None:
                return False, "CPU和内存均为空，无需调整"

            vmconf = vim.vm.ConfigSpec()

            if cpu_count is not None:
                vmconf.numCPUs = int(cpu_count)

            if memory_gb is not None:
                vmconf.memoryMB = int(memory_gb) * 1024

            task = vm.ReconfigVM_Task(spec=vmconf)
            WaitForTask(task)

            parts = []
            if cpu_count is not None:
                parts.append(f"CPU={cpu_count}")
            if memory_gb is not None:
                parts.append(f"内存={memory_gb}GB")
            return True, f"调整成功 ({', '.join(parts)})"
        except Exception as e:
            err_msg = str(e)
            if self._is_hot_add_error(err_msg):
                return False, "调整失败：CPU或内存热添加未开启，请关机后重试或先启用热添加功能"
            return False, err_msg

    def _is_hot_add_error(self, message):
        if not message:
            return False
        msg = message.lower()
        keywords = [
            "hot", "hotadd", "hot-add", "hot add",
            "cpu hot plug", "memory hot add",
            "not supported while powered on",
            "device or operation not supported",
            "powered on"
        ]
        return any(k in msg for k in keywords)

