import argparse
import contextlib
import logging
import typing
from pprint import pprint

import regress_stack.modules
from regress_stack.core.modules import get_execution_order, modules
from regress_stack.modules import keystone, utils

LOG = logging.getLogger(__name__)

CIRROS = "http://download.cirros-cloud.net/0.6.2/cirros-0.6.2-x86_64-disk.img"


def plan(target: typing.Optional[str]):
    order = get_execution_order(regress_stack.modules, target)
    print(
        "Execution Order:",
    )
    pprint(order)


@contextlib.contextmanager
def measure(section: str):
    import time

    start = time.time()
    try:
        yield
    finally:
        end = time.time()
        LOG.info("%s: %.2fs", section, end - start)


def measure_time(func):
    def wrapper(*args, **kwargs):
        with measure("Function " + func.__name__):
            return func(*args, **kwargs)

    return wrapper


@measure_time
def setup(target: str):
    for mod in get_execution_order(regress_stack.modules, target):
        if setup := getattr(mod.module, "setup", None):
            with measure("setup " + mod.name):
                setup()


@measure_time
def test():
    env = keystone.auth_env()
    utils.run("tempest", ["init", "mycloud01"])
    utils.run(
        "discover-tempest-config",
        ["--create"],  # , "--image", CIRROS, "--convert-to-raw"
        env=env,
        cwd="mycloud01",
    )
    # utils.run("tempest", ["run", "--smoke"], env=env, cwd="mycloud01")


def list_modules():
    _ = get_execution_order(regress_stack.modules)
    for module in modules():
        print(module)


def main():
    parser = argparse.ArgumentParser(
        prog="openstack-deb-tester",
        description="A CLI tool for testing OpenStack Debian packages.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common_arguments(subparser):
        subparser.add_argument("target", nargs="?", help="Target to test (optional).")

    parser_plan = subparsers.add_parser("plan", help="Plan the test execution.")
    add_common_arguments(parser_plan)

    parser_setup = subparsers.add_parser("setup", help="Execute the tests.")
    add_common_arguments(parser_setup)

    subparsers.add_parser("test", help="Run the tests.")

    subparsers.add_parser("list-modules", help="List available modules.")

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)

    if args.command == "plan":
        plan(args.target)
    elif args.command == "setup":
        setup(args.target)
    elif args.command == "test":
        test()
    elif args.command == "list-modules":
        list_modules()


if __name__ == "__main__":
    main()
