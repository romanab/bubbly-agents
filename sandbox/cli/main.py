import click
import sys
from sandbox.config import load_config, SandboxError

@click.group()
@click.pass_context
def cli(ctx):
    """sandbox-ctl: Manage bubblewrap-sandboxed Linux user accounts."""
    ctx.ensure_object(dict)
    ctx.obj['cfg'] = load_config()

# Register subgroups
from sandbox.cli.users import user_group
from sandbox.cli.groups import group_group
from sandbox.cli.membership import membership_group

cli.add_command(user_group, name='user')
cli.add_command(group_group, name='group')
cli.add_command(membership_group, name='membership')

if __name__ == '__main__':
    cli()
