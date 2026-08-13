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


class VMNetworkAdapterManager:
    def __init__(self, connector):
        self.connector = connector

    def add_network_adapter(self, vm_name, portgroup_name, adapter_type='vmxnet3'):
        vm = self.connector.get_vm_by_name(vm_name)
        if not vm:
            return False, f"找不到虚拟机: {vm_name}"

        portgroup_name = (portgroup_name or '').strip()
        if not portgroup_name:
            return False, "端口组名称不能为空"

        network = self.connector.get_obj([vim.Network], portgroup_name)
        if not network:
            network = self.connector.get_obj([vim.OpaqueNetwork], portgroup_name)
        if not network:
            return False, f"找不到网络/端口组: {portgroup_name}"

        try:
            if hasattr(network, 'config') and hasattr(network.config, 'distributedVirtualSwitch'):
                port_conn = vim.dvs.PortConnection(
                    portgroupKey=network.key,
                    switchUuid=network.config.distributedVirtualSwitch.uuid,
                )
                backing = vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(port=port_conn)
            elif isinstance(network, vim.OpaqueNetwork):
                summary = getattr(network, 'summary', None)
                backing = vim.vm.device.VirtualEthernetCard.OpaqueNetworkBackingInfo()
                backing.opaqueNetworkId = getattr(summary, 'opaqueNetworkId', '') or ''
                backing.opaqueNetworkType = getattr(summary, 'opaqueNetworkType', '') or ''
            else:
                backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(
                    deviceName=network.name,
                    network=network,
                )

            adapter_class = {
                'e1000e': vim.vm.device.VirtualE1000e,
                'e1000': vim.vm.device.VirtualE1000,
                'vmxnet2': vim.vm.device.VirtualVmxnet2,
                'vmxnet3': vim.vm.device.VirtualVmxnet3,
            }.get((adapter_type or 'vmxnet3').lower(), vim.vm.device.VirtualVmxnet3)

            nic = adapter_class()
            nic.backing = backing
            nic.key = -1000
            nic.addressType = 'generated'
            nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo(
                startConnected=True,
                allowGuestControl=True,
                connected=True,
            )

            vmconf = vim.vm.ConfigSpec()
            device_spec = vim.vm.device.VirtualDeviceSpec()
            device_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.add
            device_spec.device = nic
            vmconf.deviceChange = [device_spec]

            task = vm.ReconfigVM_Task(spec=vmconf)
            WaitForTask(task)
            return True, f"已添加网络适配器: {portgroup_name}"
        except Exception as e:
            return False, str(e)
