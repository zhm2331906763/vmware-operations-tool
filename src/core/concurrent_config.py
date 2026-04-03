import os


class ConcurrentConfig:
    @staticmethod
    def get_cpu_count():
        return os.cpu_count() or 4

    @staticmethod
    def get_optimal_workers(task_type, data_count=None):
        cpu_count = ConcurrentConfig.get_cpu_count()

        if task_type == 'vc_inspect':
            return min(5, max(2, cpu_count - 1))

        elif task_type == 'host_collect_cert':
            if data_count:
                return min(50, max(20, data_count // 10 + 10))
            return min(50, cpu_count * 4)

        elif task_type == 'host_collect_parse':
            if data_count:
                return min(20, max(5, data_count // 20 + 5))
            return min(20, cpu_count * 2)

        elif task_type == 'vm_collect':
            if data_count:
                return min(20, max(5, data_count // 50 + 5))
            return min(20, cpu_count * 2)

        elif task_type == 'batch_operation':
            return min(10, max(3, cpu_count))

        elif task_type == 'clone_vm':
            return min(5, max(2, cpu_count - 2))

        return 5

    @staticmethod
    def get_thread_pool_size(task_type, total_count):
        workers = ConcurrentConfig.get_optimal_workers(task_type, total_count)
        return min(workers, total_count)
