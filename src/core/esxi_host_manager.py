import ssl
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
from pyVmomi import vmodl


class ESXiHostManager:
    def __init__(self, connector):
        self.connector = connector

    def _get_host_by_name(self, host_name):
        content = self.connector.content
        host_view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.HostSystem], True
        )
        hosts = host_view.view
        host_view.Destroy()

        for host in hosts:
            if host.name == host_name:
                return host
        return None

    def update_certificate(self, host_name):
        try:
            host = self._get_host_by_name(host_name)
            if not host:
                return False, f"主机 {host_name} 未找到"

            content = self.connector.content
            cert_mgr = content.certificateManager

            task = cert_mgr.CertMgrRefreshCertificates_Task(host=[host])
            self._wait_for_task(task)

            return True, "证书续订成功"

        except Exception as e:
            return False, str(e)

    def _wait_for_task(self, task):
        try:
            while task.info.state == vim.TaskInfo.State.running:
                import time
                time.sleep(0.5)
            if task.info.state == vim.TaskInfo.State.success:
                return True
            elif task.info.state == vim.TaskInfo.State.error:
                raise Exception(task.info.error.localizedMessage)
        except:
            pass
        return True

    def enable_ssh(self, host_name):
        try:
            host = self._get_host_by_name(host_name)
            if not host:
                return False, f"主机 {host_name} 未找到"

            service_system = host.configManager.serviceSystem

            service_system.StartService(id='TSM-SSH')
            service_system.UpdateServicePolicy(id='TSM-SSH', policy='on')

            return True, "SSH已开启并设置自启"

        except Exception as e:
            return False, str(e)

    def config_ntp(self, host_name, ntp_servers):
        try:
            host = self._get_host_by_name(host_name)
            if not host:
                return False, f"主机 {host_name} 未找到"

            ntp_list = [ntp.strip() for ntp in ntp_servers.split() if ntp.strip()]
            if not ntp_list:
                return False, "NTP服务器地址为空"

            date_time_system = host.configManager.dateTimeSystem

            dt_config = vim.host.DateTimeConfig()
            dt_config.ntpConfig = vim.host.NtpConfig(server=ntp_list)

            date_time_system.UpdateDateTimeConfig(dt_config)

            service_system = host.configManager.serviceSystem
            try:
                service_system.StopService(id='ntpd')
            except:
                pass
            try:
                service_system.StartService(id='ntpd')
                service_system.UpdateServicePolicy(id='ntpd', policy='on')
            except:
                pass

            return True, f"NTP配置完成: {', '.join(ntp_list)}"

        except Exception as e:
            return False, str(e)