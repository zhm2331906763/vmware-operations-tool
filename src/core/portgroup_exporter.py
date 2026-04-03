import ssl
import time
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim


class PortGroupExporter:
    def __init__(self):
        pass
    
    def _connect_vc(self, vc_ip, username, password):
        context = ssl._create_unverified_context()
        si = SmartConnect(
            host=vc_ip,
            user=username,
            pwd=password,
            port=443,
            sslContext=context
        )
        return si
    
    def _get_datacenter_name(self, obj):
        try:
            parent = obj.parent
            while parent:
                if isinstance(parent, vim.Datacenter):
                    return parent.name
                if hasattr(parent, 'parent'):
                    parent = parent.parent
                else:
                    break
            return ''
        except Exception:
            return ''
    
    def _get_cluster_from_vds(self, vds):
        try:
            if hasattr(vds, 'summary') and hasattr(vds.summary, 'hostMember'):
                for host_member in vds.summary.hostMember:
                    host = host_member.config.host
                    if host:
                        parent = host.parent
                        if isinstance(parent, vim.ClusterComputeResource):
                            return parent.name
                        while hasattr(parent, 'parent'):
                            parent = parent.parent
                            if isinstance(parent, vim.ClusterComputeResource):
                                return parent.name
            return ''
        except Exception:
            return ''
    
    def _get_vlan_id(self, portgroup):
        try:
            if hasattr(portgroup, 'config') and hasattr(portgroup.config, 'defaultPortConfig'):
                port_config = portgroup.config.defaultPortConfig
                if hasattr(port_config, 'vlan'):
                    vlan_spec = port_config.vlan
                    if hasattr(vlan_spec, 'vlanId'):
                        vlan_value = vlan_spec.vlanId
                        if isinstance(vlan_value, int):
                            return vlan_value
                        elif hasattr(vlan_value, 'start') and hasattr(vlan_value, 'end'):
                            return f"{vlan_value.start}-{vlan_value.end}"
                        else:
                            return str(vlan_value)
                    elif hasattr(vlan_spec, 'vlanId') and vlan_spec.vlanId is None:
                        return 0
            return 0
        except Exception:
            return 0
    
    def collect_portgroups(self, vc_ip, username, password):
        results = []
        si = None
        
        try:
            si = self._connect_vc(vc_ip, username, password)
            content = si.content
            
            container = content.viewManager.CreateContainerView(
                content.rootFolder, [vim.dvs.DistributedVirtualPortgroup], True
            )
            
            properties = ['name', 'config', 'parent']
            filter_spec = self._create_property_filter_spec(container, vim.dvs.DistributedVirtualPortgroup, properties)
            pc = content.propertyCollector
            result = pc.RetrieveProperties(specSet=[filter_spec])
            container.Destroy()
            
            for obj_content in result:
                try:
                    props = {p.name: p.val for p in obj_content.propSet}
                    pg_name = props.get('name', '')
                    
                    vds_name = ''
                    cluster_name = ''
                    config = props.get('config')
                    if config and hasattr(config, 'distributedVirtualSwitch'):
                        vds = config.distributedVirtualSwitch
                        if vds:
                            vds_name = vds.name
                            cluster_name = self._get_cluster_from_vds(vds)
                    
                    parent_obj = props.get('parent')
                    datacenter_name = self._get_datacenter_name(parent_obj) if parent_obj else ''
                    
                    vlan_id = 0
                    if config and hasattr(config, 'defaultPortConfig'):
                        port_config = config.defaultPortConfig
                        if hasattr(port_config, 'vlan'):
                            vlan_spec = port_config.vlan
                            if hasattr(vlan_spec, 'vlanId'):
                                vlan_value = vlan_spec.vlanId
                                if isinstance(vlan_value, int):
                                    vlan_id = vlan_value
                                elif hasattr(vlan_value, 'start') and hasattr(vlan_value, 'end'):
                                    vlan_id = f"{vlan_value.start}-{vlan_value.end}"
                    
                    results.append({
                        'vCenter': vc_ip,
                        '数据中心': datacenter_name,
                        '集群': cluster_name,
                        '端口组名称': pg_name,
                        '端口组VLAN': vlan_id,
                        '所属交换机': vds_name
                    })
                except Exception:
                    continue
            
            if si:
                Disconnect(si)
                si = None
            
        except Exception:
            if si:
                try:
                    Disconnect(si)
                except:
                    pass
        
        return results
    
    def _create_property_filter_spec(self, container, vim_type, properties):
        try:
            from pyVmomi import vmodl
            
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
        except:
            return None
    
    def export_all_vcenters(self, vcenters, status_callback=None):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        all_results = []
        
        def collect_single(vc_config):
            vc_ip = vc_config[1]
            username = vc_config[2]
            password = vc_config[3]
            start_time = time.time()
            results = self.collect_portgroups(vc_ip, username, password)
            elapsed = time.time() - start_time
            return results, elapsed
        
        if status_callback:
            status_callback(f"开始收集 {len(vcenters)} 个vCenter...")
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(collect_single, vc): vc for vc in vcenters}
            total_time = 0
            for future in as_completed(futures):
                try:
                    results, elapsed = future.result()
                    all_results.extend(results)
                    total_time += elapsed
                    if status_callback:
                        status_callback(f"已收集 {len(all_results)} 个端口组 (耗时: {elapsed:.1f}s)")
                except Exception:
                    continue
        
        return all_results, total_time
    
    def save_to_excel(self, file_path, results):
        from openpyxl import Workbook
        
        wb = Workbook()
        ws = wb.active
        ws.title = "端口组信息"
        ws.append(['vCenter', '数据中心', '集群', '端口组名称', '端口组VLAN', '所属交换机'])
        
        for r in results:
            ws.append([
                r['vCenter'], r['数据中心'], r['集群'],
                r['端口组名称'], r['端口组VLAN'], r['所属交换机']
            ])
        
        column_widths = {'A': 15, 'B': 20, 'C': 20, 'D': 30, 'E': 15, 'F': 25}
        for col, width in column_widths.items():
            ws.column_dimensions[col].width = width
        
        wb.save(file_path)