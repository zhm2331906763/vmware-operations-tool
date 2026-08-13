import ssl
import socket
import datetime
import concurrent.futures
from pyVmomi import vim
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from src.core.concurrent_config import ConcurrentConfig


class HostCollector:
    CERT_TIMEOUT = 2
    CERT_EXPIRY_WARNING_DAYS = 30

    def __init__(self, connector):
        self.connector = connector

    def collect_all_hosts(self, progress_callback=None):
        if not self.connector.is_connected():
            return []

        content = self.connector.content
        print("开始采集主机数据...")

        cluster_map = self.connector.build_cluster_host_map()
        network_cache = self.connector.build_network_cache()

        result = self.connector.get_all_hosts()

        host_ip_list = []
        host_props_map = {}
        host_mor_map = {}

        for obj_content in result:
            props = {p.name: p.val for p in obj_content.propSet}
            host_mor = obj_content.obj
            host_moid = host_mor._moId
            host_props_map[host_moid] = props
            host_mor_map[host_moid] = host_mor

            host_ip = self._get_host_ip(props)
            if not host_ip:
                host_ip = props.get('name', '')
            if host_ip:
                host_ip_list.append(host_ip)

        cert_result = self._get_esxi_certificate_batch(host_ip_list)

        host_count = len(host_props_map)
        parse_workers = ConcurrentConfig.get_optimal_workers('host_collect_parse', host_count)

        all_hosts = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=parse_workers) as executor:
            futures = {
                executor.submit(self._parse_single_host, props, host_mor, self.connector.ip,
                               cluster_map, network_cache, cert_result): host_mor._moId
                for host_mor, props in zip(host_mor_map.values(), host_props_map.values())
            }

            for future in concurrent.futures.as_completed(futures):
                host_info = future.result()
                if host_info:
                    all_hosts.append(host_info)

        return all_hosts

    def _get_host_ip(self, props):
        network_config = props.get('config.network')
        if network_config and hasattr(network_config, 'vnic'):
            for vnic in network_config.vnic:
                if hasattr(vnic, 'spec') and hasattr(vnic.spec, 'ip') and vnic.spec.ip.ipAddress:
                    return vnic.spec.ip.ipAddress
        return ''

    def _get_esxi_certificate_batch(self, host_ip_list):
        cert_result = {}
        if not host_ip_list:
            return cert_result

        cert_workers = ConcurrentConfig.get_optimal_workers('host_collect_cert', len(host_ip_list))

        def fetch_single_cert(host_ip):
            try:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE

                with socket.create_connection((host_ip, 443), timeout=self.CERT_TIMEOUT) as sock:
                    with context.wrap_socket(sock, server_hostname=host_ip) as ssock:
                        cert_der = ssock.getpeercert(binary_form=True)

                if not cert_der:
                    return host_ip, None

                cert = x509.load_der_x509_certificate(cert_der, default_backend())
                not_after = cert.not_valid_after_utc if hasattr(cert, 'not_valid_after_utc') else cert.not_valid_after
                if not_after.tzinfo:
                    not_after = not_after.replace(tzinfo=None)
                return host_ip, not_after.strftime('%Y-%m-%d')
            except:
                return host_ip, None

        with concurrent.futures.ThreadPoolExecutor(max_workers=cert_workers) as executor:
            futures = [executor.submit(fetch_single_cert, ip) for ip in host_ip_list]
            for future in concurrent.futures.as_completed(futures):
                host_ip, not_after = future.result()
                cert_result[host_ip] = not_after

        return cert_result

    def _parse_single_host(self, props, host_mor, vc_ip, cluster_map, network_cache, cert_result):
        try:
            host_name = props.get('name', '')
            host_moid = host_mor._moId
            cluster_name = cluster_map.get(host_moid, '')
            power_state = props.get('runtime.powerState', '')
            overall_status = props.get('overallStatus', '')

            status_map = {'green': '正常', 'yellow': '警告', 'red': '严重', 'gray': '未知'}
            status = status_map.get(overall_status, '未知')
            if power_state != 'poweredOn':
                status = '已关机'

            product = props.get('config.product')
            esxi_version = product.version if product and hasattr(product, 'version') else '未知'

            system_info = props.get('hardware.systemInfo')
            vendor = system_info.vendor if system_info and hasattr(system_info, 'vendor') else ''
            model = system_info.model if system_info and hasattr(system_info, 'model') else ''

            bios_info = props.get('hardware.biosInfo')
            serial_number = self._get_serial_number(system_info, bios_info)

            cpu_info = props.get('hardware.cpuInfo')
            cpu_hz = cpu_info.hz if cpu_info and hasattr(cpu_info, 'hz') else 0
            num_cpu_pkgs = cpu_info.numCpuPackages if cpu_info and hasattr(cpu_info, 'numCpuPackages') else 0
            num_cpu_cores = cpu_info.numCpuCores if cpu_info and hasattr(cpu_info, 'numCpuCores') else 0

            cpu_pkgs = props.get('hardware.cpuPkg')
            cpu_model = cpu_pkgs[0].description if cpu_pkgs and len(cpu_pkgs) > 0 and hasattr(cpu_pkgs[0], 'description') else ''

            cpu_ghz = round(cpu_hz / 1e9, 2) if cpu_hz else 0

            memory_size = props.get('hardware.memorySize', 0)
            memory_gb = round(memory_size / (1024 ** 3), 2) if memory_size else 0

            cpu_usage = 0.0
            memory_usage = 0.0
            uptime_days = None

            if power_state == 'poweredOn':
                quick_stats = props.get('summary.quickStats')
                if quick_stats:
                    if hasattr(quick_stats, 'uptime') and quick_stats.uptime > 0:
                        uptime_days = round(quick_stats.uptime / (24 * 3600), 1)

                    if hasattr(quick_stats, 'overallCpuUsage') and cpu_info:
                        used_cpu = quick_stats.overallCpuUsage
                        total_cpu = num_cpu_cores * (cpu_hz / 1000000)
                        cpu_usage = round(used_cpu / total_cpu * 100, 2) if total_cpu > 0 else 0.0

                    if hasattr(quick_stats, 'overallMemoryUsage'):
                        used_mem_mb = quick_stats.overallMemoryUsage
                        total_mem_mb = memory_size / (1024 * 1024)
                        memory_usage = round(used_mem_mb / total_mem_mb * 100, 2) if total_mem_mb > 0 else 0.0

            host_ip = self._get_host_ip(props)
            if not host_ip:
                host_ip = host_name

            cert_expiry = cert_result.get(host_ip, None)
            cert_expiring_soon = '是' if self._is_cert_expiring_soon(cert_expiry) else '否'

            vmk_adapters = self._get_vmk_adapters(props.get('config.network'), network_cache)

            return {
                'vc_ip': vc_ip,
                'host_name': host_name,
                'cluster': cluster_name,
                'status': status,
                'esxi_version': esxi_version,
                'vendor': vendor,
                'model': model,
                'serial_number': serial_number,
                'cpu_model': cpu_model,
                'cpu_ghz': cpu_ghz,
                'cpu_count': num_cpu_pkgs,
                'cpu_cores': num_cpu_cores,
                'memory_gb': memory_gb,
                'uptime_days': uptime_days,
                'cpu_usage': cpu_usage,
                'memory_usage': memory_usage,
                'cert_expiring_soon': cert_expiring_soon,
                'vmk_adapters': vmk_adapters,
                'cert_expiry': cert_expiry,
                'host_ip': host_ip
            }
        except Exception as e:
            print(f"解析主机失败: {e}")
            return None

    def _is_cert_expiring_soon(self, cert_expiry):
        try:
            if not cert_expiry:
                return False
            if isinstance(cert_expiry, datetime.datetime):
                expiry_date = cert_expiry.date()
            elif isinstance(cert_expiry, datetime.date):
                expiry_date = cert_expiry
            else:
                expiry_date = datetime.datetime.strptime(str(cert_expiry).strip().split(' ')[0], '%Y-%m-%d').date()

            today = datetime.date.today()
            delta_days = (expiry_date - today).days
            return delta_days <= self.CERT_EXPIRY_WARNING_DAYS
        except Exception:
            return False

    def _get_serial_number(self, system_info, bios_info):
        invalid_serials = {"", " ", "default string", "unknown", "n/a", "na", "无", "none", "null",
                          "default", "0000000000", "0", "undefined", "not specified",
                          "to be filled by o.e.m.", "system serial number"}

        def clean_serial(s):
            if not s:
                return None
            s = str(s).strip()
            if not s or s.lower() in invalid_serials:
                return None
            return s.upper()

        if system_info and hasattr(system_info, 'serialNumber'):
            serial = clean_serial(system_info.serialNumber)
            if serial:
                return serial

        if bios_info and hasattr(bios_info, 'serialNumber'):
            serial = clean_serial(bios_info.serialNumber)
            if serial:
                return serial

        if system_info and hasattr(system_info, 'otherIdentifyingInfo') and system_info.otherIdentifyingInfo:
            for info in system_info.otherIdentifyingInfo:
                if hasattr(info, 'identifierValue'):
                    serial = clean_serial(info.identifierValue)
                    if serial:
                        return serial

        return "未知"

    def _get_vmk_adapters(self, network_config, network_cache):
        vmk_info = []
        try:
            if not network_config or not hasattr(network_config, 'vnic'):
                return ''

            for vnic in network_config.vnic:
                ip = ''
                portgroup_name = ''

                if hasattr(vnic, 'spec') and hasattr(vnic.spec, 'ip'):
                    ip = vnic.spec.ip.ipAddress
                if not ip:
                    continue

                if hasattr(vnic.spec, 'distributedVirtualPort') and vnic.spec.distributedVirtualPort:
                    dvs_connection = vnic.spec.distributedVirtualPort
                    if hasattr(dvs_connection, 'portgroupKey') and dvs_connection.portgroupKey:
                        pg_key = dvs_connection.portgroupKey
                        if network_cache and pg_key in network_cache:
                            portgroup_name = network_cache[pg_key]
                        else:
                            portgroup_name = f"分布式端口组({pg_key[:8]})"

                if not portgroup_name:
                    if hasattr(vnic, 'portgroup') and vnic.portgroup:
                        portgroup_name = network_cache.get(vnic.portgroup, vnic.portgroup)
                    elif hasattr(vnic.spec, 'portgroup') and vnic.spec.portgroup:
                        portgroup_name = network_cache.get(vnic.spec.portgroup, vnic.spec.portgroup)

                if portgroup_name:
                    vmk_info.append(f"{ip}({portgroup_name})")
                else:
                    vmk_info.append(f"{ip}(未知)")

            return '\n'.join(vmk_info) if vmk_info else ''
        except:
            return ''

    def get_host_disks(self, storage_device, host_name, vc_ip):
        disk_details = []
        try:
            if not storage_device or not hasattr(storage_device, 'scsiLun'):
                return disk_details

            remote_transport_types = {'iscsi', 'fc', 'fcoe', 'nfs', 'nvmetcp', 'rdma'}
            nvme_disk_prefixes = {'t10.nvme', 'eui.', 'naa.5'}
            raid_naa_prefixes = {'naa.600', 'naa.614', 'naa.624', 'naa.630', 'naa.648', 'naa.678', 'naa.690'}
            raid_keywords = ['logical volume', 'virtual disk', 'raid', 'vd ', 'megaraid', 'perc', 'smart array']

            disk_idx = 1
            for lun in storage_device.scsiLun:
                if getattr(lun, 'deviceType', '') != 'disk':
                    continue

                is_remote = False
                if hasattr(lun, 'transport') and hasattr(lun.transport, 'type'):
                    if lun.transport.type.lower() in remote_transport_types:
                        is_remote = True

                canonical = getattr(lun, 'canonicalName', '').lower()
                display_name = getattr(lun, 'displayName', '').lower()
                model = getattr(lun, 'model', '').lower()

                remote_kw = ['iscsi', 'vsan', 'vml', 'fc', 'nfs', 'netapp', 'emc', '3par']
                if any(kw in canonical for kw in remote_kw) or any(kw in display_name for kw in remote_kw):
                    is_remote = True

                if is_remote:
                    continue

                is_nvme = any(canonical.startswith(p) for p in nvme_disk_prefixes) or 'nvme' in model

                is_raid = False
                if not is_nvme:
                    if any(canonical.startswith(p) for p in raid_naa_prefixes):
                        is_raid = True
                    elif any(kw in model for kw in raid_keywords) or any(kw in display_name for kw in raid_keywords):
                        is_raid = True

                raw_vendor = (getattr(lun, 'vendor', '') or "").strip()
                raw_model = (getattr(lun, 'model', '') or "").strip()

                if is_raid:
                    final_model = "RAID硬盘"
                    final_vendor = ''
                else:
                    final_model = raw_model
                    final_vendor = raw_vendor if raw_vendor and raw_vendor.lower() not in ['ata', 'unknown', '', 'lsi', 'perc'] else ''

                capacity = 0.0
                used_capacity = 0.0
                if hasattr(lun, 'capacity') and lun.capacity:
                    capacity = round(lun.capacity.block * lun.capacity.blockSize / (1024 ** 3), 2)

                disk_name = f"磁盘 {disk_idx}" if not final_model else (f"{final_vendor} {final_model}" if final_vendor else final_model)

                disk_details.append({
                    'vc_ip': vc_ip,
                    'host_name': host_name,
                    'disk_index': disk_idx,
                    'disk_name': disk_name,
                    'disk_vendor': final_vendor,
                    'disk_model': final_model,
                    'disk_capacity': capacity,
                    'disk_used': used_capacity,
                    'disk_usage': 0.0
                })
                disk_idx += 1

            return disk_details
        except:
            return []

    def collect_all_local_disks(self, progress_callback=None):
        if not self.connector.is_connected():
            return []

        print("开始采集本地硬盘数据...")

        cluster_map = self.connector.build_cluster_host_map()
        datacenter_map = self.connector.build_datacenter_map()

        result = self.connector.get_all_hosts()

        host_info_list = []
        for obj_content in result:
            props = {p.name: p.val for p in obj_content.propSet}
            host_mor = obj_content.obj
            host_name = props.get('name', '')
            host_ip = self._get_host_ip(props) or host_name
            host_info_list.append({
                'mor': host_mor,
                'props': props,
                'name': host_name,
                'ip': host_ip
            })

        host_count = len(host_info_list)
        collect_workers = ConcurrentConfig.get_optimal_workers('host_collect_parse', host_count)

        all_disks = []

        def collect_host_disks(host_info):
            mor = host_info['mor']
            props = host_info['props']
            host_name = host_info['name']
            vc_ip = self.connector.ip

            cluster_name = cluster_map.get(getattr(mor, '_moId', ''), '')

            datacenter_name = ''
            for dc, clusters in datacenter_map.items():
                if cluster_name in clusters:
                    datacenter_name = dc
                    break

            storage_device = props.get('config.storageDevice')
            disks = self.get_host_disks(storage_device, host_name, vc_ip)

            for disk in disks:
                disk['datacenter'] = datacenter_name
                disk['cluster'] = cluster_name

            return disks

        with concurrent.futures.ThreadPoolExecutor(max_workers=collect_workers) as executor:
            futures = {
                executor.submit(collect_host_disks, hi): hi['name']
                for hi in host_info_list
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
