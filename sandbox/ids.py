import fcntl
from pathlib import Path


def allocate_id(data_dir: Path) -> int:
    """
    Allocate the next internal UID/GID from {data_dir}/next_id.
    Starts at 1001 if file doesn't exist. Thread/process safe via flock.
    Returns the allocated ID.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    counter_file = data_dir / "next_id"
    lock_file = data_dir / "next_id.lock"

    with lock_file.open("w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            if counter_file.exists():
                current = int(counter_file.read_text().strip())
            else:
                current = 1001
            tmp = counter_file.parent / (counter_file.name + ".tmp")
            tmp.write_text(str(current + 1) + "\n")
            tmp.rename(counter_file)
            return current
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
