import json
import logging
import os
import stat
import time
from regress_stack.modules import glance, keystone, neutron, ovn, rabbitmq, mysql, utils

PACKAGES = [
    "nova-api",
    "nova-conductor",
    "nova-scheduler",
    "nova-compute",
    "nova-spiceproxy",
    "spice-html5",
]
LOG = logging.getLogger(__name__)

CONF = "/etc/nova/nova.conf"
URL = f"http://{utils.fqdn()}:8774/v2.1"


def setup():
    db_user, db_pass = mysql.ensure_service("nova")
    db_api_user, db_api_pass = mysql.ensure_service("nova_api")
    db_cell0_user, db_cell0_pass = mysql.ensure_service("nova_cell0")
    rabbit_user, rabbit_pass = rabbitmq.ensure_service("nova")
    username, password = keystone.ensure_service_account("nova", "compute", URL)

    utils.cfg_set(
        CONF,
        (
            "database",
            "connection",
            mysql.connection_string("nova", db_user, db_pass),
        ),
        ("database", "max_pool_size", "1"),
        (
            "api_database",
            "connection",
            mysql.connection_string("nova_api", db_api_user, db_api_pass),
        ),
        ("api_database", "max_pool_size", "1"),
        ("DEFAULT", "transport_url", rabbitmq.transport_url(rabbit_user, rabbit_pass)),
        ("DEFAULT", "host", utils.fqdn()),
        ("DEFAULT", "my_ip", utils.my_ip()),
        ("DEFAULT", "osapi_compute_workers", "1"),
        ("DEFAULT", "metadata_workers", "1"),
        ("conductor", "workers", "1"),
        ("scheduler", "workers", "1"),
        ("DEFAULT", "auth_strategy", "keystone"),
        *utils.dict_to_cfg_set_args(
            "keystone_authtoken", keystone.authtoken_service(username, password)
        ),
        *utils.dict_to_cfg_set_args(
            "placement", keystone.account_dict(username, password)
        ),
        *utils.dict_to_cfg_set_args(
            "neutron", keystone.account_dict(username, password)
        ),
        ("neutron", "service_metadata_proxy", "true"),
        ("neutron", "metadata_proxy_shared_secret", neutron.METADATA_SECRET),
        *utils.dict_to_cfg_set_args(
            "service_user", keystone.account_dict(username, password)
        ),
        ("service_user", "send_service_user_token", "true"),
        *utils.dict_to_cfg_set_args(
            "glance",
            {
                "service_type": glance.SERVICE_TYPE,
                "service_name": glance.SERVICE,
                "region_name": utils.REGION,
            },
        ),
        ("oslo_concurrency", "lock_path", "/var/lib/nova/tmp"),
        ("os_region_name", "openstack", utils.REGION),
        ("vnc", "enabled", "false"),
        *utils.dict_to_cfg_set_args(
            "spice",
            {
                "enabled": "true",
                "agent_enabled": "true",
                "html5proxy_base_url": f"http://{utils.my_ip()}:6082/spice_auto.html",
                "server_listen": utils.my_ip(),
                "server_proxyclient_address": utils.my_ip(),
                "keymap": "en-us",
            },
        ),
        ("libvirt", "virt_type", virt_type()),
        ("os_vif_ovs", "ovsdb_connection", ovn.OVSDB_CONNECTION),
    )

    utils.sudo("nova-manage", ["api_db", "sync"], user="nova")
    utils.sudo(
        "nova-manage",
        [
            "cell_v2",
            "map_cell0",
            "--database_connection",
            mysql.connection_string("nova_cell0", db_cell0_user, db_cell0_pass),
        ],
        user="nova",
    )
    list_cells = utils.sudo("nova-manage", ["cell_v2", "list_cells"], user="nova")
    if " cell1 " not in list_cells:
        utils.sudo(
            "nova-manage", ["cell_v2", "create_cell", "--name=cell1"], user="nova"
        )
    utils.sudo("nova-manage", ["db", "sync"], user="nova")
    utils.restart_service("nova-api")
    utils.restart_service("nova-scheduler")
    utils.restart_service("nova-conductor")
    utils.restart_service("nova-compute")
    # Give some time for nova-compute to be up before discovering hosts
    time.sleep(15)
    utils.sudo("nova-manage", ["cell_v2", "discover_hosts", "--verbose"], user="nova")


def virt_type() -> str:
    if _is_hw_virt_supported() and _is_kvm_api_available():
        return "kvm"
    return "qemu"


def _is_kvm_api_available() -> bool:
    """Determine whether KVM is supportable."""
    kvm_devpath = "/dev/kvm"
    if not os.path.exists(kvm_devpath):
        LOG.warning(f"{kvm_devpath} does not exist")
        return False
    elif not os.access(kvm_devpath, os.R_OK | os.W_OK):
        LOG.warning(f"{kvm_devpath} is not RW-accessible")
        return False
    kvm_dev = os.stat(kvm_devpath)
    if not stat.S_ISCHR(kvm_dev.st_mode):
        LOG.warning(f"{kvm_devpath} is not a character device")
        return False
    major = os.major(kvm_dev.st_rdev)
    minor = os.minor(kvm_dev.st_rdev)
    if major != 10:
        LOG.warning(f"{kvm_devpath} has an unexpected major number: {major}")
        return False
    elif minor != 232:
        LOG.warning(f"{kvm_devpath} has an unexpected minor number: {minor}")
        return False
    return True


def _is_hw_virt_supported() -> bool:
    """Determine whether hardware virt is supported."""
    cpu_info = json.loads(utils.run("lscpu", ["-J"]))["lscpu"]
    architecture = next(
        filter(lambda x: x["field"] == "Architecture:", cpu_info), {"data": ""}
    )["data"].split()
    flags = next(filter(lambda x: x["field"] == "Flags:", cpu_info), None)
    if flags is not None:
        flags = flags["data"].split()

    vendor_id = next(filter(lambda x: x["field"] == "Vendor ID:", cpu_info), None)
    if vendor_id is not None:
        vendor_id = vendor_id["data"]

    # Mimic virt-host-validate code (from libvirt) and assume nested
    # support on ppc64 LE or BE.
    if architecture in ["ppc64", "ppc64le"]:
        return True
    elif vendor_id is not None and flags is not None:
        if vendor_id == "AuthenticAMD" and "svm" in flags:
            return True
        elif vendor_id == "GenuineIntel" and "vmx" in flags:
            return True
        elif vendor_id == "IBM/S390" and "sie" in flags:
            return True
        elif vendor_id == "ARM":
            # ARM 8.3-A added nested virtualization support but it is yet
            # to land upstream https://lwn.net/Articles/812280/ at the time
            # of writing (Nov 2020).
            LOG.warning(
                "Nested virtualization is not supported on ARM" " - will use emulation"
            )
            return False
        else:
            LOG.warning(
                "Unable to determine hardware virtualization"
                f' support by CPU vendor id "{vendor_id}":'
                " assuming it is not supported."
            )
            return False
    else:
        LOG.warning(
            "Unable to determine hardware virtualization support"
            " by the output of lscpu: assuming it is not"
            " supported"
        )
        return False
