import functools
import logging
import socket
import subprocess
import typing

import pyroute2

LOG = logging.getLogger(__name__)

PACKAGES = ["crudini"]

REGION = "AutoPkgOne"


def setup():
    pass


def run(
    cmd: str,
    args: typing.Sequence[str],
    env: typing.Optional[typing.Dict[str, str]] = None,
    cwd: typing.Optional[str] = None,
) -> str:
    cmd_args = [cmd]
    cmd_args.extend(args)
    try:
        result = subprocess.run(
            cmd_args,
            shell=False,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd,
        )
    except subprocess.CalledProcessError as e:
        LOG.error("Command %r failed with exit code %d", cmd, e.returncode)
        LOG.error("Command %r stdout: %s", cmd, e.stdout)
        LOG.error("Command %r stderr: %s", cmd, e.stderr)
        raise e
    LOG.debug(
        "Command %r stdout: %s, stderr: %s",
        " ".join(cmd_args),
        result.stdout,
        result.stderr,
    )
    return result.stdout


def sudo(
    cmd: str, args: typing.Sequence[str], user: typing.Optional[str] = None
) -> str:
    opts = []
    if user:
        opts = ["--user", user]
    return run("sudo", opts + [cmd, *args])


def restart_service(service: str):
    run("systemctl", ["restart", service])


def restart_apache():
    restart_service("apache2")


def cfg_set(config_file: str, *args: typing.Tuple[str, str, str]) -> None:
    for section, key, value in args:
        run("crudini", ["--set", config_file, section, key, value])


def dict_to_cfg_set_args(
    section: str, d: typing.Dict[str, str]
) -> typing.List[typing.Tuple[str, str, str]]:
    return [(section, k, v) for k, v in d.items()]


@functools.lru_cache()
def fqdn() -> str:
    return run("hostname", ["-f"]).strip()


def _get_local_ip_by_default_route() -> str:
    """Get host IP from default route interface."""
    with pyroute2.NDB() as ndb:
        default_route_ifindex = ndb.routes["default"]["oif"]
        iface = ndb.interfaces[default_route_ifindex]
        ipaddr = iface.ipaddr[socket.AF_INET]["address"]
        return ipaddr


@functools.lru_cache()
def my_ip() -> str:
    try:
        return _get_local_ip_by_default_route()
    except Exception:
        LOG.exception("Failed to get local IP by default route")
        return run("hostname", ["-I"]).strip().split()[0]
