from dataclasses import dataclass
from pathlib import Path
import os


class SandboxError(Exception):
    pass


class UserExistsError(SandboxError):
    pass


class UserNotFoundError(SandboxError):
    pass


class GroupExistsError(SandboxError):
    pass


class GroupNotFoundError(SandboxError):
    pass


class NotManagedError(SandboxError):
    pass


@dataclass
class SandboxConfig:
    project_root: Path
    data_dir: Path       # low_priv_user_dirs/
    launcher_dir: Path
    state_dir: Path
    homes_dir: Path
    groups_dir: Path
    scripts_dir: Path


def load_config() -> SandboxConfig:
    """Load config, honouring SANDBOX_DATA_DIR env var override."""
    project_root = Path(
        os.environ.get("SANDBOX_PROJECT_ROOT", Path(__file__).parent.parent)
    )

    data_dir = Path(
        os.environ.get("SANDBOX_DATA_DIR", project_root / "low_priv_user_dirs")
    )

    return SandboxConfig(
        project_root=project_root,
        data_dir=data_dir,
        launcher_dir=data_dir / "launchers",
        state_dir=data_dir / "state",
        homes_dir=data_dir / "homes",
        groups_dir=data_dir / "groups",
        scripts_dir=project_root / "scripts",
    )
