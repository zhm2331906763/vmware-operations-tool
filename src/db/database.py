import os
import sys
import sqlite3
import threading
from datetime import datetime


class Database:
    _instance = None
    _lock = threading.Lock()
    ALLOWED_HISTORY_TABLES = {'host_inspect', 'local_disk_inspect', 'vm_inspect', 'host_disk'}
    INSPECTION_DATA_TABLES = ('host_inspect', 'host_disk', 'local_disk_inspect', 'vm_inspect')

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            data_dir = os.path.join(exe_dir, 'data')
            os.makedirs(data_dir, exist_ok=True)
            self.db_path = os.path.join(data_dir, 'vcenter.db')
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.db_path = os.path.join(base_dir, 'src', 'db', 'vcenter.db')

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_tables()
        self._init_scheduled_tasks_table()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_tables(self):
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vcenter_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL UNIQUE,
                user TEXT NOT NULL,
                password TEXT NOT NULL,
                root_password TEXT DEFAULT '',
                region TEXT DEFAULT '',
                remark TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        try:
            cursor.execute("ALTER TABLE vcenter_config ADD COLUMN root_password TEXT DEFAULT ''")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE vcenter_config ADD COLUMN region TEXT DEFAULT ''")
        except:
            pass

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS host_inspect (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vc_ip TEXT NOT NULL,
                host_name TEXT NOT NULL,
                cluster TEXT,
                status TEXT,
                esxi_version TEXT,
                vendor TEXT,
                model TEXT,
                serial_number TEXT,
                cpu_model TEXT,
                cpu_ghz REAL,
                cpu_count INTEGER,
                cpu_cores INTEGER,
                memory_gb REAL,
                uptime_days REAL,
                cpu_usage REAL,
                memory_usage REAL,
                cert_expiring_soon TEXT DEFAULT '否',
                vmk_adapters TEXT,
                cert_expiry TEXT,
                inspect_time TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        try:
            cursor.execute("ALTER TABLE host_inspect ADD COLUMN cert_expiring_soon TEXT DEFAULT '否'")
        except:
            pass

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS host_disk (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vc_ip TEXT NOT NULL,
                host_name TEXT NOT NULL,
                disk_index INTEGER,
                disk_vendor TEXT,
                disk_model TEXT,
                disk_capacity REAL,
                inspect_time TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS local_disk_inspect (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vc_ip TEXT NOT NULL,
                datacenter TEXT,
                cluster TEXT,
                host_name TEXT NOT NULL,
                disk_name TEXT,
                datastore TEXT,
                total_gb REAL,
                used_gb REAL,
                usage_percent TEXT,
                inspect_time TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vm_inspect (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vc_ip TEXT NOT NULL,
                vm_name TEXT NOT NULL,
                cluster TEXT,
                host TEXT,
                power_state TEXT,
                ip_address TEXT,
                memory_gb REAL,
                cpu_count INTEGER,
                uuid TEXT,
                annotation TEXT,
                system_version TEXT,
                guest_os TEXT,
                cpu_hot_add_enabled TEXT DEFAULT '否',
                memory_hot_add_enabled TEXT DEFAULT '否',
                tools_status TEXT,
                uptime_days REAL,
                datastore TEXT,
                vm_portgroups TEXT,
                nsx_managed TEXT DEFAULT '否',
                disks TEXT,
                used_space_gb REAL,
                folder TEXT,
                inspect_time TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        try:
            cursor.execute('ALTER TABLE vm_inspect ADD COLUMN folder TEXT')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE vm_inspect ADD COLUMN system_version TEXT')
        except:
            pass
        try:
            cursor.execute('ALTER TABLE vm_inspect ADD COLUMN guest_os TEXT')
        except:
            pass
        try:
            cursor.execute("ALTER TABLE vm_inspect ADD COLUMN cpu_hot_add_enabled TEXT DEFAULT '否'")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE vm_inspect ADD COLUMN memory_hot_add_enabled TEXT DEFAULT '否'")
        except:
            pass
        try:
            cursor.execute('ALTER TABLE vm_inspect ADD COLUMN vm_portgroups TEXT')
        except:
            pass
        try:
            cursor.execute("ALTER TABLE vm_inspect ADD COLUMN nsx_managed TEXT DEFAULT '否'")
        except:
            pass

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_host_inspect_vc_host ON host_inspect(vc_ip, host_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_vm_inspect_vc_vm ON vm_inspect(vc_ip, vm_name)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_vm_inspect_uuid ON vm_inspect(uuid)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_local_disk_vc_host ON local_disk_inspect(vc_ip, host_name)')

        conn.commit()
        conn.close()

    def add_vcenter(self, ip, user, password, remark='', root_password='', region=''):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    '''INSERT OR REPLACE INTO vcenter_config
                       (ip, user, password, remark, root_password, region, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (ip, user, password, remark, root_password, region, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                )
                conn.commit()
                return True
            except Exception as e:
                print(f"娣诲姞vCenter澶辫触: {e}")
                return False
            finally:
                conn.close()

    def get_vcenters(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, ip, user, password, remark, created_at, updated_at, root_password, region '
            'FROM vcenter_config ORDER BY ip'
        )
        result = cursor.fetchall()
        conn.close()
        return result

    def delete_vcenter(self, vc_id):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute('SELECT ip FROM vcenter_config WHERE id = ?', (vc_id,))
                row = cursor.fetchone()
                if row:
                    self._delete_inspection_data(cursor, row[0])
                cursor.execute('DELETE FROM vcenter_config WHERE id = ?', (vc_id,))
                conn.commit()
            finally:
                conn.close()

    @classmethod
    def _delete_inspection_data(cls, cursor, vc_ip):
        """Delete all persisted inspection data belonging to one vCenter."""
        for table_name in cls.INSPECTION_DATA_TABLES:
            cursor.execute(f'DELETE FROM {table_name} WHERE vc_ip = ?', (vc_ip,))

    def sync_inspection_data_with_vcenters(self, active_vc_ips=None):
        """Remove inspection rows whose vCenter is no longer configured.

        ``active_vc_ips`` can be passed by a caller that already captured the
        current vCenter list. If omitted, the configured list is read in the
        same database transaction as the cleanup.
        """
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                if active_vc_ips is None:
                    cursor.execute('SELECT ip FROM vcenter_config')
                    active_vc_ips = {row[0] for row in cursor.fetchall() if row[0]}
                else:
                    active_vc_ips = {str(ip).strip() for ip in active_vc_ips if ip}
                active_vc_ips = tuple(sorted(active_vc_ips))

                deleted_rows = 0
                for table_name in self.INSPECTION_DATA_TABLES:
                    if active_vc_ips:
                        placeholders = ', '.join('?' for _ in active_vc_ips)
                        cursor.execute(
                            f'DELETE FROM {table_name} '
                            f'WHERE vc_ip IS NULL OR vc_ip NOT IN ({placeholders})',
                            tuple(active_vc_ips)
                        )
                    else:
                        cursor.execute(f'DELETE FROM {table_name}')
                    deleted_rows += cursor.rowcount

                conn.commit()
                return deleted_rows
            finally:
                conn.close()

    def update_vcenter(self, vc_id, ip, user, password, remark, root_password='', region=''):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE vcenter_config SET ip=?, user=?, password=?, remark=?, root_password=?, region=?, updated_at=? WHERE id=?',
                (ip, user, password, remark, root_password, region, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), vc_id)
            )
            conn.commit()
            conn.close()

    def get_vcenter_region_map(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT ip, COALESCE(region, "") FROM vcenter_config')
        rows = cursor.fetchall()
        conn.close()
        return {ip: region or '' for ip, region in rows}

    def save_host_inspect(self, hosts_data, vc_ip=None):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            if vc_ip:
                cursor.execute('DELETE FROM host_inspect WHERE vc_ip = ?', (vc_ip,))
            elif hosts_data:
                vc_ip = hosts_data[0].get('vc_ip')
                cursor.execute('DELETE FROM host_inspect WHERE vc_ip = ?', (vc_ip,))

            for host in hosts_data:
                cursor.execute('''
                    INSERT INTO host_inspect (
                        vc_ip, host_name, cluster, status, esxi_version, vendor, model,
                        serial_number, cpu_model, cpu_ghz, cpu_count, cpu_cores,
                        memory_gb, uptime_days, cpu_usage, memory_usage, cert_expiring_soon,
                        vmk_adapters, cert_expiry
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    host.get('vc_ip'), host.get('host_name'), host.get('cluster'), host.get('status'),
                    host.get('esxi_version'), host.get('vendor'), host.get('model'),
                    host.get('serial_number'), host.get('cpu_model'), host.get('cpu_ghz'),
                    host.get('cpu_count'), host.get('cpu_cores'), host.get('memory_gb'),
                    host.get('uptime_days'), host.get('cpu_usage'), host.get('memory_usage'),
                    host.get('cert_expiring_soon', '否'), host.get('vmk_adapters'), host.get('cert_expiry')
                ))
            conn.commit()
            conn.close()

    def get_host_inspect(self, vc_ip=None, search='', page=1, page_size=50, filters=None):
        conn = self.get_connection()
        cursor = conn.cursor()

        where_clause = ''
        params = []

        if vc_ip:
            where_clause += ' WHERE vc_ip = ?'
            params.append(vc_ip)

        if search:
            if where_clause:
                where_clause += ' AND (host_name LIKE ? OR cluster LIKE ?)'
            else:
                where_clause += ' WHERE (host_name LIKE ? OR cluster LIKE ?)'
            params.extend([f'%{search}%', f'%{search}%'])

        if filters:
            for key, value in filters.items():
                if value and value != '鍏ㄩ儴':
                    col_map = {
                        'vc_ip': 'vc_ip',
                        'status': 'status',
                        'esxi_version': 'esxi_version',
                        'vendor': 'vendor',
                        'cluster': 'cluster'
                    }
                    col = col_map.get(key, key)
                    if where_clause:
                        where_clause += f' AND {col} = ?'
                    else:
                        where_clause += f' WHERE {col} = ?'
                    params.append(value)

        count_sql = f'SELECT COUNT(*) FROM host_inspect{where_clause}'
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        offset = (page - 1) * page_size
        sql = f'''SELECT id, vc_ip, host_name, cluster, status, esxi_version, vendor, model,
                  serial_number, cpu_model, cpu_ghz, cpu_count, cpu_cores, memory_gb,
                  uptime_days, cpu_usage, memory_usage, cert_expiring_soon, vmk_adapters, cert_expiry, inspect_time
                  FROM host_inspect{where_clause} ORDER BY host_name LIMIT ? OFFSET ?'''
        params.extend([page_size, offset])
        cursor.execute(sql, params)
        result = cursor.fetchall()
        conn.close()

        return result, total

    def save_host_disks(self, disks_data):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            for disk in disks_data:
                cursor.execute('''
                    INSERT INTO host_disk (vc_ip, host_name, disk_index, disk_vendor, disk_model, disk_capacity)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (disk.get('vc_ip'), disk.get('host_name'), disk.get('disk_index'),
                      disk.get('disk_vendor'), disk.get('disk_model'), disk.get('disk_capacity')))
            conn.commit()
            conn.close()

    def get_host_disks(self, host_name, vc_ip):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT disk_index, disk_vendor, disk_model, disk_capacity
            FROM host_disk WHERE host_name = ? AND vc_ip = ?
            ORDER BY disk_index
        ''', (host_name, vc_ip))
        result = cursor.fetchall()
        conn.close()
        return result

    def save_local_disk_inspect(self, disks_data):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            if disks_data:
                vc_ip = disks_data[0].get('vc_ip')
                cursor.execute('DELETE FROM local_disk_inspect WHERE vc_ip = ?', (vc_ip,))

            for disk in disks_data:
                cursor.execute('''
                    INSERT INTO local_disk_inspect (
                        vc_ip, datacenter, cluster, host_name, disk_name, datastore,
                        total_gb, used_gb, usage_percent
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    disk.get('vc_ip'), disk.get('datacenter'), disk.get('cluster'),
                    disk.get('host_name'), disk.get('disk_name'), disk.get('datastore'),
                    disk.get('total_gb'), disk.get('used_gb'), disk.get('usage_percent')
                ))
            conn.commit()
            conn.close()

    def get_local_disk_inspect(self, vc_ip=None, search='', page=1, page_size=50):
        conn = self.get_connection()
        cursor = conn.cursor()

        where_clause = ''
        params = []

        if vc_ip:
            where_clause += ' WHERE vc_ip = ?'
            params.append(vc_ip)

        if search:
            if where_clause:
                where_clause += ' AND host_name LIKE ?'
            else:
                where_clause += ' WHERE host_name LIKE ?'
            params.append(f'%{search}%')

        count_sql = f'SELECT COUNT(*) FROM local_disk_inspect{where_clause}'
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        offset = (page - 1) * page_size
        sql = f'''SELECT id, vc_ip, datacenter, cluster, host_name, disk_name, datastore,
                  total_gb, used_gb, usage_percent, inspect_time
                  FROM local_disk_inspect{where_clause} ORDER BY host_name LIMIT ? OFFSET ?'''
        params.extend([page_size, offset])
        cursor.execute(sql, params)
        result = cursor.fetchall()
        conn.close()

        return result, total

    def save_vm_inspect(self, vms_data, vc_ip=None):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            if vc_ip:
                cursor.execute('DELETE FROM vm_inspect WHERE vc_ip = ?', (vc_ip,))
            elif vms_data:
                vc_ip = vms_data[0].get('vc_ip')
                cursor.execute('DELETE FROM vm_inspect WHERE vc_ip = ?', (vc_ip,))

            for vm in vms_data:
                cursor.execute('''
                    INSERT INTO vm_inspect (
                        vc_ip, vm_name, cluster, host, power_state, ip_address, memory_gb,
                        cpu_count, uuid, annotation, system_version, guest_os, cpu_hot_add_enabled,
                        memory_hot_add_enabled, tools_status, uptime_days, datastore,
                        vm_portgroups, nsx_managed, disks, used_space_gb, folder
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    vm.get('vc_ip'), vm.get('vm_name'), vm.get('cluster'), vm.get('host'),
                    vm.get('power_state'), vm.get('ip_address'), vm.get('memory_gb'),
                    vm.get('cpu_count'), vm.get('uuid'), vm.get('annotation'),
                    vm.get('system_version'), vm.get('guest_os'), vm.get('cpu_hot_add_enabled', '否'),
                    vm.get('memory_hot_add_enabled', '否'), vm.get('tools_status'),
                    vm.get('uptime_days'), vm.get('datastore'), vm.get('vm_portgroups', ''), vm.get('nsx_managed', '否'),
                    vm.get('disks'), vm.get('used_space_gb'),
                    vm.get('folder', '')
                ))
            conn.commit()
            conn.close()

    def get_vm_inspect(self, vc_ip=None, search='', page=1, page_size=50, filters=None):
        conn = self.get_connection()
        cursor = conn.cursor()

        where_clause = ''
        params = []

        if vc_ip:
            where_clause += ' WHERE vc_ip = ?'
            params.append(vc_ip)

        if search:
            if where_clause:
                where_clause += ' AND (vm_name LIKE ? OR ip_address LIKE ?)'
            else:
                where_clause += ' WHERE (vm_name LIKE ? OR ip_address LIKE ?)'
            params.extend([f'%{search}%', f'%{search}%'])

        if filters:
            for key, value in filters.items():
                if value and value != '鍏ㄩ儴':
                    col_map = {
                        'vc_ip': 'vc_ip',
                        'cluster': 'cluster',
                        'datastore': 'datastore',
                        'power_state': 'power_state',
                        'tools_status': 'tools_status'
                    }
                    col = col_map.get(key, key)
                    if where_clause:
                        where_clause += f' AND {col} = ?'
                    else:
                        where_clause += f' WHERE {col} = ?'
                    params.append(value)

        count_sql = f'SELECT COUNT(*) FROM vm_inspect{where_clause}'
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        offset = (page - 1) * page_size
        sql = f'''SELECT id, vc_ip, vm_name, cluster, host, power_state, ip_address, memory_gb,
                  cpu_count, uuid, annotation, system_version, guest_os, cpu_hot_add_enabled, memory_hot_add_enabled, tools_status, uptime_days, datastore, disks,
                  vm_portgroups, nsx_managed, used_space_gb, folder, inspect_time FROM vm_inspect{where_clause} ORDER BY vm_name LIMIT ? OFFSET ?'''
        params.extend([page_size, offset])
        cursor.execute(sql, params)
        result = cursor.fetchall()
        conn.close()

        return result, total

    def clear_vm_inspect(self, vc_ip=None):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            if vc_ip:
                cursor.execute('DELETE FROM vm_inspect WHERE vc_ip = ?', (vc_ip,))
            else:
                cursor.execute('DELETE FROM vm_inspect')
            conn.commit()
            conn.close()

    def clear_host_inspect(self, vc_ip=None):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            if vc_ip:
                cursor.execute('DELETE FROM host_inspect WHERE vc_ip = ?', (vc_ip,))
            else:
                cursor.execute('DELETE FROM host_inspect')
            conn.commit()
            conn.close()

    def get_all_vms_for_batch(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT vc_ip, vm_name, uuid, annotation, host FROM vm_inspect ORDER BY vm_name')
        result = cursor.fetchall()
        conn.close()
        return result

    def update_vm_annotation(self, uuid, annotation):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE vm_inspect SET annotation = ? WHERE uuid = ?', (annotation, uuid))
            conn.commit()
            conn.close()

    def update_vm_name(self, uuid, new_name):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE vm_inspect SET vm_name = ? WHERE uuid = ?', (new_name, uuid))
            conn.commit()
            conn.close()

    def get_host_by_uuid(self, uuid):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT vc_ip, vm_name, cluster, host FROM vm_inspect WHERE uuid = ?', (uuid,))
        result = cursor.fetchone()
        conn.close()
        return result

    def clear_old_data(self, table_name, days=30):
        if table_name not in self.ALLOWED_HISTORY_TABLES:
            raise ValueError(f"涓嶅厑璁告竻鐞嗙殑鏁版嵁琛? {table_name}")
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM {table_name} WHERE inspect_time < datetime('now', '-{days} days')")
            conn.commit()
            conn.close()

    def _init_scheduled_tasks_table(self):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_name TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    schedule_type TEXT NOT NULL,
                    schedule_time TEXT NOT NULL,
                    schedule_day TEXT,
                    save_path TEXT,
                    enabled INTEGER DEFAULT 1,
                    last_run TEXT,
                    last_status TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tasks_enabled_time ON scheduled_tasks(enabled, schedule_type, schedule_time, schedule_day)')
            conn.commit()
            conn.close()

    def add_scheduled_task(self, task_name, task_type, schedule_type, schedule_time, schedule_day=None, save_path=None):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO scheduled_tasks (task_name, task_type, schedule_type, schedule_time, schedule_day, save_path, enabled)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            ''', (task_name, task_type, schedule_type, schedule_time, schedule_day, save_path))
            conn.commit()
            conn.close()
            return cursor.lastrowid

    def get_scheduled_tasks(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM scheduled_tasks ORDER BY created_at DESC')
        result = cursor.fetchall()
        conn.close()
        return result

    def get_enabled_tasks(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM scheduled_tasks WHERE enabled = 1 ORDER BY created_at DESC')
        result = cursor.fetchall()
        conn.close()
        return result

    def update_task(self, task_id, **kwargs):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            for key, value in kwargs.items():
                if key in ('enabled', 'last_run', 'last_status'):
                    cursor.execute(f'UPDATE scheduled_tasks SET {key} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (value, task_id))
            conn.commit()
            conn.close()

    def delete_task(self, task_id):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM scheduled_tasks WHERE id = ?', (task_id,))
            conn.commit()
            conn.close()

    def update_scheduled_task(self, task_id, task_name, task_type, schedule_type, schedule_time, schedule_day=None, save_path=None):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE scheduled_tasks
                SET task_name = ?, task_type = ?, schedule_type = ?, schedule_time = ?,
                    schedule_day = ?, save_path = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (task_name, task_type, schedule_type, schedule_time, schedule_day, save_path, task_id))
            conn.commit()
            conn.close()

    def update_task_status(self, task_id, status):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('UPDATE scheduled_tasks SET last_run = CURRENT_TIMESTAMP, last_status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (status, task_id))
            conn.commit()
            conn.close()

