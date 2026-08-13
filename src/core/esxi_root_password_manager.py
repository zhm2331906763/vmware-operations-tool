from pyVmomi import vim


class ESXiRootPasswordManager:
    def __init__(self, connector):
        self.connector = connector

    def change_root_password(self, host_name, new_password):
        if not new_password:
            return False, "root密码不能为空"

        host = self._get_host_by_name(host_name)
        if not host:
            return False, f"主机 {host_name} 未找到"

        return self._change_password_direct(host, new_password)

    def _change_password_direct(self, host, new_password):
        account_manager = host.configManager.accountManager

        # 兼容旧版/当前 pyVmomi：oldPassword 参数必须显式传入
        try:
            account_manager.ChangePassword(user='root', oldPassword='', newPassword=new_password)
            return True, "[ChangePassword] root密码修改成功"
        except Exception as first_err:
            first_msg = str(first_err)

        # 回退策略：直接更新 root 账户密码
        try:
            spec = vim.host.LocalAccountManager.AccountSpecification()
            spec.id = 'root'
            spec.password = new_password
            spec.description = 'root'
            account_manager.UpdateUser(user=spec)
            return True, "[ChangePassword失败] " + first_msg + "；[UpdateUser] root密码修改成功"
        except Exception as second_err:
            return False, f"[ChangePassword失败] {first_msg}；[UpdateUser失败] {str(second_err)}"

    def _get_host_by_name(self, host_name):
        content = self.connector.content
        host_view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.HostSystem], True
        )
        try:
            for host in host_view.view:
                if host.name == host_name:
                    return host
            return None
        finally:
            host_view.Destroy()
