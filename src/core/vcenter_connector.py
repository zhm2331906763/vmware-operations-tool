import ssl
import socket
import datetime
import concurrent.futures
from pyVim.connect import SmartConnect, Disconnect
from pyVim.task import WaitForTask
from pyVmomi import vim
from pyVmomi import vmodl
from cryptography import x509
from cryptography.hazmat.backends import default_backend


class VCenterConnector:
    def __init__(self, ip, user, password):
        self.ip = ip
        self.user = user
        self.password = password
        self.si = None
        self.content = None
    
    def connect(self):
        context = ssl._create_unverified_context()
        try:
            self.si = SmartConnect(
                host=self.ip,
                user=self.user,
                pwd=self.password,
                port=443,
                sslContext=context
            )
            self.content = self.si.content
            return True, "连接成功"
        except Exception as e:
            return False, str(e)
    
    def disconnect(self):
        if self.si:
            try:
                Disconnect(self.si)
            except:
                pass
            self.si = None
            self.content = None
    
    def test_connection(self):
        success, msg = self.connect()
        if success:
            self.disconnect()
        return success, msg
    
    def is_connected(self):
        return self.si is not None and self.content is not None
    
    def get_all_hosts(self):
        if not self.is_connected():
            return []
        
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.HostSystem], True
        )
        
        properties = [
            'name', 'runtime.powerState', 'overallStatus', 'config.product',
            'config.network', 'config.storageDevice', 'hardware.systemInfo',
            'hardware.biosInfo', 'hardware.cpuInfo', 'hardware.cpuPkg',
            'hardware.memorySize', 'summary.quickStats'
        ]
        
        filter_spec = self._create_property_filter_spec(container, vim.HostSystem, properties)
        pc = self.content.propertyCollector
        result = pc.RetrieveProperties(specSet=[filter_spec])
        container.Destroy()
        
        return result
    
    def get_all_vms(self):
        if not self.is_connected():
            return []
        
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )
        
        properties = [
            'name', 'runtime.host', 'runtime.powerState', 'runtime.bootTime',
            'guest.ipAddress', 'guest.net', 'guest.toolsStatus', 'guest.guestFullName',
            'config.hardware.memoryMB', 'config.hardware.numCPU', 'config.hardware.device',
            'config.instanceUuid', 'config.annotation', 'config.modified', 'config.guestFullName',
            'config.cpuHotAddEnabled', 'config.memoryHotAddEnabled',
            'datastore', 'summary.storage.committed', 'parent'
        ]
        
        filter_spec = self._create_property_filter_spec(container, vim.VirtualMachine, properties)
        pc = self.content.propertyCollector
        result = pc.RetrieveProperties(specSet=[filter_spec])
        container.Destroy()
        
        return result
    
    def _create_property_filter_spec(self, container, vim_type, properties):
        obj_spec = vmodl.query.PropertyCollector.ObjectSpec()
        obj_spec.obj = container
        obj_spec.selectSet = [
            vmodl.query.PropertyCollector.TraversalSpec(
                name='traverseEntities',
                path='view',
                skip=False,
                type=vim.view.ContainerView
            )
        ]
        
        prop_spec = vmodl.query.PropertyCollector.PropertySpec()
        prop_spec.type = vim_type
        prop_spec.pathSet = properties
        
        filter_spec = vmodl.query.PropertyCollector.FilterSpec()
        filter_spec.objectSet = [obj_spec]
        filter_spec.propSet = [prop_spec]
        return filter_spec
    
    def build_cluster_host_map(self):
        cluster_map = {}
        try:
            cluster_container = self.content.viewManager.CreateContainerView(
                self.content.rootFolder, [vim.ClusterComputeResource], True
            )
            all_clusters = cluster_container.view
            cluster_container.Destroy()
            
            for cluster in all_clusters:
                cluster_name = cluster.name
                if hasattr(cluster, 'host') and cluster.host:
                    for host in cluster.host:
                        cluster_map[host._moId] = cluster_name
            return cluster_map
        except:
            return {}
    
    def build_datacenter_map(self):
        datacenter_map = {}
        try:
            dc_container = self.content.viewManager.CreateContainerView(
                self.content.rootFolder, [vim.Datacenter], True
            )
            all_dcs = dc_container.view
            dc_container.Destroy()
            
            for dc in all_dcs:
                dc_name = dc.name
                if hasattr(dc, 'hostFolder') and dc.hostFolder:
                    try:
                        clusters = dc.hostFolder.childEntity
                        for cluster in clusters:
                            if hasattr(cluster, 'name'):
                                if dc_name not in datacenter_map:
                                    datacenter_map[dc_name] = set()
                                datacenter_map[dc_name].add(cluster.name)
                    except:
                        pass
            for k, v in datacenter_map.items():
                datacenter_map[k] = list(v)
            return datacenter_map
        except:
            return {}
    
    def build_network_cache(self):
        network_cache = {}
        try:
            container = self.content.viewManager.CreateContainerView(
                self.content.rootFolder, [vim.Network], True
            )
            all_networks = container.view
            container.Destroy()
            
            for net in all_networks:
                if isinstance(net, vim.dvs.DistributedVirtualPortgroup):
                    pg_key = net.key
                    pg_name = net.name
                    network_cache[pg_key] = pg_name
                    network_cache[pg_name] = pg_name
                else:
                    pg_name = net.name
                    network_cache[pg_name] = pg_name
            return network_cache
        except:
            return {}
    
    def build_datastore_cache(self):
        """构建存储缓存 - 名称到MOID的映射"""
        datastore_map = {}
        try:
            container = self.content.viewManager.CreateContainerView(
                self.content.rootFolder, [vim.Datastore], True
            )
            all_datastores = container.view
            container.Destroy()
            
            for ds in all_datastores:
                datastore_map[ds.name] = ds
                datastore_map[ds._moId] = ds
            return datastore_map
        except:
            return {}
    
    def get_vm_by_uuid(self, uuid, instance_uuid=True):
        if not self.is_connected():
            return None
        return self.content.searchIndex.FindByUuid(
            datacenter=None, uuid=uuid, vmSearch=True, instanceUuid=instance_uuid
        )
    
    def get_vm_by_name(self, vm_name):
        if not self.is_connected():
            return None
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )
        for vm in container.view:
            if vm.name == vm_name:
                container.Destroy()
                return vm
        container.Destroy()
        return None
    
    def get_host_by_name(self, host_name):
        if not self.is_connected():
            return None
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.HostSystem], True
        )
        for host in container.view:
            if host.name == host_name:
                container.Destroy()
                return host
        container.Destroy()
        return None
    
    def get_datastore_by_name(self, datastore_name):
        return self.get_obj([vim.Datastore], datastore_name)
    
    def get_obj(self, vimtype, name=None):
        """获取对象函数"""
        container = self.content.viewManager.CreateContainerView(self.content.rootFolder, vimtype, True)
        try:
            if name:
                return next((item for item in container.view if item.name == name), None)
            return list(container.view)
        finally:
            container.Destroy()
    
    def get_all_datastores(self):
        if not self.is_connected():
            return []
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.Datastore], True
        )
        result = [ds.name for ds in container.view]
        container.Destroy()
        return result
    
    def get_all_networks(self):
        if not self.is_connected():
            return []
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.Network], True
        )
        result = [net.name for net in container.view]
        container.Destroy()
        return result
    
    def get_all_folders(self):
        if not self.is_connected():
            return []
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.Folder], True
        )
        result = [folder.name for folder in container.view]
        container.Destroy()
        return result
    
    def get_all_templates(self):
        if not self.is_connected():
            return []
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )
        templates = [vm.name for vm in container.view if vm.config.template]
        container.Destroy()
        return templates
    
    def get_customization_specs(self):
        if not self.is_connected():
            return []
        try:
            spec_manager = self.content.customizationSpecManager
            return [spec.name for spec in spec_manager.info]
        except:
            return []

    def find_vm_by_uuid(self, uuid):
        return self.get_vm_by_uuid(uuid, instance_uuid=True)

    def get_vm_by_ip(self, ip_address):
        if not self.is_connected():
            return None
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim.VirtualMachine], True
        )
        try:
            for vm in container.view:
                guest = getattr(vm, "guest", None)
                summary_guest = getattr(getattr(vm, "summary", None), "guest", None)
                if ip_address in {getattr(guest, "ipAddress", ""), getattr(summary_guest, "ipAddress", "")}:
                    return vm
            return None
        finally:
            container.Destroy()

    def power_on_vm(self, vm_obj):
        if not vm_obj:
            return False, "未找到虚拟机"
        try:
            if getattr(vm_obj.runtime, "powerState", None) == vim.VirtualMachinePowerState.poweredOn:
                return True, "虚拟机已开机"
            task = vm_obj.PowerOnVM_Task()
            WaitForTask(task)
            return True, "虚拟机开机成功"
        except Exception as e:
            return False, str(e)

    def power_off_vm(self, vm_obj):
        if not vm_obj:
            return False, "未找到虚拟机"
        try:
            if getattr(vm_obj.runtime, "powerState", None) == vim.VirtualMachinePowerState.poweredOff:
                return True, "虚拟机已关机"
            task = vm_obj.PowerOffVM_Task()
            WaitForTask(task)
            return True, "虚拟机关机成功"
        except Exception as e:
            return False, str(e)

    def update_vm_annotation(self, vm_obj, annotation):
        from pyVmomi import vim
        from pyVim.task import WaitForTask
        try:
            vmconf = vim.vm.ConfigSpec()
            vmconf.annotation = annotation
            task = vm_obj.ReconfigVM_Task(spec=vmconf)
            WaitForTask(task)
            return True, "备注修改成功"
        except Exception as e:
            return False, str(e)

    def rename_vm(self, vm_obj, new_name):
        from pyVmomi import vim
        from pyVim.task import WaitForTask
        try:
            vmconf = vim.vm.ConfigSpec()
            vmconf.name = new_name
            task = vm_obj.ReconfigVM_Task(spec=vmconf)
            WaitForTask(task)
            return True, f"重命名为 '{new_name}' 成功"
        except Exception as e:
            return False, str(e)

    def _retrieve_properties_all(self, vim_type, properties):
        if not self.is_connected():
            return []
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, [vim_type], True
        )
        filter_spec = self._create_property_filter_spec(container, vim_type, properties)
        pc = self.content.propertyCollector
        result = pc.RetrieveProperties(specSet=[filter_spec])
        container.Destroy()
        return result
