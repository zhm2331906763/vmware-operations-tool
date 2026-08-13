import re
import socket
import time
import os
import posixpath
import sys
import base64
import tarfile
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlparse

import paramiko
from cryptography import x509
from paramiko.ssh_exception import AuthenticationException


class VCenterVmcaCertQuery:
    VECS_CLI = '/usr/lib/vmware-vmafd/bin/vecs-cli'
    TARGET_STORES = [
        'MACHINE_SSL_CERT',
        'machine',
        'vsphere-webclient',
        'vpxd',
        'vpxd-extension',
        'SMS',
        'data-encipherment',
        'hvc',
        'wcp',
        'wcpsvc',
    ]

    STORE_LABELS = {
        'MACHINE_SSL_CERT': 'MACHINE_SSL_CERT',
        'machine': 'machine',
        'vsphere-webclient': 'vsphere-webclient',
        'vpxd': 'vpxd',
        'vpxd-extension': 'vpxd-extension',
        'SMS': 'SMS',
        'data-encipherment': 'data-encipherment',
        'hvc': 'hvc',
        'wcp': 'wcp',
        'wcpsvc': 'wcpsvc',
    }

    def __init__(self, host, root_password, root_user='root', port=22, timeout=15):
        self.host = self._normalize_host(host)
        self.root_password = root_password
        self.root_user = root_user
        self.port = port
        self.timeout = timeout

    def renew_vmca_certificates(self, sso_user, sso_password, progress_cb=None):
        if not sso_user or not sso_password:
            return False, "续订失败：未提供vCenter管理账号或密码（SSO账号）"

        client = None
        remote_bundle_dir = "/tmp/codex_vcert_bundle"
        job_dir = f"/tmp/vcert_vmca_job_{int(time.time())}"
        answers_file = f"{job_dir}/answers.txt"
        run_file = f"{job_dir}/run_reset.sh"
        log_file = f"{job_dir}/renew.log"
        rc_file = f"{job_dir}/renew.rc"
        channel = None
        try:
            self._notify_progress(progress_cb, "connecting", "正在连接vCenter...", 5)
            client = self._connect_with_fallback()
            channel = self._open_bash_channel(client)
            self._notify_progress(progress_cb, "preparing", "连接成功，准备续订环境...", 12)
            local_vcert_dir = self._resolve_local_vcert_dir()
            self._ensure_remote_bundle(client, channel, local_vcert_dir, remote_bundle_dir, progress_cb)
            self._exec_quiet(channel, f"rm -rf {job_dir}")
            self._exec_quiet(channel, f"mkdir -p {job_dir}")
            self._notify_progress(progress_cb, "preparing", "已就绪，开始创建续订任务...", 22)

            answers = self._build_vcert_answers()
            self._write_remote_text_file(channel, answers_file, answers)
            run_script = self._build_run_script(remote_bundle_dir, sso_user, sso_password, answers_file, log_file, rc_file)
            self._write_remote_text_file(channel, run_file, run_script)
            self._exec_quiet(channel, f"chmod 700 {run_file}")
            self._exec_quiet(channel, f"rm -f {rc_file} {log_file}")
            self._notify_progress(progress_cb, "running", "续订任务已启动，正在执行证书替换...", 35)

            launch_cmd = f"nohup bash {run_file} >/dev/null 2>&1 & echo $!"
            rc, out_text, err_text = self._run_command(channel, launch_cmd, timeout=30)
            if rc != 0:
                return False, (
                    f"续订任务启动失败(rc={rc})\n"
                    f"stdout:\n{out_text or '<empty>'}\n"
                    f"stderr:\n{err_text or '<empty>'}"
                )

            # 任务启动后释放当前连接，采用轮询模式跟踪结果。
            try:
                client.close()
            except Exception:
                pass
            client = None
            channel = None

            ok, result = self._wait_background_job(
                rc_file=rc_file,
                log_file=log_file,
                timeout=7200,
                interval=10,
                progress_cb=progress_cb,
            )
            if ok:
                # 成功后清理远端目录，失败时保留便于排障。
                self._cleanup_remote_dir(job_dir)
                self._notify_progress(progress_cb, "done", "续订完成", 100)
                return True, result
            return False, result + f"\n远端日志目录保留: {job_dir}"
        except Exception as e:
            return False, str(e)
        finally:
            if client:
                client.close()

    def _build_vcert_answers(self):
        lines = [
            "US",
            "VMware",
            "VMware Engineering",
            "California",
            "Palo Alto",
            "",
            "",
            "",
            "",
            "N",
        ]
        lines.extend([""] * 2000)
        return "\n".join(lines) + "\n"

    def _ensure_remote_bundle(self, client, channel, local_vcert_dir, remote_bundle_dir, progress_cb=None):
        rc, out, err = self._run_command(
            channel,
            f"if [ -f {remote_bundle_dir}/config/logging.yaml ]; then echo __HAS_BUNDLE__; else echo __NO_BUNDLE__; fi",
            timeout=20,
        )
        if "__HAS_BUNDLE__" in out:
            self._notify_progress(progress_cb, "bundle_ready", "复用远端缓存vCert工具包", 18)
            return
        if progress_cb:
            progress_cb("uploading", "首次执行：正在上传vCert工具包到远端缓存...", 15)
        self._upload_directory(client, local_vcert_dir, remote_bundle_dir, channel)
        self._notify_progress(progress_cb, "bundle_ready", "vCert工具包上传完成", 20)

    def _build_run_script(self, remote_dir, sso_user, sso_password, answers_file, log_file, rc_file):
        q_user = self._shell_quote(sso_user)
        q_pwd = self._shell_quote(sso_password)
        return (
            "#!/bin/bash\n"
            f"cd {remote_dir} || exit 1\n"
            f"python3 vCert.py --run config/op_reset_cert_vmca.yaml "
            f"--user {q_user} --password {q_pwd} "
            f"< {answers_file} > {log_file} 2>&1\n"
            f"echo $? > {rc_file}\n"
        )

    def _wait_background_job(self, rc_file, log_file, timeout=7200, interval=10, progress_cb=None):
        end_time = time.time() + timeout
        cert_done_notified = False
        restarting_notified = False
        while time.time() < end_time:
            try:
                client = self._connect_with_fallback()
                channel = self._open_bash_channel(client)
                rc, out, err = self._run_command(
                    channel,
                    f"if [ -f {rc_file} ]; then echo __DONE__; cat {rc_file}; else echo __RUNNING__; fi",
                    timeout=20,
                )
                if "__DONE__" in out:
                    tail_rc, tail_out, tail_err = self._run_command(
                        channel, f"tail -n 200 {log_file}", timeout=20
                    )
                    client.close()
                    log_tail = tail_out or "<empty>"
                    rc_line = out.splitlines()[-1].strip() if out.splitlines() else "1"
                    job_rc = int(rc_line) if rc_line.isdigit() else 1
                    if job_rc == 0:
                        self._notify_progress(progress_cb, "done", "vCert执行完成", 100)
                        return True, f"续订完成\n日志尾部:\n{log_tail}"
                    if "Restart VMware services [N]:" in log_tail:
                        if not cert_done_notified:
                            self._notify_progress(progress_cb, "cert_done", "证书续订完成，准备重启所有VMware服务...", 75)
                            cert_done_notified = True
                        if not restarting_notified:
                            self._notify_progress(progress_cb, "restarting", "正在重启所有VMware服务，请稍候...", 85)
                            restarting_notified = True
                        restart_ok, restart_msg = self._restart_all_services()
                        if restart_ok:
                            self._notify_progress(progress_cb, "done", "服务重启完成", 100)
                            return True, (
                                "续订已完成（vCert在最后重启服务交互处退出，已自动执行全量服务重启）\n"
                                f"日志尾部:\n{log_tail}\n\n"
                                f"服务重启输出:\n{restart_msg}"
                            )
                        return False, (
                            f"续订失败(rc={job_rc})，并且自动重启服务失败\n"
                            f"日志尾部:\n{log_tail}\n\n"
                            f"服务重启输出:\n{restart_msg}"
                        )
                    return False, f"续订失败(rc={job_rc})\n日志尾部:\n{log_tail}\n{tail_err or ''}"
                client.close()
            except Exception:
                # 服务重启期间可能临时断连，继续轮询即可
                pass
            self._notify_progress(progress_cb, "running", "证书续订执行中，请耐心等待...", 50)
            time.sleep(interval)
        return False, "续订任务超时：等待结果超过7200秒"

    def _restart_all_services(self):
        try:
            client = self._connect_with_fallback()
            channel = self._open_bash_channel(client)
            rc, out, err = self._run_command(
                channel,
                "service-control --stop --all && service-control --start --all",
                timeout=7200,
                heartbeat_input="\n",
                heartbeat_interval=3.0,
            )
            client.close()
            combined = (out or "") + ("\n" + err if err else "")
            if rc == 0:
                return True, combined.strip() or "service-control执行成功"
            return False, f"service-control失败(rc={rc})\n{combined}"
        except Exception as e:
            return False, str(e)

    def _cleanup_remote_dir(self, remote_dir):
        try:
            client = self._connect_with_fallback()
            channel = self._open_bash_channel(client)
            self._exec_quiet(channel, f"rm -rf {remote_dir}")
            client.close()
        except Exception:
            pass

    @staticmethod
    def _notify_progress(progress_cb, stage, message, percent=None):
        if progress_cb:
            progress_cb(stage, message, percent)

    def query_vmca_certificates(self):
        client = None

        try:
            client = self._connect_with_fallback()
            channel = self._open_bash_channel(client)

            stores = self._get_available_target_stores(channel)
            cert_rows = []
            for store in stores:
                aliases = self._get_store_aliases(channel, store)
                for alias in aliases:
                    cert_pem = self._get_cert_pem(channel, store, alias)
                    if not cert_pem:
                        continue
                    parsed = self._parse_cert(cert_pem)
                    if not parsed:
                        continue
                    not_before, not_after, days_left = parsed
                    cert_type = self._build_cert_type(store, alias)
                    cert_rows.append({
                        'cert_type': cert_type,
                        'created_time': not_before,
                        'expiry_time': not_after,
                        'days_left': days_left,
                    })

            cert_rows.sort(key=lambda x: (x['days_left'], x['cert_type']))
            return True, cert_rows
        except Exception as e:
            return False, str(e)
        finally:
            if client:
                client.close()

    @staticmethod
    def _normalize_host(host):
        raw = (host or '').strip()
        if not raw:
            return raw

        if '://' in raw:
            parsed = urlparse(raw)
            return (parsed.hostname or raw).strip()

        if '/' in raw:
            parsed = urlparse(f'//{raw}')
            if parsed.hostname:
                return parsed.hostname.strip()

        if ':' in raw and raw.count(':') == 1:
            parsed = urlparse(f'//{raw}')
            if parsed.hostname:
                return parsed.hostname.strip()

        return raw

    def _connect_with_fallback(self):
        direct_error = None

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=self.host,
                port=self.port,
                username=self.root_user,
                password=self.root_password,
                timeout=self.timeout,
                auth_timeout=self.timeout,
                banner_timeout=self.timeout,
                look_for_keys=False,
                allow_agent=False,
            )
            return client
        except AuthenticationException as e:
            direct_error = e
            client.close()
        except Exception:
            client.close()
            raise

        transport_client = paramiko.SSHClient()
        transport_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            transport = paramiko.Transport(sock)
            transport.banner_timeout = self.timeout
            transport.auth_timeout = self.timeout
            transport.start_client(timeout=self.timeout)

            def kb_handler(title, instructions, prompts):
                return [self.root_password for _ in prompts]

            try:
                transport.auth_interactive(self.root_user, kb_handler)
            except Exception:
                transport.auth_password(self.root_user, self.root_password, fallback=True)

            if not transport.is_authenticated():
                raise AuthenticationException('认证失败：用户名或密码错误，或账号未允许SSH登录')

            transport_client._transport = transport
            return transport_client
        except Exception as e:
            transport_client.close()
            if direct_error:
                raise AuthenticationException(f'{direct_error}; interactive回退失败: {e}')
            raise

    @staticmethod
    def _shell_quote(text):
        if text is None:
            return "''"
        return "'" + str(text).replace("'", "'\"'\"'") + "'"

    def _resolve_local_vcert_dir(self):
        candidates = []
        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", "")
            if meipass:
                candidates.append(os.path.join(meipass, "vCert-6.1.1-20260401"))
            candidates.append(os.path.join(os.path.dirname(sys.executable), "vCert-6.1.1-20260401"))
        else:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            candidates.append(os.path.join(project_root, "vCert-6.1.1-20260401"))

        for path in candidates:
            if path and os.path.isdir(path):
                return path
        raise RuntimeError("未找到vCert脚本目录，无法执行VMCA证书续订")

    def _upload_directory(self, client, local_dir, remote_dir, channel=None):
        try:
            self._upload_directory_sftp(client, local_dir, remote_dir)
        except Exception:
            self._upload_directory_via_base64_tar(channel, local_dir, remote_dir)

    def _upload_directory_sftp(self, client, local_dir, remote_dir):
        sftp = client.open_sftp()
        try:
            self._mkdir_p(sftp, remote_dir)
            for root, dirs, files in os.walk(local_dir):
                rel = os.path.relpath(root, local_dir)
                remote_root = remote_dir if rel == "." else posixpath.join(remote_dir, rel.replace("\\", "/"))
                self._mkdir_p(sftp, remote_root)
                for d in dirs:
                    self._mkdir_p(sftp, posixpath.join(remote_root, d))
                for f in files:
                    local_file = os.path.join(root, f)
                    remote_file = posixpath.join(remote_root, f)
                    sftp.put(local_file, remote_file)
        finally:
            sftp.close()

    def _upload_directory_via_base64_tar(self, channel, local_dir, remote_dir):
        if channel is None:
            raise RuntimeError("上传失败：未建立shell通道，无法执行base64回退上传")
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmpf:
            tar_path = tmpf.name

        try:
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(local_dir, arcname="vCert-6.1.1-20260401")

            with open(tar_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")

            remote_b64 = f"{remote_dir}.tgz.b64"
            remote_tgz = f"{remote_dir}.tgz"

            self._exec_quiet(channel, f"rm -rf {remote_dir} {remote_b64} {remote_tgz}")
            self._exec_quiet(channel, f"mkdir -p {remote_dir}")
            self._stream_write_base64(channel, remote_b64, encoded)

            self._exec_quiet(channel, f"base64 -d {remote_b64} > {remote_tgz}")
            self._exec_quiet(channel, f"tar -xzf {remote_tgz} -C {remote_dir} --strip-components=1")
            self._exec_quiet(channel, f"rm -f {remote_b64} {remote_tgz}")
        finally:
            try:
                os.remove(tar_path)
            except Exception:
                pass

    def _stream_write_base64(self, channel, remote_b64, encoded_text):
        # 关闭回显，避免base64内容污染日志。按固定短行写入，规避大块流写导致的数据损坏。
        self._exec_quiet(channel, "stty -echo")
        try:
            self._exec_quiet(channel, f": > {remote_b64}")
            line_size = 76
            for i in range(0, len(encoded_text), line_size):
                line = encoded_text[i:i + line_size]
                safe = line.replace("'", "'\"'\"'")
                self._exec_quiet(channel, f"printf '%s\\n' '{safe}' >> {remote_b64}")

            # 基本校验：文件存在且有内容
            self._exec_quiet(channel, f"test -s {remote_b64}")
        finally:
            # 恢复回显，避免后续人工诊断受影响
            try:
                self._exec_quiet(channel, "stty echo")
            except Exception:
                pass

    def _write_remote_text_file(self, channel, remote_path, content):
        # 避免单次heredoc过长导致内容截断，改为逐行稳定写入。
        self._exec_quiet(channel, f": > {remote_path}")
        for line in content.splitlines():
            safe = line.replace("'", "'\"'\"'")
            self._exec_quiet(channel, f"printf '%s\\n' '{safe}' >> {remote_path}")

    def _mkdir_p(self, sftp, remote_path):
        parts = [p for p in remote_path.split("/") if p]
        current = "/"
        for part in parts:
            current = posixpath.join(current, part)
            try:
                sftp.stat(current)
            except IOError:
                sftp.mkdir(current)

    def _exec_quiet(self, channel, command):
        rc, out, err = self._run_command(channel, command, timeout=120)
        if rc != 0:
            raise RuntimeError(
                f"命令执行失败(rc={rc})\ncmd: {command}\nstdout:\n{out or '<empty>'}\nstderr:\n{err or '<empty>'}"
            )

    def _open_bash_channel(self, client):
        channel = client.invoke_shell(width=240, height=2000)
        time.sleep(0.8)
        latest = self._drain_channel(channel, timeout=2.0)

        # 某些VCSA默认进入 appliancesh，需要先切换到 bash。
        max_try = 4
        for _ in range(max_try):
            if self._looks_like_bash_prompt(latest):
                return channel

            # 仅在未进入bash时尝试切换，避免在bash里重复执行shell命令。
            channel.send("shell\n")
            time.sleep(0.8)
            latest = self._drain_channel(channel, timeout=4.0)
            if self._looks_like_bash_prompt(latest):
                return channel

        raise RuntimeError(
            "进入shell失败：未检测到bash提示符\n"
            f"stdout:\n{(latest or '<empty>').strip()}"
        )

    @staticmethod
    def _looks_like_bash_prompt(text):
        compact = VCenterVmcaCertQuery._strip_ansi(text or "").replace("\r", "")
        # 优先判定bash提示符，避免同时包含旧的Command>缓存时误判。
        if ("root@" in compact and "#" in compact) or "Shell access is granted" in compact:
            return True
        return False

    @staticmethod
    def _strip_ansi(text):
        ansi_escape = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
        return ansi_escape.sub("", text)

    @staticmethod
    def _drain_channel(channel, timeout=3.0):
        end = time.time() + timeout
        out = ""
        while time.time() < end:
            if channel.recv_ready():
                out += channel.recv(8192).decode("utf-8", errors="ignore")
            else:
                time.sleep(0.1)
        return out

    def _run_command(self, channel, command, timeout=40, heartbeat_input=None, heartbeat_interval=2.0):
        marker = f"__VCERT_RC__{int(time.time() * 1000)}"
        full_cmd = f"{command}\necho {marker}:$?\n"
        channel.send(full_cmd)

        end_time = time.time() + timeout
        raw = ""
        next_heartbeat = time.time() + heartbeat_interval
        while time.time() < end_time:
            if channel.recv_ready():
                raw += channel.recv(8192).decode("utf-8", errors="ignore")
                if marker in raw:
                    break
            else:
                now = time.time()
                if heartbeat_input and now >= next_heartbeat:
                    channel.send(heartbeat_input)
                    next_heartbeat = now + heartbeat_interval
                time.sleep(0.1)

        if marker not in raw:
            raise TimeoutError(f"命令执行超时: {command}")

        marker_match = re.search(re.escape(marker) + r":(\d+)", raw)
        rc = int(marker_match.group(1)) if marker_match else 1
        out_block = raw.split(marker, 1)[0]
        out = self._cleanup_command_output(out_block, command).strip()
        return rc, out, ""

    @staticmethod
    def _cleanup_command_output(text, command):
        lines = text.replace("\r", "").split("\n")
        cleaned = []
        command_stripped = command.strip()
        for line in lines:
            s = line.strip()
            if not s:
                continue
            if s == command_stripped:
                continue
            if s.startswith("Command>"):
                continue
            if re.match(r"^\[root@.+\]\s*#\s*$", s):
                continue
            cleaned.append(line)
        return "\n".join(cleaned)

    def _get_available_target_stores(self, channel):
        rc, out, err = self._run_command(channel, f'{self.VECS_CLI} store list', timeout=30)
        if rc != 0:
            raise RuntimeError(
                f'获取VECS store失败(rc={rc})\nstdout:\n{out or "<empty>"}\nstderr:\n{err or "<empty>"}'
            )

        all_stores = [line.strip() for line in out.splitlines() if line.strip()]
        return [s for s in self.TARGET_STORES if s in all_stores]

    def _get_store_aliases(self, channel, store):
        rc, out, err = self._run_command(channel, f'{self.VECS_CLI} entry list --store {store}', timeout=40)
        if rc != 0:
            return []

        aliases = re.findall(r'^\s*Alias\s*:\s*(.+?)\s*$', out, re.MULTILINE)
        return [a.strip() for a in aliases if a.strip()]

    def _get_cert_pem(self, channel, store, alias):
        rc, out, err = self._run_command(
            channel,
            f'{self.VECS_CLI} entry getcert --store {store} --alias {alias}',
            timeout=40,
        )
        if rc != 0:
            return ''

        match = re.search(
            r'-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----',
            out,
            re.MULTILINE,
        )
        return match.group(0) if match else ''

    @staticmethod
    def _parse_cert(cert_pem):
        try:
            cert = x509.load_pem_x509_certificate(cert_pem.encode('utf-8'))
            not_before = cert.not_valid_before_utc if hasattr(cert, 'not_valid_before_utc') else cert.not_valid_before
            not_after = cert.not_valid_after_utc if hasattr(cert, 'not_valid_after_utc') else cert.not_valid_after

            if not_before.tzinfo is None:
                not_before = not_before.replace(tzinfo=timezone.utc)
            if not_after.tzinfo is None:
                not_after = not_after.replace(tzinfo=timezone.utc)

            now_utc = datetime.now(timezone.utc)
            days_left = int((not_after - now_utc).days)

            return (
                not_before.strftime('%Y-%m-%d %H:%M:%S'),
                not_after.strftime('%Y-%m-%d %H:%M:%S'),
                days_left,
            )
        except Exception:
            return None

    def _build_cert_type(self, store, alias):
        label = self.STORE_LABELS.get(store, store)
        return f'{label}/{alias}' if alias else label
