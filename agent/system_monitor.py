"""
Read-only OS-level metrics collection. Nothing here touches Chrome or the
scraper -- it only reads counters that any process (e.g. Task Manager) can
read.
"""

from __future__ import annotations

import dataclasses
import platform
import socket
import time

import psutil


@dataclasses.dataclass
class SystemSnapshot:
    machine_name: str
    ip_address: str
    timestamp: float
    cpu_percent: float
    ram_percent: float
    ram_used_mb: float
    ram_total_mb: float
    disk_percent: float
    uptime_seconds: float
    internet_connected: bool
    python_process_running: bool


class SystemMonitor:
    """Collects machine-wide health metrics. Read-only, no side effects."""

    def __init__(self, machine_name: str, python_process_name_hint: str = "python"):
        self.machine_name = machine_name
        self._python_process_name_hint = python_process_name_hint.lower()

    @staticmethod
    def _get_ip_address() -> str:
        try:
            # Doesn't actually send data anywhere useful -- UDP "connect" to a
            # public IP just makes the OS pick the right local interface/IP.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(0.2)
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except OSError:
            return platform.node()

    @staticmethod
    def _check_internet(timeout: float = 2.0) -> bool:
        try:
            socket.setdefaulttimeout(timeout)
            socket.gethostbyname("www.google.com")
            return True
        except OSError:
            return False

    def _is_scraper_python_running(self) -> bool:
        """
        Detect whether *a* python process is running, WITHOUT knowing or caring
        about the scraper's internals. This is a coarse "is Python alive on
        this box" signal, deliberately not scoped to any particular script so
        the agent never needs to know anything about the scraper's identity.
        """
        for proc in psutil.process_iter(attrs=["name"]):
            name = (proc.info.get("name") or "").lower()
            if self._python_process_name_hint in name:
                return True
        return False

    def snapshot(self) -> SystemSnapshot:
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/" if platform.system() != "Windows" else "C:\\")
        uptime = time.time() - psutil.boot_time()

        return SystemSnapshot(
            machine_name=self.machine_name,
            ip_address=self._get_ip_address(),
            timestamp=time.time(),
            cpu_percent=psutil.cpu_percent(interval=0.5),
            ram_percent=vm.percent,
            ram_used_mb=round(vm.used / (1024 * 1024), 1),
            ram_total_mb=round(vm.total / (1024 * 1024), 1),
            disk_percent=disk.percent,
            uptime_seconds=uptime,
            internet_connected=self._check_internet(),
            python_process_running=self._is_scraper_python_running(),
        )
