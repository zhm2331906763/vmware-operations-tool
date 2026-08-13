from pyVmomi import vim
from pyVim.task import WaitForTask


class VMCloner:
    def __init__(self, connector):
        self.connector = connector
    
    def clone_vm(self, config):
        """克隆虚拟机"""
        try:
            template_vm = self.connector.get_vm_by_name(config['template_name'])
            if not template_vm:
                return False, f"找不到模板虚拟机 '{config['template_name']}'"
            
            target_host = self.connector.get_host_by_name(config['host_name'])
            if not target_host:
                return False, f"找不到主机 '{config['host_name']}'"
            
            datacenter = self._get_datacenter_from_host(target_host)
            if not datacenter:
                return False, "无法确定数据中心"
            
            folder = self._get_folder(config.get('folder_name', ''), datacenter)
            if not folder:
                return False, f"无法获取或创建文件夹 '{config.get('folder_name', '')}'"
            
            datastore = self._find_datastore(target_host, config['datastore_name'])
            if not datastore:
                return False, f"找不到存储 '{config['datastore_name']}'"
            
            use_host_for_relocate = target_host
            if isinstance(target_host.parent, vim.ClusterComputeResource):
                resource_pool = target_host.parent.resourcePool
                # 集群内克隆时让 vCenter 自行挑选可达主机，避免并发 clone 强绑 host 引发 HostConnectFault
                use_host_for_relocate = None
            else:
                resource_pool = target_host.resourcePool
            
            if not resource_pool:
                return False, "无法获取资源池"
            
            vmconf = vim.vm.ConfigSpec()
            
            if config.get('cpu_num') is not None:
                vmconf.numCPUs = config['cpu_num']
            if config.get('mem_num') is not None:
                vmconf.memoryMB = config['mem_num'] * 1024
            
            vmconf.guestId = template_vm.config.guestId
            vmconf.annotation = config.get('remark', '')
            vmconf.deviceChange = []
            
            has_custom_network = config.get('port_group') and config['port_group'].strip()
            
            if has_custom_network:
                template_nics = [dev for dev in template_vm.config.hardware.device 
                               if isinstance(dev, vim.vm.device.VirtualEthernetCard)]
                for nic in template_nics:
                    vmconf.deviceChange.append(vim.vm.device.VirtualDeviceSpec(
                        device=nic,
                        operation=vim.vm.device.VirtualDeviceSpec.Operation.remove
                    ))
                
                network = self._get_network(config['port_group'])
                if not network:
                    return False, f"找不到端口组 '{config['port_group']}'"
                
                if hasattr(network, 'config') and hasattr(network.config, 'distributedVirtualSwitch'):
                    port_conn = vim.dvs.PortConnection(
                        portgroupKey=network.key,
                        switchUuid=network.config.distributedVirtualSwitch.uuid
                    )
                    backing = vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(port=port_conn)
                else:
                    backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(
                        deviceName=network.name,
                        network=network
                    )
                
                new_nic = vim.vm.device.VirtualVmxnet3()
                new_nic.backing = backing
                new_nic.key = -100
                new_nic.addressType = 'generated'
                new_nic.wakeOnLanEnabled = True
                new_nic.connectable = vim.vm.device.VirtualDevice.ConnectInfo(
                    startConnected=True, allowGuestControl=True, connected=True
                )
                vmconf.deviceChange.append(vim.vm.device.VirtualDeviceSpec(
                    device=new_nic, operation=vim.vm.device.VirtualDeviceSpec.Operation.add
                ))
            
            if config.get('disk_sizes'):
                self._add_disks(vmconf, template_vm, datastore, config['disk_sizes'])
            
            customization_spec = None
            if has_custom_network:
                adapter_map = vim.vm.customization.AdapterMapping()
                ip_settings = vim.vm.customization.IPSettings()
                
                if config.get('nic_ip'):
                    ip_settings.ip = vim.vm.customization.FixedIp(ipAddress=config['nic_ip'])
                    ip_settings.subnetMask = config.get('nic_netmask', '255.255.255.0')
                    if config.get('nic_gateway'):
                        ip_settings.gateway = [config['nic_gateway']]
                else:
                    ip_settings.ip = vim.vm.customization.DhcpIpGenerator()
                
                adapter_map.adapter = ip_settings
                
                dns_servers = []
                if config.get('dns1'):
                    dns_servers.append(config['dns1'])
                if config.get('dns2'):
                    dns_servers.append(config['dns2'])
                
                customization_spec = self._build_customization_spec(
                    config.get('hostname', ''), config.get('custom_spec_name'), 
                    adapter_map, dns_servers, template_vm.config.guestId
                )
            elif config.get('hostname') or config.get('custom_spec_name'):
                adapter_map = vim.vm.customization.AdapterMapping()
                ip_settings = vim.vm.customization.IPSettings()
                ip_settings.ip = vim.vm.customization.DhcpIpGenerator()
                adapter_map.adapter = ip_settings
                
                dns_servers = []
                if config.get('dns1'):
                    dns_servers.append(config['dns1'])
                if config.get('dns2'):
                    dns_servers.append(config['dns2'])
                
                customization_spec = self._build_customization_spec(
                    config.get('hostname', ''), config.get('custom_spec_name'),
                    adapter_map, dns_servers, template_vm.config.guestId
                )
            
            clonespec = vim.vm.CloneSpec(
                powerOn=False,
                template=False,
                location=vim.vm.RelocateSpec(
                    datastore=datastore,
                    pool=resource_pool,
                    host=use_host_for_relocate,
                ),
                config=vmconf,
                customization=customization_spec
            )
            
            task = template_vm.Clone(folder=folder, name=config['vm_name'], spec=clonespec)
            WaitForTask(task)
            
            return True, "克隆成功"
        
        except Exception as e:
            return False, str(e)
    
    def _get_folder(self, folder_name, datacenter):
        if not folder_name or folder_name.strip() == '':
            return datacenter.vmFolder
        
        return self._find_or_create_folder(folder_name.strip(), datacenter.vmFolder)
    
    def _find_or_create_folder(self, folder_path, parent_folder):
        import time
        parts = folder_path.split('/')
        
        current_folder = parent_folder
        for part in parts:
            if not part or part.strip() == '':
                continue
            
            part = part.strip()
            found = False
            
            if hasattr(current_folder, 'childEntity') and current_folder.childEntity:
                for child in current_folder.childEntity:
                    if isinstance(child, vim.Folder) and child.name == part:
                        current_folder = child
                        found = True
                        break
            
            if not found:
                try:
                    current_folder = current_folder.CreateFolder(part)
                    time.sleep(0.5)
                    
                    if hasattr(current_folder, 'parent'):
                        pass
                except Exception as e:
                    if hasattr(current_folder, 'childEntity') and current_folder.childEntity:
                        for child in current_folder.childEntity:
                            if isinstance(child, vim.Folder) and child.name == part:
                                current_folder = child
                                found = True
                                break
                    if not found:
                        return None
        
        return current_folder
    
    def _get_datacenter_from_host(self, host):
        from pyVmomi import vim
        current = host
        while current:
            if isinstance(current, vim.Datacenter):
                return current
            current = getattr(current, 'parent', None)
        return None
    
    def _get_network(self, network_name):
        return self.connector.get_obj([vim.Network], network_name)
    
    def _find_datastore(self, host, datastore_name):
        for ds in host.datastore:
            if ds.name == datastore_name:
                return ds
        return self.connector.get_datastore_by_name(datastore_name)
    
    def _add_disks(self, vmconf, template_vm, datastore, disk_sizes):
        template_disks = [dev for dev in template_vm.config.hardware.device 
                         if isinstance(dev, vim.vm.device.VirtualDisk)]
        template_controllers = [dev for dev in template_vm.config.hardware.device 
                              if isinstance(dev, (vim.vm.device.VirtualSCSIController,
                                                   vim.vm.device.ParaVirtualSCSIController,
                                                   vim.vm.device.VirtualLsiLogicController,
                                                   vim.vm.device.VirtualLsiLogicSASController))]
        
        if not template_controllers:
            return
        
        scsi_controller = template_controllers[0]
        used_unit_numbers = set()
        for disk in template_disks:
            if disk.controllerKey == scsi_controller.key:
                used_unit_numbers.add(disk.unitNumber)
        
        next_unit_number = 1
        while next_unit_number in used_unit_numbers or next_unit_number == 7:
            next_unit_number += 1
        
        for disk_size_gb in disk_sizes:
            if disk_size_gb <= 0:
                continue
            
            new_disk = vim.vm.device.VirtualDisk()
            new_disk.key = -200 - len(vmconf.deviceChange)
            new_disk.controllerKey = scsi_controller.key
            new_disk.unitNumber = next_unit_number
            new_disk.capacityInKB = disk_size_gb * 1024 * 1024
            
            disk_backing = vim.vm.device.VirtualDisk.FlatVer2BackingInfo()
            disk_backing.fileName = ""
            disk_backing.datastore = datastore
            disk_backing.diskMode = "persistent"
            disk_backing.thinProvisioned = True
            new_disk.backing = disk_backing
            
            disk_spec = vim.vm.device.VirtualDeviceSpec()
            disk_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.add
            disk_spec.fileOperation = vim.vm.device.VirtualDeviceSpec.FileOperation.create
            disk_spec.device = new_disk
            vmconf.deviceChange.append(disk_spec)
            
            next_unit_number += 1
            while next_unit_number in used_unit_numbers or next_unit_number == 7:
                next_unit_number += 1
    
    def _build_customization_spec(self, hostname, custom_spec_name, adapter_map, dns_servers, guest_id):
        if not hostname:
            hostname = "vm"
        
        if custom_spec_name:
            spec_manager = self.connector.content.customizationSpecManager
            try:
                base_spec = spec_manager.GetCustomizationSpec(name=custom_spec_name).spec
                customization_spec = vim.vm.customization.Specification()
                customization_spec.identity = base_spec.identity
                customization_spec.globalIPSettings = base_spec.globalIPSettings or vim.vm.customization.GlobalIPSettings()
                customization_spec.nicSettingMap = base_spec.nicSettingMap or []
                
                if isinstance(customization_spec.identity, vim.vm.customization.Sysprep):
                    if not customization_spec.identity.userData:
                        customization_spec.identity.userData = vim.vm.customization.UserData()
                    customization_spec.identity.userData.computerName = vim.vm.customization.FixedName(name=hostname)
                elif isinstance(customization_spec.identity, vim.vm.customization.LinuxPrep):
                    customization_spec.identity.hostName = vim.vm.customization.FixedName(name=hostname)
                
                if dns_servers:
                    customization_spec.globalIPSettings.dnsServerList = dns_servers
                
                if customization_spec.nicSettingMap:
                    customization_spec.nicSettingMap[0] = adapter_map
                else:
                    customization_spec.nicSettingMap = [adapter_map]
                
                return customization_spec
            except:
                pass
        
        is_windows = 'windows' in guest_id.lower()
        
        if is_windows:
            ident = vim.vm.customization.Sysprep()
            ident.userData = vim.vm.customization.UserData()
            ident.userData.computerName = vim.vm.customization.FixedName(name=hostname)
            ident.userData.fullName = "Administrator"
            ident.userData.orgName = "Organization"
            ident.guiUnattended = vim.vm.customization.GuiUnattended()
            ident.guiUnattended.timeZone = 85
            ident.identification = vim.vm.customization.Identification()
            ident.identification.joinWorkgroup = "WORKGROUP"
        else:
            ident = vim.vm.customization.LinuxPrep(
                hostName=vim.vm.customization.FixedName(name=hostname),
                domain="localdomain"
            )
        
        global_ip = vim.vm.customization.GlobalIPSettings()
        if dns_servers:
            global_ip.dnsServerList = dns_servers
        
        return vim.vm.customization.Specification(
            identity=ident,
            globalIPSettings=global_ip,
            nicSettingMap=[adapter_map]
        )
