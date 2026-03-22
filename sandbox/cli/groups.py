import click
import subprocess
import sys
from sandbox.config import SandboxError, GroupExistsError, GroupNotFoundError

@click.group()
def group_group():
    """Group management commands."""

@group_group.command('list')
@click.pass_context
def group_list(ctx):
    """List managed shared groups."""
    from sandbox.groups import list_groups
    cfg = ctx.obj['cfg']
    groups = list_groups(cfg)
    if not groups:
        click.echo("No managed shared groups found.")
        return
    for g in groups:
        click.echo(g['groupname'])

@group_group.command('create')
@click.option('--group', required=True, help='Group name to create')
@click.option('--mode', default='u=rwx,g=rwx,o=', help='Directory permissions mode')
@click.option('--dry-run', is_flag=True)
@click.pass_context
def group_create(ctx, group, mode, dry_run):
    """Create a shared no-login group."""
    cfg = ctx.obj['cfg']
    try:
        from sandbox.groups import create_group
        create_group(cfg, group, mode, dry_run)
        if not dry_run:
            click.echo(f"Group '{group}' created.")
    except (SandboxError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@group_group.command('delete')
@click.option('--group', required=True, help='Group name to delete')
@click.option('--dry-run', is_flag=True)
@click.pass_context
def group_delete(ctx, group, dry_run):
    """Delete a managed shared group."""
    cfg = ctx.obj['cfg']
    try:
        from sandbox.groups import audit_group, delete_group
        audit = audit_group(cfg, group)
        click.echo(f"\nAudit for group '{group}':")
        click.echo(f"  GID:       {audit['gid']}")
        click.echo(f"  Directory: {audit['group_dir']} ({'present' if audit['group_dir_present'] else 'missing'})")
        if audit.get('companion_user'):
            click.echo(f"  Companion: {audit.get('companion_user')} (will be deleted)")
        if audit.get('members', []):
            click.echo(f"  Members:   {', '.join(audit.get('members', []))}")
        if dry_run:
            click.echo("\nDry-run complete.")
            return
        confirm = click.prompt(f"\nType '{group}' to confirm deletion (Ctrl-C to abort)")
        if confirm != group:
            click.echo("Cancelled.")
            sys.exit(2)
        delete_group(cfg, group, dry_run=False)
        click.echo(f"Group '{group}' deleted.")
    except (SandboxError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@group_group.command('chmod')
@click.option('--group', required=True, help='Group name')
@click.option('--mode', required=True, help='New permissions mode')
@click.option('--dry-run', is_flag=True)
@click.pass_context
def group_chmod(ctx, group, mode, dry_run):
    """Change group directory permissions."""
    cfg = ctx.obj['cfg']
    group_dir = cfg.groups_dir / group
    if dry_run:
        click.echo(f"[dry-run] would chmod {mode} {group_dir}")
        return
    if not group_dir.is_dir():
        click.echo(f"Error: group directory {group_dir} not found.", err=True)
        sys.exit(1)
    try:
        subprocess.run(["chmod", mode, str(group_dir)], check=True)
        click.echo(f"Changed permissions of {group_dir} to {mode}.")
    except subprocess.CalledProcessError as e:
        click.echo(f"Error: chmod failed: {e}", err=True)
        sys.exit(1)
