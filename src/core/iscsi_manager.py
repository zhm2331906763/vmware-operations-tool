from pyVmomi import vim
from pyVim.task import WaitForTask


class ISCSIManager:
    def __init__(self, connector):
        self.connector = connector
    
    def add_iscsi_target(self, esxi_host_name, target_ips, target_iqn=None):
        """添加iSCSI动态发现目标，target_iqn 可选用于添加静态目标"""
        try:
            host = self._get_host_by_name(esxi_host_name)
            if not host:
                return False, f"找不到ESXi主机 '{esxi_host_name}'"
            
            storage_system = host.configManager.storageSystem
            if not storage_system:
                return False, "无法获取存储系统"
            
            # 查找iSCSI适配器
            iscsi_hba = self._get_iscsi_hba(storage_system)
            if not iscsi_hba:
                return False, "未找到iSCSI适配器"
            
            hba_device = iscsi_hba.device
            
            # 获取现有目标
            existing_targets = []
            if hasattr(iscsi_hba, 'configuredSendTarget') and iscsi_hba.configuredSendTarget:
                existing_targets = [t.address for t in iscsi_hba.configuredSendTarget]
            
            added_count = 0
            static_added_count = 0
            skipped_count = 0
            failed_ips = []
            static_failed_ips = []

            for target_ip in target_ips:
                if target_ip in existing_targets:
                    skipped_count += 1
                    continue
                
                try:
                    send_target = vim.host.InternetScsiHba.SendTarget(
                        address=target_ip,
                        port=3260
                    )
                    storage_system.AddInternetScsiSendTargets(
                        iScsiHbaDevice=hba_device,
                        targets=[send_target]
                    )
                    added_count += 1
                except Exception as e:
                    failed_ips.append(f"{target_ip}({e})")

            if target_iqn:
                static_added_count, static_failed_ips = self._add_static_targets(
                    storage_system=storage_system,
                    hba_device=hba_device,
                    target_ips=target_ips,
                    target_iqn=target_iqn
                )

            # 重新扫描
            if added_count > 0 or static_added_count > 0:
                storage_system.RescanHba(hbaDevice=hba_device)
            
            msg_parts = []
            if added_count > 0:
                msg_parts.append(f"新增{added_count}个")
            if static_added_count > 0:
                msg_parts.append(f"静态新增{static_added_count}个")
            if skipped_count > 0:
                msg_parts.append(f"跳过{skipped_count}个")
            if failed_ips:
                msg_parts.append(f"失败{len(failed_ips)}个")
            if static_failed_ips:
                msg_parts.append(f"静态失败{len(static_failed_ips)}个")
            
            return True, ', '.join(msg_parts) if msg_parts else "无操作"
        
        except Exception as e:
            return False, str(e)
    
    def _get_host_by_name(self, host_name):
        return self.connector.get_host_by_name(host_name)
    
    def _get_iscsi_hba(self, storage_system):
        device_info = storage_system.storageDeviceInfo
        if not device_info or not device_info.hostBusAdapter:
            return None

        for hba in device_info.hostBusAdapter:
            if isinstance(hba, vim.host.InternetScsiHba):
                return hba
        return None

    def _add_static_targets(self, storage_system, hba_device, target_ips, target_iqn):
        added_count = 0
        failed_ips = []

        existing_static = set()
        hba_info = self._get_iscsi_hba(storage_system)
        if hba_info and getattr(hba_info, 'configuredStaticTarget', None):
            for st in hba_info.configuredStaticTarget:
                address = getattr(st, 'address', '')
                iqn = getattr(st, 'iScsiName', '')
                if address and iqn:
                    existing_static.add((address, iqn))

        for target_ip in target_ips:
            if (target_ip, target_iqn) in existing_static:
                continue
            try:
                static_target = vim.host.InternetScsiHba.StaticTarget()
                static_target.address = target_ip
                static_target.port = 3260
                static_target.iScsiName = target_iqn
                storage_system.AddInternetScsiStaticTargets(
                    iScsiHbaDevice=hba_device,
                    targets=[static_target]
                )
                added_count += 1
            except Exception as e:
                failed_ips.append(f"{target_ip}({e})")

        return added_count, failed_ips
