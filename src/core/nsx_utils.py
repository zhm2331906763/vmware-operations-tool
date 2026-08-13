from __future__ import annotations

import re
from typing import Iterable


NSX_KEYWORDS = (
    "nsx",
    "vxw-dvs",
    "logicalswitch",
    "transportzone",
    "n-vds",
    "opaque",
)


def is_nsx_portgroup_name(pg_name: str | None) -> bool:
    name = (pg_name or "").strip().lower()
    if not name:
        return False
    return name.startswith("vxw-") or any(keyword in name for keyword in NSX_KEYWORDS)


def split_portgroup_names(text: str | None) -> list[str]:
    value = (text or "").strip()
    if not value:
        return []

    parts = re.split(r"[\n,;]+", value)
    return [part.strip() for part in parts if part and part.strip()]


def derive_vm_nsx_managed(portgroups: str | None, extra_names: Iterable[str] | None = None) -> str:
    names = split_portgroup_names(portgroups)
    if extra_names:
        for name in extra_names:
            if name:
                names.append(str(name).strip())

    for name in names:
        if is_nsx_portgroup_name(name):
            return "是"

    return "否"
