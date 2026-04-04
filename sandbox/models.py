from dataclasses import dataclass, field


@dataclass
class UserConfig:
    username: str
    no_usr: bool = False
    sys_dirs: bool = False
    network: str = "full"       # "full" | "loopback" | "none"
    hostname: str = ""
    max_procs: str = ""
    max_fsize: str = ""
    max_nofile: str = ""
    cgroup_mem: str = ""
    cgroup_cpu: str = ""
    comment: str = ""
    extra_groups: list[str] = field(default_factory=list)
    fake_sudo: bool = False
    extra_paths: list[str] = field(default_factory=list)


@dataclass
class MountEntry:
    kind: str           # "--bind" | "--ro-bind" | "--overlay" etc.
    source: str
    dest: str


@dataclass
class Profile:
    name: str
    description: str
    user: UserConfig
    hostname: str
    bind_entries: list[MountEntry]
    shadow_paths: list[str]
    install_entries: list[str]  # "host_path[:dest]"
    dotfiles: list[str]
    post_setup: str
