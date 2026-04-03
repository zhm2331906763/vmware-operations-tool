from pyVmomi import vim
from pyVim.task import WaitForTask
from collections import defaultdict


class DVSwitchManager:
    def __init__(self, connector):
        self.connector = connector
        self.content = connector.si.content
    
    def create_dvswitch(self, datacenter_name, switch_name, num_uplinks=4):
        try:
            datacenter = self._get_datacenter(datacenter_name)
            if not datacenter:
                return False, f"找不到数据中心: {datacenter_name}"
            
            existing_vds = self._get_all_dvswitches()
            for existing in existing_vds:
                if existing.name == switch_name:
                    return True, f"分布式交换机 {switch_name} 已存在"
            
            network_folder = datacenter.networkFolder
            
            print(f"正在创建分布式交换机: {switch_name} ...")
            
            create_spec = vim.DVSCreateSpec()
            create_spec.configSpec = vim.VMwareDVSConfigSpec()
            create_spec.configSpec.name = switch_name
            create_spec.configSpec.numStandalonePorts = 0
            
            uplink_port_names = ['Uplink 1', 'Uplink 2', 'Uplink 3', 'Uplink 4'][:num_uplinks]
            create_spec.configSpec.uplinkPortPolicy = vim.DVSNameArrayUplinkPortPolicy()
            create_spec.configSpec.uplinkPortPolicy.uplinkPortName = uplink_port_names
            
            task = network_folder.CreateDVS_Task(spec=create_spec)
            WaitForTask(task)
            
            return True, f"分布式交换机 {switch_name} 创建成功"
            
        except vim.fault.DuplicateName:
            return True, f"分布式交换机 {switch_name} 已存在"
        except Exception as e:
            return False, str(e)
    
    def create_portgroup(self, switch_name, portgroup_name, vlan_id=0):
        try:
            dvs = self._get_dvswitch(switch_name)
            if not dvs:
                return False, f"找不到分布式交换机: {switch_name}"
            
            if hasattr(dvs, 'portgroup'):
                for pg in dvs.portgroup:
                    if pg.name == portgroup_name:
                        return True, f"端口组 {portgroup_name} 已存在"
            
            vlan_display = f"VLAN {vlan_id}" if vlan_id else "VLAN 0 (未设置)"
            print(f"正在创建端口组: {portgroup_name} -> {switch_name} ({vlan_display}) ...")
            
            pg_spec = vim.DVPortgroupConfigSpec()
            pg_spec.name = portgroup_name
            pg_spec.type = 'earlyBinding'
            
            default_port_config = vim.VMwareDVSPortSetting()
            vlan_config = vim.VmwareDistributedVirtualSwitchVlanIdSpec()
            vlan_config.vlanId = vlan_id if vlan_id else 0
            vlan_config.inherited = False
            default_port_config.vlan = vlan_config
            pg_spec.defaultPortConfig = default_port_config
            
            task = dvs.AddDVPortgroup_Task(spec=[pg_spec])
            WaitForTask(task)
            
            return True, f"端口组 {portgroup_name} 创建成功"
            
        except vim.fault.DuplicateName:
            return True, f"端口组 {portgroup_name} 已存在"
        except Exception as e:
            return False, str(e)
    
    def _get_datacenter(self, name):
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.Datacenter], True
        )
        for dc in container.view:
            if dc.name == name:
                container.Destroy()
                return dc
        container.Destroy()
        return None
    
    def _get_all_dvswitches(self):
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.DistributedVirtualSwitch], True
        )
        result = list(container.view)
        container.Destroy()
        return result
    
    def _get_dvswitch(self, name):
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.DistributedVirtualSwitch], True
        )
        for dvs in container.view:
            if dvs.name == name:
                container.Destroy()
                return dvs
        container.Destroy()
        return None