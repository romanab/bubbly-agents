import click
import sys
from sandbox.config import SandboxError, UserExistsError, UserNotFoundError
from sandbox.models import UserConfig

@click.group()
def user_group():
    """User management commands."""

@user_group.command('list')
@click.pass_context
def user_list(ctx):
    """List managed sandbox users."""
    from sandbox.users import list_users
    cfg = ctx.obj['cfg']
    users = list_users(cfg)
    if not users:
        click.echo("No managed sandbox users found.")
        return
    click.echo(f"{'USER':<20} {'PROFILE':<20} {'SUPP GROUPS'}")
    click.echo("-" * 70)
    for u in users:
        supp = ",".join(u.get('supp_groups', []))
        click.echo(f"{u['username']:<20} {u.get('profile', ''):<20} {supp}")

@user_group.command('create')
@click.option('--user', required=True, help='Username to create')
@click.option('--extra-groups', default='', help='Comma-separated supplementary groups')
@click.option('--comment', default='', help='GECOS comment')
@click.option('--no-usr', is_flag=True, help='Omit /usr from sandbox')
@click.option('--sys-dirs', is_flag=True, help='Mount /etc and /run read-only')
@click.option('--fake-sudo', is_flag=True, help='Inject a sudo shim (exec wrapper, no privilege gain)')
@click.option('--network', default='full', type=click.Choice(['full','loopback','none']), help='Network mode')
@click.option('--max-procs', default='', help='Max processes (ulimit -u)')
@click.option('--max-fsize', default='', help='Max file size in MB (ulimit -f)')
@click.option('--max-nofile', default='', help='Max open file descriptors (ulimit -n)')
@click.option('--cgroup-mem', default='', help='Memory cap (e.g. 512M)')
@click.option('--cgroup-cpu', default='', help='CPU quota (e.g. 50%)')
@click.option('--extra-path', multiple=True, help='Expose host directory read-only (repeatable)')
@click.option('--dry-run', is_flag=True, help='Print actions without making changes')
@click.pass_context
def user_create(ctx, user, extra_groups, comment, no_usr, sys_dirs, fake_sudo,
                network, max_procs, max_fsize, max_nofile, cgroup_mem, cgroup_cpu,
                extra_path, dry_run):
    """Create a sandboxed system user."""
    cfg = ctx.obj['cfg']
    user_cfg = UserConfig(
        username=user,
        no_usr=no_usr,
        sys_dirs=sys_dirs,
        fake_sudo=fake_sudo,
        network=network,
        max_procs=max_procs,
        max_fsize=max_fsize,
        max_nofile=max_nofile,
        cgroup_mem=cgroup_mem,
        cgroup_cpu=cgroup_cpu,
        comment=comment,
        extra_groups=[g.strip() for g in extra_groups.split(',') if g.strip()],
        extra_paths=list(extra_path),
    )
    try:
        from sandbox.users import create_user
        create_user(cfg, user_cfg, dry_run)
        if not dry_run:
            click.echo(f"User '{user}' created successfully.")
    except (SandboxError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@user_group.command('audit')
@click.option('--user', required=True, help='Username to inspect')
@click.pass_context
def user_audit(ctx, user):
    """Inspect a sandbox user: paths, presence, and running processes."""
    cfg = ctx.obj['cfg']
    try:
        from sandbox.users import audit_user
        audit = audit_user(cfg, user)
        click.echo(f"\nAudit for user '{user}':")
        click.echo(f"  Home:       {audit['actual_home']} ({'present' if audit['home_present'] else 'missing'})")
        click.echo(f"  Launcher:   {audit['launcher']} ({'present' if audit['launcher_present'] else 'missing'})")
        click.echo(f"  Container:  {audit['user_container']} ({'present' if audit['user_container_present'] else 'missing'})")
        if audit['home_size']:
            click.echo(f"  Home size:  {audit['home_size']}")
        if audit['supp_groups']:
            click.echo(f"  Groups:     {', '.join(audit['supp_groups'])}")
        if audit['running_pids']:
            pids_str = ' '.join(str(p) for p in sorted(audit['running_pids']))
            click.echo(f"  Running:    {len(audit['running_pids'])} process(es) — PIDs: {pids_str}")
        else:
            click.echo(f"  Running:    none")
    except (SandboxError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@user_group.command('delete')
@click.option('--user', required=True, help='Username to delete')
@click.option('--keep-home', is_flag=True, help='Keep home directory')
@click.option('--force', is_flag=True, help='Force deletion even if processes running')
@click.option('--dry-run', is_flag=True, help='Print audit report only')
@click.pass_context
def user_delete(ctx, user, keep_home, force, dry_run):
    """Delete a managed sandboxed user."""
    cfg = ctx.obj['cfg']
    try:
        from sandbox.users import audit_user, delete_user
        audit = audit_user(cfg, user)
        # Print audit report
        click.echo(f"\nAudit for user '{user}':")
        click.echo(f"  Home:       {audit['actual_home']} ({'present' if audit['home_present'] else 'missing'})")
        click.echo(f"  Launcher:   {audit['launcher']} ({'present' if audit['launcher_present'] else 'missing'})")
        click.echo(f"  Container:  {audit['user_container']} ({'present' if audit['user_container_present'] else 'missing'})")
        if audit['supp_groups']:
            click.echo(f"  Groups:     {', '.join(audit['supp_groups'])}")
        if audit['private_group']:
            click.echo(f"  Private group: {audit['private_group']} (will be deleted)")
        if audit['running_pids']:
            click.echo(f"  WARNING: {len(audit['running_pids'])} process(es) running as {user}")
        if dry_run:
            click.echo("\nDry-run complete. No changes made.")
            return
        # Confirmation prompt
        confirm = click.prompt(f"\nType '{user}' to confirm deletion (Ctrl-C to abort)")
        if confirm != user:
            click.echo("Cancelled.")
            sys.exit(2)
        delete_user(cfg, user, keep_home=keep_home, force=force, dry_run=False)
        click.echo(f"User '{user}' deleted.")
    except (SandboxError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@user_group.command('profile')
@click.option('--profile', required=True, help='Profile name')
@click.option('--user', required=True, help='Username to create')
@click.option('--dry-run', is_flag=True)
@click.pass_context
def user_profile(ctx, profile, user, dry_run):
    """Apply a profile template to create a sandbox user."""
    cfg = ctx.obj['cfg']
    try:
        from sandbox.profiles import apply_profile
        apply_profile(cfg, profile, user, dry_run)
        if not dry_run:
            click.echo(f"Profile '{profile}' applied to user '{user}'.")
    except (SandboxError, ValueError, FileNotFoundError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@user_group.command('profile-list')
@click.pass_context
def user_profile_list(ctx):
    """List available profile templates."""
    from sandbox.profiles import list_profiles
    cfg = ctx.obj['cfg']
    profiles = list_profiles(cfg.project_root / "profiles")
    if not profiles:
        click.echo("No profiles available.")
        return
    click.echo(f"{'PROFILE':<20} {'DESCRIPTION'}")
    click.echo("\u2500" * 60)
    for p in profiles:
        click.echo(f"{p['name']:<20} {p['description']}")


@user_group.command('install')
@click.option('--sandbox', required=True, help='Sandbox username')
@click.option('--binary', required=True, type=click.Path(), help='Path to binary')
@click.option('--dest', default='', help='Destination path inside sandbox')
@click.option('--dry-run', is_flag=True)
@click.pass_context
def user_install(ctx, sandbox, binary, dest, dry_run):
    """Install a binary into a sandbox."""
    from pathlib import Path
    cfg = ctx.obj['cfg']
    try:
        from sandbox.installs import install_binary
        install_binary(cfg, sandbox, Path(binary), dest, dry_run)
        if not dry_run:
            click.echo(f"Installed {binary} into sandbox '{sandbox}'.")
    except (SandboxError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

@user_group.command('regen')
@click.option('--user', required=True, help='Username')
@click.pass_context
def user_regen(ctx, user):
    """Regenerate the bwrap launcher for a user (picks up script/config changes)."""
    cfg = ctx.obj['cfg']
    try:
        from sandbox.users import is_managed_user
        from sandbox.launcher import generate_launcher
        if not is_managed_user(cfg, user):
            raise UserNotFoundError(f"User {user!r} does not exist")
        generate_launcher(cfg.launcher_dir, cfg.users_dir, user)
        click.echo(f"Launcher regenerated for '{user}'.")
    except (SandboxError, ValueError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@user_group.command('run')
@click.option('--user', required=True, help='Username to run sandbox for')
@click.pass_context
def user_run(ctx, user):
    """Launch a sandbox shell for the given user."""
    import os
    cfg = ctx.obj['cfg']
    launcher = cfg.launcher_dir / f"bwrap-shell-{user}"
    if not launcher.exists():
        click.echo(f"Error: launcher not found for user '{user}'. Run 'user create' first.", err=True)
        sys.exit(1)
    from sandbox.users import write_jobctl_pids
    write_jobctl_pids(cfg, user)
    os.execv(str(launcher), [str(launcher)])

