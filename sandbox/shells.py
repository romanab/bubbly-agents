def is_in_shells(entry: str) -> bool:
    """No-op in rootless mode: /etc/shells management is not needed."""
    return False


def add_to_shells(entry: str, dry_run: bool = False) -> None:
    """No-op in rootless mode: /etc/shells management is not needed."""


def remove_from_shells(entry: str, dry_run: bool = False) -> None:
    """No-op in rootless mode: /etc/shells management is not needed."""
