import click
import sys
from sandbox.config import SandboxError, NotManagedError

@click.group()
def membership_group():
    """Group membership management."""

@membership_group.command('add')
@click.option('--user', required=True, help='Username')
@click.option('--groups', required=True, help='Comma-separated group names to add')
@click.option('--dry-run', is_flag=True)
@click.pass_context
def membership_add(ctx, user, groups, dry_run):
    """Add user to one or more groups."""
    cfg = ctx.obj['cfg']
    from sandbox.membership import add_member
    for group in [g.strip() for g in groups.split(',') if g.strip()]:
        try:
            add_member(cfg, user, group, dry_run)
            if not dry_run:
                click.echo(f"Added '{user}' to group '{group}'.")
        except (SandboxError, NotManagedError) as e:
            click.echo(f"Error ({group}): {e}", err=True)

@membership_group.command('remove')
@click.option('--user', required=True, help='Username')
@click.option('--groups', required=True, help='Comma-separated group names to remove')
@click.option('--dry-run', is_flag=True)
@click.pass_context
def membership_remove(ctx, user, groups, dry_run):
    """Remove user from one or more groups."""
    cfg = ctx.obj['cfg']
    from sandbox.membership import remove_member
    for group in [g.strip() for g in groups.split(',') if g.strip()]:
        try:
            remove_member(cfg, user, group, dry_run)
            if not dry_run:
                click.echo(f"Removed '{user}' from group '{group}'.")
        except (SandboxError, NotManagedError) as e:
            click.echo(f"Error ({group}): {e}", err=True)
