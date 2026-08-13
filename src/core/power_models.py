from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(slots=True)
class PowerTaskTarget:
    uuid: str = ""
    name: str = ""
    host: str = ""
    ip_address: str = ""
    cluster: str = ""
    vc_ip: str = ""

    @property
    def display_name(self) -> str:
        return self.name or self.ip_address or self.uuid or self.host or ""

    def to_dict(self) -> dict[str, str]:
        return {
            "uuid": self.uuid or "",
            "name": self.name or "",
            "host": self.host or "",
            "ip_address": self.ip_address or "",
            "cluster": self.cluster or "",
            "vc_ip": self.vc_ip or "",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PowerTaskTarget":
        return cls(
            uuid=str(data.get("uuid", "") or ""),
            name=str(data.get("name", "") or ""),
            host=str(data.get("host", "") or ""),
            ip_address=str(data.get("ip_address", "") or ""),
            cluster=str(data.get("cluster", "") or ""),
            vc_ip=str(data.get("vc_ip", "") or ""),
        )


@dataclass(slots=True)
class PowerTask:
    id: str
    name: str
    action: str
    schedule_type: str
    schedule_time: str
    schedule_day: str = ""
    enabled: bool = True
    vcenter_name: str = ""
    targets: list[PowerTaskTarget] = field(default_factory=list)
    last_run: str = ""
    last_status: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def target_count(self) -> int:
        return len(self.targets)

    @property
    def target_summary(self) -> str:
        if not self.targets:
            return ""
        labels = [target.display_name or target.ip_address or target.uuid for target in self.targets]
        return "、".join(labels[:3]) + (f" 等{len(labels)}台" if len(labels) > 3 else "")

    def with_targets(self, targets: list[PowerTaskTarget]) -> "PowerTask":
        return replace(self, targets=list(targets))
