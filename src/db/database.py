import os
import sys
import sqlite3
import threading
from datetime import datetime


class Database:
    _instance = None
    _lock = threading.Lock()

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
                remark TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

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
                vmk_adapters TEXT,
                cert_expiry TEXT,
                inspect_time TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

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
                tools_status TEXT,
                uptime_days REAL,
                datastore TEXT,
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

        conn.commit()
        conn.close()

    def add_vcenter(self, ip, user, password, remark=''):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    'INSERT OR REPLACE INTO vcenter_config (ip, user, password, remark, updated_at) VALUES (?, ?, ?, ?, ?)',
                    (ip, user, password, remark, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                )
                conn.commit()
                return True
            except Exception as e:
                print(f"添加vCenter失败: {e}")
                return False
            finally:
                conn.close()

    def get_vcenters(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, ip, user, password, remark, created_at, updated_at FROM vcenter_config ORDER BY ip')
        result = cursor.fetchall()
        conn.close()
        return result

    def delete_vcenter(self, vc_id):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('DELETE FROM vcenter_config WHERE id = ?', (vc_id,))
            conn.commit()
            conn.close()

    def update_vcenter(self, vc_id, ip, user, password, remark):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE vcenter_config SET ip=?, user=?, password=?, remark=?, updated_at=? WHERE id=?',
                (ip, user, password, remark, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), vc_id)
            )
            conn.commit()
            conn.close()

    def save_host_inspect(self, hosts_data):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            if hosts_data:
                vc_ip = hosts_data[0].get('vc_ip')
                cursor.execute('DELETE FROM host_inspect WHERE vc_ip = ?', (vc_ip,))

            for host in hosts_data:
                cursor.execute('''
                    INSERT INTO host_inspect (
                        vc_ip, host_name, cluster, status, esxi_version, vendor, model,
                        serial_number, cpu_model, cpu_ghz, cpu_count, cpu_cores,
                        memory_gb, uptime_days, cpu_usage, memory_usage, vmk_adapters, cert_expiry
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    host.get('vc_ip'), host.get('host_name'), host.get('cluster'), host.get('status'),
                    host.get('esxi_version'), host.get('vendor'), host.get('model'),
                    host.get('serial_number'), host.get('cpu_model'), host.get('cpu_ghz'),
                    host.get('cpu_count'), host.get('cpu_cores'), host.get('memory_gb'),
                    host.get('uptime_days'), host.get('cpu_usage'), host.get('memory_usage'),
                    host.get('vmk_adapters'), host.get('cert_expiry')
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
                where_clause += ' WHERE host_name LIKE ? OR cluster LIKE ?'
            params.extend([f'%{search}%', f'%{search}%'])

        if filters:
            for key, value in filters.items():
                if value and value != '全部':
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
                  uptime_days, cpu_usage, memory_usage, vmk_adapters, cert_expiry, inspect_time
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

    def save_vm_inspect(self, vms_data):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            if vms_data:
                vc_ip = vms_data[0].get('vc_ip')
                cursor.execute('DELETE FROM vm_inspect WHERE vc_ip = ?', (vc_ip,))

            for vm in vms_data:
                cursor.execute('''
                    INSERT INTO vm_inspect (
                        vc_ip, vm_name, cluster, host, power_state, ip_address, memory_gb,
                        cpu_count, uuid, annotation, tools_status, uptime_days, datastore,
                        disks, used_space_gb, folder
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    vm.get('vc_ip'), vm.get('vm_name'), vm.get('cluster'), vm.get('host'),
                    vm.get('power_state'), vm.get('ip_address'), vm.get('memory_gb'),
                    vm.get('cpu_count'), vm.get('uuid'), vm.get('annotation'), vm.get('tools_status'),
                    vm.get('uptime_days'), vm.get('datastore'), vm.get('disks'), vm.get('used_space_gb'),
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
                where_clause += ' WHERE vm_name LIKE ? OR ip_address LIKE ?'
            params.extend([f'%{search}%', f'%{search}%'])

        if filters:
            for key, value in filters.items():
                if value and value != '全部':
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
                  cpu_count, uuid, annotation, tools_status, uptime_days, datastore, disks,
                  used_space_gb, folder, inspect_time FROM vm_inspect{where_clause} ORDER BY vm_name LIMIT ? OFFSET ?'''
        params.extend([page_size, offset])
        cursor.execute(sql, params)
        result = cursor.fetchall()
        conn.close()

        return result, total

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
        cursor.execute('SELECT vc_ip, host_name, cluster, host FROM host_inspect WHERE uuid = ?', (uuid,))
        result = cursor.fetchone()
        conn.close()
        return result

    def clear_old_data(self, table_name, days=30):
        with self._lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM {table_name} WHERE inspect_time < datetime('now', '-{days} days')")
            conn.commit()
            conn.close()
