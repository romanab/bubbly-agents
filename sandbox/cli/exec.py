import sys
import click
from sandbox.config import SandboxError, UserNotFoundError


@click.group("exec")
def exec_group():
    """Run commands inside sandboxes without an interactive login."""


@exec_group.command("run")
@click.option("--user", required=True, help="Sandbox username")
@click.option("--detach", is_flag=True, help="Fork and print PID; do not wait")
@click.argument("cmd", nargs=-1, required=True)
@click.pass_context
def exec_run(ctx, user, detach, cmd):
    """Run CMD inside USER's sandbox.

    \b
    Examples:
      sandbox-ctl exec run --user agent1 -- python3 agent.py
      sandbox-ctl exec run --user agent1 --detach -- python3 agent.py
    """
    from sandbox.exec import spawn_in_sandbox
    cfg = ctx.obj["cfg"]
    try:
        proc = spawn_in_sandbox(cfg, user, list(cmd))
    except (SandboxError, UserNotFoundError, FileNotFoundError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if detach:
        click.echo(str(proc.pid))
        return  # Python exits; bwrap survives (no --die-with-parent in exec mode)

    proc.wait()
    sys.exit(proc.returncode)
