import signal as _signal
import sys
import click
from sandbox.config import load_config, SandboxError, UserNotFoundError


@click.group()
@click.pass_context
def jobctl_group(ctx):
    """Manage processes running under sandbox users."""
    ctx.ensure_object(dict)
    ctx.obj['cfg'] = load_config()


@jobctl_group.command('list')
@click.option('--user', default=None, help='Filter by username')
@click.pass_context
def jobs_list(ctx, user):
    """List running jobs for all users or a specific user."""
    from sandbox.jobctl import get_all_jobs, get_user_jobs
    cfg = ctx.obj['cfg']
    try:
        jobs = get_user_jobs(cfg, user) if user else get_all_jobs(cfg)
    except (SandboxError, UserNotFoundError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if not jobs:
        click.echo("No jobs running.")
        return

    click.echo(f"{'USER':<15} {'PID':>7}  {'S':1}  {'ELAPSED':>9}  COMMAND")
    click.echo("-" * 72)
    for j in jobs:
        click.echo(f"{j['username']:<15} {j['pid']:>7}  {j['state']:1}  {j['elapsed']:>9}  {j['command']}")


@jobctl_group.command('kill')
@click.option('--user', required=True, help='Username')
@click.option('--pid', type=int, default=None, help='Specific PID (default: all)')
@click.option('--sig', default='TERM', show_default=True,
              help='Signal name or number (e.g. TERM, KILL, STOP, 9)')
@click.pass_context
def jobs_kill(ctx, user, pid, sig):
    """Send a signal to job(s) running under a user."""
    cfg = ctx.obj['cfg']

    # Resolve signal name/number
    try:
        signum = int(sig) if sig.isdigit() else getattr(_signal, f"SIG{sig.upper()}")
    except AttributeError:
        click.echo(f"Error: unknown signal '{sig}'", err=True)
        sys.exit(1)

    from sandbox.jobctl import send_signal
    try:
        sent = send_signal(cfg, user, sig=signum, pid=pid)
    except (SandboxError, UserNotFoundError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if sent:
        signame = _signal.Signals(signum).name
        click.echo(f"Sent {signame} to {len(sent)} process(es): {' '.join(str(p) for p in sent)}")
    else:
        click.echo("No processes matched.")
