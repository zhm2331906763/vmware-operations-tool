from pyVmomi import vim
from pyVim.task import WaitForTask


class ISCSIManager:
    def __init__(self, connector):
        self.connector = connector
    
    def add_iscsi_target(self, esxi_host_name, target_ips):
        """添加iSCSI动态发现目标"""
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
            skipped_count = 0
            failed_ips = []
            
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
            
            # 重新扫描
            if added_count > 0:
                storage_system.RescanHba(hbaDevice=hba_device)
            
            msg_parts = []
            if added_count > 0:
                msg_parts.append(f"新增{added_count}个")
            if skipped_count > 0:
                msg_parts.append(f"跳过{skipped_count}个")
            if failed_ips:
                msg_parts.append(f"失败{len(failed_ips)}个")
            
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