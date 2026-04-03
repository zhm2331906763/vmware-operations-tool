import datetime
import concurrent.futures
from pyVmomi import vim
from src.core.concurrent_config import ConcurrentConfig


class VMCollector:
    def __init__(self, connector):
        self.connector = connector
        self.cluster_cache = {}

    def collect_all_vms(self, progress_callback=None):
        if not self.connector.is_connected():
            return []

        print("开始采集虚拟机数据...")

        cluster_map = self.connector.build_cluster_host_map()

        result = self.connector.get_all_vms()

        vm_count = len(result)
        parse_workers = ConcurrentConfig.get_optimal_workers('vm_collect', vm_count)

        all_vms = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=parse_workers) as executor:
            futures = {
                executor.submit(self._parse_single_vm, {p.name: p.val for p in obj_content.propSet}, cluster_map): i
                for i, obj_content in enumerate(result, 1)
            }

            for future in concurrent.futures.as_completed(futures):
                try:
                    vm_info = future.result()
                    if vm_info:
                        all_vms.append(vm_info)

                    i = futures[future]
                    if progress_callback and i % 100 == 0:
                        progress_callback(i, len(result))
                except Exception as e:
                    print(f"解析虚拟机失败: {e}")
                    continue

        return all_vms

    def _parse_single_vm(self, props, cluster_map=None):
        try:
            host_mor = props.get('runtime.host')
            host_name = host_mor.name if host_mor else ''
            cluster_name = self._get_cluster_name(host_mor, cluster_map) if host_mor else ''

            power_state = props.get('runtime.powerState', '')
            state_map = {'poweredOn': '已开机', 'poweredOff': '已关机', 'suspended': '已挂起'}
            power_state_cn = state_map.get(power_state, '')

            boot_time = props.get('runtime.bootTime')
            uptime_days = self._calculate_uptime_days(power_state, boot_time)

            ip_address = self._get_vm_ip(props.get('guest.net'), props.get('guest.ipAddress'))

            memory_mb = props.get('config.hardware.memoryMB', 0)
            memory_gb = round(memory_mb / 1024, 2)
            cpu_count = props.get('config.hardware.numCPU', 0)

            uuid = props.get('config.instanceUuid', '')
            annotation = props.get('config.annotation', '') or ''

            tools_status = props.get('guest.toolsStatus', '')
            tools_map = {
                'toolsNotInstalled': '未安装',
                'toolsNotRunning': '未运行',
                'toolsOld': '版本过旧',
                'toolsOk': '正常',
                'toolsBlacklisted': '已黑名单'
            }
            tools_status_cn = tools_map.get(tools_status, '')

            datastore = props.get('datastore')
            datastore_names = self._get_datastore_names(datastore)

            hardware_devices = props.get('config.hardware.device')
            disks = self._get_vm_disks(hardware_devices)

            committed_bytes = props.get('summary.storage.committed', 0)
            used_space_gb = round(committed_bytes / (1024 ** 3), 2) if committed_bytes else 0

            folder = self._get_vm_folder(props.get('parent'))

            return {
                'vc_ip': self.connector.ip,
                'vm_name': props.get('name', ''),
                'cluster': cluster_name,
                'host': host_name,
                'power_state': power_state_cn,
                'ip_address': ip_address,
                'memory_gb': memory_gb,
                'cpu_count': cpu_count,
                'uuid': uuid,
                'annotation': annotation,
                'tools_status': tools_status_cn,
                'uptime_days': uptime_days,
                'datastore': datastore_names,
                'disks': disks,
                'used_space_gb': used_space_gb,
                'folder': folder
            }
        except Exception as e:
            print(f"解析虚拟机数据失败: {e}")
            return None

    def _get_cluster_name(self, host_mor, cluster_map=None):
        if not host_mor:
            return ''

        if cluster_map and host_mor in cluster_map:
            return cluster_map[host_mor]

        if host_mor in self.cluster_cache:
            return self.cluster_cache[host_mor]

        try:
            parent = host_mor.parent
            while parent:
                if isinstance(parent, vim.ClusterComputeResource):
                    cluster_name = parent.name
                    self.cluster_cache[host_mor] = cluster_name
                    return cluster_name
                if hasattr(parent, 'parent'):
                    parent = parent.parent
                else:
                    break
            self.cluster_cache[host_mor] = ''
            return ''
        except:
            self.cluster_cache[host_mor] = ''
            return ''

    def _calculate_uptime_days(self, power_state, boot_time):
        if power_state != 'poweredOn':
            return None

        if boot_time:
            try:
                if boot_time.tzinfo:
                    boot_time = boot_time.replace(tzinfo=None)
                now = datetime.datetime.now()
                delta = now - boot_time
                days = round(delta.total_seconds() / 86400, 1)
                if days > 0:
                    return days
            except:
                pass

        return None

    def _get_vm_ip(self, guest_net, guest_ip):
        try:
            if guest_ip and guest_ip != '127.0.0.1':
                return guest_ip

            if guest_net:
                for nic in guest_net:
                    if hasattr(nic, 'ipAddress') and nic.ipAddress:
                        for ip in nic.ipAddress:
                            if ip and not ip.startswith('127.') and not ip.startswith('169.254.'):
                                return ip
            return ''
        except:
            return ''

    def _get_datastore_names(self, datastores):
        try:
            if not datastores:
                return ''
            ds_names = sorted(list({ds.name for ds in datastores}))
            return ', '.join(ds_names)
        except:
            return ''

    def _get_vm_disks(self, hardware_devices):
        try:
            if not hardware_devices:
                return ''

            disk_sizes = []
            for device in hardware_devices:
                if isinstance(device, vim.vm.device.VirtualDisk):
                    capacity_kb = device.capacityInKB
                    capacity_gb = int(round(capacity_kb / (1024 * 1024), 0))
                    disk_sizes.append(f"{capacity_gb}GB")

            return '\n'.join(disk_sizes) if disk_sizes else ''
        except:
            return ''

    def _get_vm_folder(self, parent):
        try:
            if not parent:
                return ''

            path_parts = []
            current = parent
            while current:
                if hasattr(current, 'name') and current.name:
                    path_parts.insert(0, current.name)
                if hasattr(current, 'parent') and current.parent:
                    current = current.parent
                else:
                    break

            return '/'.join(path_parts) if path_parts else ''
        except:
            return ''
