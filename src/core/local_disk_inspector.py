import ssl
import concurrent.futures
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
from pyVmomi import vmodl
from src.core.concurrent_config import ConcurrentConfig


def is_local_disk(lun):
    try:
        remote_transports = {'iscsi', 'fc', 'fcoe', 'nfs', 'nvmetcp', 'rdma', 'iscsiv4', 'iscsiv6'}

        if hasattr(lun, 'transport') and hasattr(lun.transport, 'type'):
            transport_type = str(lun.transport.type).lower()
            if transport_type in remote_transports:
                return False

        canonical = getattr(lun, 'canonicalName', '').lower()
        display_name = getattr(lun, 'displayName', '').lower()

        remote_keywords = {'iscsi', 'fc ', ' fcoe', 'nfs', 'netapp', 'emc', '3par', 'huawei', 'dell compellent', 'hitachi'}
        if any(kw in canonical for kw in remote_keywords) or any(kw in display_name for kw in remote_keywords):
            return False

        local_keywords = {'local', 'sata', 'ssd', 'nvme', 'hdd', 'raid', 'logical volume', 'virtual disk'}
        if any(kw in canonical for kw in local_keywords) or any(kw in display_name for kw in local_keywords):
            return True

        if getattr(lun, 'deviceType', '') != 'disk':
            return False

        return True
    except Exception:
        return False


def build_vmfs_mapping(host_datastores):
    vmfs_map = {}
    try:
        for ds in host_datastores:
            if not hasattr(ds, 'summary') or ds.summary.type != 'VMFS':
                continue

            ds_name = ds.summary.name
            total_bytes = ds.summary.capacity
            free_bytes = ds.summary.freeSpace
            used_bytes = total_bytes - free_bytes

            total_gb = round(total_bytes / (1024 ** 3), 2)
            used_gb = round(used_bytes / (1024 ** 3), 2)
            usage_percent = round((used_bytes / total_bytes) * 100, 1) if total_bytes > 0 else 0

            if hasattr(ds, 'info') and hasattr(ds.info, 'vmfs') and hasattr(ds.info.vmfs, 'extent'):
                for extent in ds.info.vmfs.extent:
                    canonical_name = extent.diskName

                    if canonical_name in vmfs_map:
                        vmfs_map[canonical_name]['is_extent'] = True
                        vmfs_map[canonical_name]['ds_name'] += f" | {ds_name}(扩展)"
                    else:
                        vmfs_map[canonical_name] = {
                            'total_gb': total_gb,
                            'used_gb': used_gb,
                            'usage_percent': usage_percent,
                            'ds_name': ds_name,
                            'is_extent': False
                        }
    except Exception as e:
        print(f"构建VMFS映射时出错: {str(e)}")
    return vmfs_map


def get_disk_usage_info(lun, vmfs_map):
    try:
        canonical_name = getattr(lun, 'canonicalName', '')

        if canonical_name and canonical_name in vmfs_map:
            vmfs_info = vmfs_map[canonical_name]

            if vmfs_info['is_extent']:
                return (
                    vmfs_info['total_gb'],
                    vmfs_info['used_gb'],
                    f"{vmfs_info['usage_percent']}% (VMFS扩展盘)",
                    vmfs_info['ds_name']
                )
            else:
                return (
                    vmfs_info['total_gb'],
                    vmfs_info['used_gb'],
                    f"{vmfs_info['usage_percent']}%",
                    vmfs_info['ds_name']
                )

        total_bytes = 0
        if hasattr(lun, 'capacity') and lun.capacity:
            total_bytes = lun.capacity.block * lun.capacity.blockSize

        total_gb = round(total_bytes / (1024 ** 3), 2) if total_bytes > 0 else 0

        if total_gb == 0:
            status = "无法识别"
        elif hasattr(lun, 'deviceType') and lun.deviceType == 'disk':
            status = "未格式化/直通盘"
        else:
            status = "非数据盘"

        return (total_gb, 0, status, "")

    except Exception as e:
        return (0, 0, "获取失败", "")


def get_parent_name(obj, target_type):
    try:
        parent = obj.parent
        while parent:
            if isinstance(parent, target_type):
                return parent.name
            if hasattr(parent, 'parent'):
                parent = parent.parent
            else:
                break
        return ''
    except Exception:
        return ''


def create_property_filter_spec(container, vim_type, properties):
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


class LocalDiskInspector:
    def __init__(self, connector):
        self.connector = connector

    def collect_all_local_disks(self, progress_callback=None):
        if not self.connector.is_connected():
            return []

        content = self.connector.content

        host_container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.HostSystem], True
        )

        host_properties = [
            'name',
            'config.storageDevice',
            'datastore'
        ]

        filter_spec = create_property_filter_spec(host_container, vim.HostSystem, host_properties)
        pc = content.propertyCollector
        result = pc.RetrieveProperties(specSet=[filter_spec])
        host_container.Destroy()

        all_disks = []
        host_count = len(result)

        def collect_host_disks(obj_content):
            props = {p.name: p.val for p in obj_content.propSet}
            host_mor = obj_content.obj
            host_name = props.get('name', '')

            if not host_name:
                return []

            datacenter_name = get_parent_name(host_mor, vim.Datacenter)
            cluster_name = get_parent_name(host_mor, vim.ClusterComputeResource)

            storage_device = props.get('config.storageDevice')
            host_datastores = props.get('datastore', [])

            if not storage_device or not hasattr(storage_device, 'scsiLun'):
                return []

            vmfs_map = build_vmfs_mapping(host_datastores)

            local_disks = []
            for lun in storage_device.scsiLun:
                if is_local_disk(lun):
                    local_disks.append(lun)

            disks = []
            for lun in local_disks:
                disk_name = getattr(lun, 'displayName', '')
                if not disk_name:
                    disk_name = getattr(lun, 'deviceName', '')
                if not disk_name:
                    disk_name = getattr(lun, 'canonicalName', '')

                total_gb, used_gb, usage_percent, ds_name = get_disk_usage_info(lun, vmfs_map)

                disk_info = {
                    'vc_ip': self.connector.ip,
                    'datacenter': datacenter_name,
                    'cluster': cluster_name,
                    'host_name': host_name,
                    'disk_name': disk_name,
                    'datastore': ds_name,
                    'total_gb': total_gb,
                    'used_gb': used_gb,
                    'usage_percent': usage_percent
                }
                disks.append(disk_info)

            return disks

        collect_workers = ConcurrentConfig.get_optimal_workers('host_collect_parse', host_count)

        with concurrent.futures.ThreadPoolExecutor(max_workers=collect_workers) as executor:
            futures = {
                executor.submit(collect_host_disks, obj_content): obj_content.obj._moId
                for obj_content in result
            }

            for future in concurrent.futures.as_completed(futures):
                try:
                    disks = future.result()
                    if disks:
                        all_disks.extend(disks)
                    if progress_callback:
                        progress_callback(1)
                except Exception as e:
                    print(f"采集主机硬盘失败: {e}")

        return all_disks
