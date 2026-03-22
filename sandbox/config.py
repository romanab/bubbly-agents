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
    users_dir: Path      # users/<username>/ containers (replaces state_dir + homes_dir)
    groups_dir: Path
    scripts_dir: Path

    def user_home(self, username: str) -> Path:
        """Return the home directory path for a user inside their container."""
        return self.users_dir / username / f"{username}.home"


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
        users_dir=data_dir / "users",
        groups_dir=data_dir / "groups",
        scripts_dir=project_root / "scripts",
    )
