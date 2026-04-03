from pyVmomi import vim
from pyVim.task import WaitForTask


class VMRenamer:
    def __init__(self, connector):
        self.connector = connector
    
    def rename_vm(self, vm_name, new_name):
        """重命名虚拟机"""
        try:
            vm = self.connector.get_vm_by_name(vm_name)
            if not vm:
                return False, f"找不到虚拟机 (主机名: {vm_name})"
            
            vmconf = vim.vm.ConfigSpec()
            vmconf.name = new_name
            
            task = vm.ReconfigVM_Task(spec=vmconf)
            WaitForTask(task)
            
            return True, f"重命名为 '{new_name}' 成功"
        
        except Exception as e:
            return False, str(e)
    
    def batch_rename(self, rename_configs):
        """批量重命名"""
        results = []
        for config in rename_configs:
            uuid = config.get('uuid')
            new_name = config.get('new_name')
            rule = config.get('rule', '')
            
            # 如果是前缀/后缀规则，先获取原名称
            if rule in ['prefix', 'suffix']:
                vm = self.connector.get_vm_by_uuid(uuid, instance_uuid=True)
                if vm:
                    if rule == 'prefix':
                        new_name = f"{config.get('prefix', '')}{vm.name}"
                    else:
                        new_name = f"{vm.name}{config.get('suffix', '')}"
            
            success, msg = self.rename_vm(uuid, new_name)
            results.append({
                'uuid': uuid,
                'new_name': new_name,
                'success': success,
                'message': msg
            })
        
        return results


class VMRemarkUpdater:
    def __init__(self, connector):
        self.connector = connector
    
    def update_remark(self, vm_name, remark):
        """修改虚拟机备注"""
        try:
            vm = self.connector.get_vm_by_name(vm_name)
            if not vm:
                return False, f"找不到虚拟机 (主机名: {vm_name})"
            
            vmconf = vim.vm.ConfigSpec()
            vmconf.annotation = remark
            
            task = vm.ReconfigVM_Task(spec=vmconf)
            WaitForTask(task)
            
            return True, "备注修改成功"
        
        except Exception as e:
            return False, str(e)
    
    def batch_update_remark(self, configs):
        """批量修改备注"""
        results = []
        for config in configs:
            uuid = config.get('uuid')
            remark = config.get('remark', '')
            
            success, msg = self.update_remark(uuid, remark)
            results.append({
                'uuid': uuid,
                'success': success,
                'message': msg
            })
        
        return results