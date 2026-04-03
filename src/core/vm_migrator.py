from pyVmomi import vim
from pyVim.task import WaitForTask


class VMMigrator:
    def __init__(self, connector):
        self.connector = connector
    
    def migrate_vm(self, vm_name, target_host_name=None, target_datastore_name=None):
        """迁移虚拟机 - 支持冷迁移和热迁移
        - 只填目标主机 = 只迁移计算资源
        - 只填目标存储 = 只迁移存储资源
        - 两者都填 = 迁移计算和存储
        """
        try:
            vm = self.connector.get_vm_by_name(vm_name)
            if not vm:
                return False, f"找不到虚拟机 '{vm_name}'"
            
            is_powered_on = vm.runtime.powerState == vim.VirtualMachinePowerState.poweredOn
            
            # 如果只迁移存储，需要获取当前主机
            current_host = None
            if target_datastore_name and not target_host_name:
                current_host = vm.runtime.host
                if not current_host:
                    return False, "无法获取当前主机信息"
            
            # 如果迁移计算资源
            target_host = None
            if target_host_name:
                target_host = self.connector.get_host_by_name(target_host_name)
                if not target_host:
                    return False, f"找不到目标主机 '{target_host_name}'"
                
                if isinstance(target_host.parent, vim.ClusterComputeResource):
                    resource_pool = target_host.parent.resourcePool
                else:
                    resource_pool = target_host.resourcePool
                
                if not resource_pool:
                    return False, "无法获取目标资源池"
            else:
                # 如果不迁移计算资源，使用当前资源池
                current_host_for_pool = current_host if current_host else vm.runtime.host
                if current_host_for_pool:
                    if isinstance(current_host_for_pool.parent, vim.ClusterComputeResource):
                        resource_pool = current_host_for_pool.parent.resourcePool
                    else:
                        resource_pool = current_host_for_pool.resourcePool
                else:
                    resource_pool = None
            
            # 检查是否只迁移存储
            only_storage = target_datastore_name and not target_host_name
            
            # 如果只迁移存储，用当前主机
            host_for_datastore = current_host if only_storage else target_host
            
            # 构建迁移规格
            relocate_spec = vim.vm.RelocateSpec()
            migrate_type = ""
            
            # 处理目标主机（计算资源迁移）
            if target_host_name:
                relocate_spec.host = target_host
                relocate_spec.pool = resource_pool
                migrate_type += "计算资源"
            
            # 处理目标存储（存储迁移）
            if target_datastore_name:
                search_host = host_for_datastore if host_for_datastore else vm.runtime.host
                if not search_host:
                    return False, "无法确定用于查找存储的主机"
                
                target_datastore = self._find_datastore(search_host, target_datastore_name)
                if not target_datastore:
                    return False, f"找不到目标存储 '{target_datastore_name}'"
                
                if not target_datastore.summary.accessible:
                    return False, f"目标存储 '{target_datastore_name}' 不可访问"
                
                relocate_spec.datastore = target_datastore
                
                # 磁盘定位器 - 用于迁移存储时指定每个磁盘的目标位置
                disk_locators = []
                for device in vm.config.hardware.device:
                    if isinstance(device, vim.vm.device.VirtualDisk):
                        disk_locator = vim.vm.RelocateSpec.DiskLocator()
                        disk_locator.diskId = device.key
                        disk_locator.datastore = target_datastore
                        disk_locators.append(disk_locator)
                
                if disk_locators:
                    relocate_spec.disk = disk_locators
                
                if migrate_type:
                    migrate_type += "+"
                migrate_type += "存储"
            
            if not migrate_type:
                return False, "未指定迁移目标"
            
            # 执行迁移
            task = vm.RelocateVM_Task(
                spec=relocate_spec,
                priority=vim.VirtualMachine.MovePriority.defaultPriority
            )
            WaitForTask(task)
            
            return True, f"{migrate_type}迁移成功"
        
        except Exception as e:
            return False, str(e)
    
    def _find_datastore(self, host, datastore_name):
        # 先在主机存储中查找
        for ds in host.datastore:
            if ds.name == datastore_name:
                return ds
        # 全局查找
        return self.connector.get_datastore_by_name(datastore_name)