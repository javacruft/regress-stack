import contextlib
import functools
import ipaddress
import logging
import pathlib
import socket
import subprocess
import time
import typing

import pyroute2

LOG = logging.getLogger(__name__)


@contextlib.contextmanager
def measure(section: str):
    start = time.time()
    try:
        yield
    finally:
        end = time.time()
        LOG.info("%s: %.2fs", section, end - start)


def print_ascii_banner(msg: str):
    width = 80
    print("#" * width)
    print(msg.center(width, "#"))
    print("#" * width)


@contextlib.contextmanager
def banner(msg: str):
    print_ascii_banner("START " +msg)
    yield
    print_ascii_banner("END " + msg)


def measure_time(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with measure("Function " + func.__name__):
            return func(*args, **kwargs)

    return wrapper


def run(
    cmd: str,
    args: typing.Sequence[str] = (),
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


@functools.lru_cache()
def fqdn() -> str:
    return run("hostname", ["-f"]).strip()


@functools.lru_cache()
def _get_local_ip_by_default_route() -> typing.Tuple[str, int]:
    """Get host IP from default route interface."""
    with pyroute2.NDB() as ndb:
        default_route_ifindex = ndb.routes["default"]["oif"]
        iface = ndb.interfaces[default_route_ifindex]
        ipaddr = iface.ipaddr[socket.AF_INET]
        return ipaddr["address"], ipaddr["prefixlen"]


@functools.lru_cache()
def my_ip() -> str:
    try:
        return _get_local_ip_by_default_route()[0]
    except Exception:
        LOG.exception("Failed to get local IP by default route")
        return "127.0.0.1"


@functools.lru_cache()
def my_network() -> str:
    try:
        ipaddr = _get_local_ip_by_default_route()
        return str(ipaddress.ip_network(f"{ipaddr[0]}/{ipaddr[1]}", strict=False))
    except Exception:
        LOG.exception("Failed to get local IP by default route")
        return "127.0.0.1/8"


def exists_cache(path: pathlib.Path):
    """Wrapped function is not executed if resulting file exists."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if path.exists():
                return path
            result = func(*args, **kwargs)
            return result

        return wrapper

    return decorator
