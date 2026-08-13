import datetime
import concurrent.futures
from pyVmomi import vim
from src.core.concurrent_config import ConcurrentConfig
from src.core.nsx_utils import derive_vm_nsx_managed, is_nsx_portgroup_name


class VMCollector:
    def __init__(self, connector):
        self.connector = connector
        self.cluster_cache = {}

    def collect_all_vms(self, progress_callback=None):
        if not self.connector.is_connected():
            return []

        print("开始采集虚拟机数据...")

        cluster_map = self.connector.build_cluster_host_map()
        network_cache = self.connector.build_network_cache()

        result = self.connector.get_all_vms()

        vm_count = len(result)
        parse_workers = ConcurrentConfig.get_optimal_workers('vm_collect', vm_count)

        all_vms = []
        # 小规模数据直接串行解析，减少线程池开销；大规模时并发解析。
        if vm_count < 300:
            for i, obj_content in enumerate(result, 1):
                try:
                    vm_info = self._parse_single_vm(
                        {p.name: p.val for p in obj_content.propSet},
                        cluster_map,
                        network_cache,
                    )
                    if vm_info:
                        all_vms.append(vm_info)
                    if progress_callback and i % 100 == 0:
                        progress_callback(i, vm_count)
                except Exception as e:
                    print(f"解析虚拟机失败: {e}")
                    continue
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=parse_workers) as executor:
                futures = {
                    executor.submit(
                        self._parse_single_vm,
                        {p.name: p.val for p in obj_content.propSet},
                        cluster_map,
                        network_cache,
                    ): i
                    for i, obj_content in enumerate(result, 1)
                }

                for future in concurrent.futures.as_completed(futures):
                    try:
                        vm_info = future.result()
                        if vm_info:
                            all_vms.append(vm_info)

                        i = futures[future]
                        if progress_callback and i % 100 == 0:
                            progress_callback(i, vm_count)
                    except Exception as e:
                        print(f"解析虚拟机失败: {e}")
                        continue

        return all_vms

    def _parse_single_vm(self, props, cluster_map=None, network_cache=None):
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
            system_version = props.get('guest.guestFullName', '') or ''
            guest_os = props.get('config.guestFullName', '') or ''
            cpu_hot_add = '是' if bool(props.get('config.cpuHotAddEnabled')) else '否'
            memory_hot_add = '是' if bool(props.get('config.memoryHotAddEnabled')) else '否'

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
            portgroups, nsx_managed = self._get_vm_portgroups_and_nsx(
                props.get('guest.net'),
                props.get('config.hardware.device'),
                network_cache or {},
            )

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
                'system_version': system_version,
                'guest_os': guest_os,
                'cpu_hot_add_enabled': cpu_hot_add,
                'memory_hot_add_enabled': memory_hot_add,
                'tools_status': tools_status_cn,
                'uptime_days': uptime_days,
                'datastore': datastore_names,
                'vm_portgroups': portgroups,
                'nsx_managed': nsx_managed,
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
        host_moid = getattr(host_mor, '_moId', None)

        if cluster_map and host_moid and host_moid in cluster_map:
            return cluster_map[host_moid]

        if host_moid and host_moid in self.cluster_cache:
            return self.cluster_cache[host_moid]

        try:
            parent = host_mor.parent
            while parent:
                if isinstance(parent, vim.ClusterComputeResource):
                    cluster_name = parent.name
                    if host_moid:
                        self.cluster_cache[host_moid] = cluster_name
                    return cluster_name
                if hasattr(parent, 'parent'):
                    parent = parent.parent
                else:
                    break
            if host_moid:
                self.cluster_cache[host_moid] = ''
            return ''
        except:
            if host_moid:
                self.cluster_cache[host_moid] = ''
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

    def _get_vm_portgroups_and_nsx(self, guest_net, hardware_devices=None, network_cache=None):
        try:
            if not guest_net:
                return '', '否'

            portgroups = []
            is_nsx = False
            for nic in guest_net:
                name = ''
                nic_nsx = False
                backing = getattr(nic, 'backing', None)
                if backing:
                    if isinstance(backing, vim.vm.device.VirtualEthernetCard.OpaqueNetworkBackingInfo):
                        nic_nsx = True
                        opaque_id = getattr(backing, 'opaqueNetworkId', '') or ''
                        opaque_type = (getattr(backing, 'opaqueNetworkType', '') or '').lower()
                        if 'nsx' in opaque_type:
                            nic_nsx = True
                        if opaque_id and network_cache and opaque_id in network_cache:
                            name = str(network_cache.get(opaque_id, '')).strip()
                    if hasattr(backing, 'deviceName') and backing.deviceName:
                        name = str(backing.deviceName).strip()
                    elif hasattr(backing, 'network') and backing.network and hasattr(backing.network, 'name'):
                        name = str(backing.network.name).strip()
                    elif hasattr(backing, 'port') and backing.port and hasattr(backing.port, 'portgroupKey'):
                        pg_key = backing.port.portgroupKey
                        name = str(pg_key).strip()
                        if network_cache and pg_key in network_cache:
                            name = str(network_cache.get(pg_key, name)).strip()
                            nic_nsx = nic_nsx or is_nsx_portgroup_name(name)

                if not name and hasattr(nic, 'network') and nic.network:
                    name = str(nic.network).strip()
                elif not name and hasattr(nic, 'deviceConfigId') and nic.deviceConfigId:
                    name = str(nic.deviceConfigId).strip()

                if name:
                    portgroups.append(name)
                if name and is_nsx_portgroup_name(name):
                    nic_nsx = True
                if nic_nsx:
                    is_nsx = True

            if not portgroups:
                return '', '是' if is_nsx else '否'
            return ', '.join(sorted(set(portgroups))), '是' if is_nsx else '否'
        except:
            return '', '否'

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

            return path_parts[-1] if path_parts else ''
        except:
            return ''
