import functools
import logging
import shutil
import typing
import uuid
from pathlib import Path

from regress_stack.modules import utils

PACKAGES = ["ceph-mgr", "ceph-mon", "ceph-osd", "ceph-volume"]
LOG = logging.getLogger(__name__)
UUID_PATH = Path("/etc/ceph/fsid")

CLUSTER = "ceph"
CONF = f"/etc/ceph/{CLUSTER}.conf"
MON_KEYRING = Path("/etc/ceph/ceph.mon.keyring")
ADMIN_KEYRING = Path("/etc/ceph/ceph.client.admin.keyring")
OSD_KEYRING = Path("/var/lib/ceph/bootstrap-osd/ceph.keyring")
MONMAP = Path("/etc/ceph/ceph.monmap")
MON_DATA_FOLDER = Path(f"/var/lib/ceph/mon/{CLUSTER}-{utils.fqdn()}")
MON_SETUP_DONE = MON_DATA_FOLDER / "done"
MGR_DATA_FOLDER = Path(f"/var/lib/ceph/mgr/{CLUSTER}-{utils.fqdn()}")
MGR_KEYRING = MGR_DATA_FOLDER / "keyring"
MGR_SETUP_DONE = MGR_DATA_FOLDER / "done"
LOOP_DEVICE_PATH = Path("/var/lib/ceph-osd")
RBD_UUID = Path("/etc/ceph/rbd_secret_uuid")

OSD_SIZE_GB = 2
BS = 4096
COUNT = (OSD_SIZE_GB * 1024**3) // BS


def setup():
    utils.cfg_set(
        CONF,
        *utils.dict_to_cfg_set_args(
            "global",
            {
                "fsid": ceph_uuid(),
                "mon host": utils.my_ip(),
                "mon initial members": utils.fqdn(),
                "public network": utils.my_network(),
                "auth cluster required": "cephx",
                "auth service required": "cephx",
                "auth client required": "cephx",
                "osd pool default size": "1",
                "osd pool default min size": "1",
                "mon warn on insecure global id reclaim": "false",
                "mon warn on insecure global id reclaim allowed": "false",
            },
        ),
    )
    ensure_ceph_folders()
    setup_mon_keyring()
    setup_mgr_keyring()
    setup_admin_keyring()
    setup_osd_keyring()
    import_keyrings()
    setup_mon()
    setup_mgr()
    for i in range(3):
        utils.exists_cache(LOOP_DEVICE_PATH / f"ceph-{i}")(setup_osd)(i)


@functools.lru_cache
def ceph_uuid() -> str:
    if UUID_PATH.exists():
        return UUID_PATH.read_text().strip()
    uuid_str = str(uuid.uuid4())
    UUID_PATH.write_text(uuid_str)
    return uuid_str


@utils.exists_cache(MON_KEYRING)
def setup_mon_keyring() -> Path:
    utils.run(
        "ceph-authtool",
        [
            "--create-keyring",
            str(MON_KEYRING),
            "--gen-key",
            "-n",
            "mon.",
            "--cap",
            "mon",
            "allow *",
        ],
    )
    utils.run(
        "ln",
        ["-s", str(MON_KEYRING), "/etc/ceph/ceph.keyring"],
    )
    shutil.chown(MON_KEYRING, user="ceph", group="ceph")
    return MON_KEYRING


@utils.exists_cache(MGR_KEYRING)
def setup_mgr_keyring() -> Path:
    utils.run(
        "ceph-authtool",
        [
            "--create-keyring",
            str(MGR_KEYRING),
            "--gen-key",
            "-n",
            "mgr." + utils.fqdn(),
            "--cap",
            "mon",
            "allow profile mgr",
            "--cap",
            "osd",
            "allow *",
            "--cap",
            "mds",
            "allow *",
        ],
    )
    shutil.chown(MGR_KEYRING, user="ceph", group="ceph")
    return MGR_KEYRING


@utils.exists_cache(ADMIN_KEYRING)
def setup_admin_keyring() -> Path:
    utils.run(
        "ceph-authtool",
        [
            "--create-keyring",
            str(ADMIN_KEYRING),
            "--gen-key",
            "-n",
            "client.admin",
            "--cap",
            "mon",
            "allow *",
            "--cap",
            "osd",
            "allow *",
            "--cap",
            "mds",
            "allow *",
            "--cap",
            "mgr",
            "allow *",
        ],
    )
    return ADMIN_KEYRING


@utils.exists_cache(OSD_KEYRING)
def setup_osd_keyring() -> Path:
    utils.run(
        "ceph-authtool",
        [
            "--create-keyring",
            str(OSD_KEYRING),
            "--gen-key",
            "-n",
            "client.bootstrap-osd",
            "--cap",
            "mon",
            "profile bootstrap-osd",
            "--cap",
            "mgr",
            "allow r",
        ],
    )
    return OSD_KEYRING


def create_keyring(name: str, caps: str) -> Path:
    keyring = Path(f"/etc/ceph/ceph.{name}.keyring")
    if keyring.exists():
        return keyring

    return keyring


def import_keyrings():
    utils.run(
        "ceph-authtool",
        [
            str(setup_mon_keyring()),
            "--import-keyring",
            str(setup_mgr_keyring()),
        ],
    )
    utils.run(
        "ceph-authtool",
        [
            str(setup_mon_keyring()),
            "--import-keyring",
            str(setup_admin_keyring()),
        ],
    )
    utils.run(
        "ceph-authtool",
        [
            str(setup_mon_keyring()),
            "--import-keyring",
            str(setup_osd_keyring()),
        ],
    )


@utils.exists_cache(MONMAP)
def monmap() -> Path:
    utils.run(
        "monmaptool",
        [
            "--create",
            "--add",
            utils.fqdn(),
            utils.my_ip(),
            "--fsid",
            ceph_uuid(),
            str(MONMAP),
        ],
    )
    return MONMAP


def ensure_ceph_folders():
    MON_DATA_FOLDER.mkdir(parents=True, exist_ok=True)
    shutil.chown(MON_DATA_FOLDER, user="ceph", group="ceph")
    MGR_DATA_FOLDER.mkdir(parents=True, exist_ok=True)
    shutil.chown(MGR_DATA_FOLDER, user="ceph", group="ceph")


@utils.exists_cache(MON_SETUP_DONE)
def setup_mon():
    utils.sudo(
        "ceph-mon",
        [
            "--mkfs",
            "--id",
            utils.fqdn(),
            "--cluster",
            CLUSTER,
            "--monmap",
            str(monmap()),
            "--keyring",
            str(MON_KEYRING),
        ],
        "ceph",
    )
    MON_SETUP_DONE.touch()
    utils.restart_service(f"ceph-mon@{utils.fqdn()}")
    return MON_SETUP_DONE


@utils.exists_cache(MGR_SETUP_DONE)
def setup_mgr():
    utils.restart_service(f"ceph-mgr@{utils.fqdn()}")
    MGR_SETUP_DONE.touch()
    return MGR_SETUP_DONE


def setup_loop_device(name: str) -> str:
    if not LOOP_DEVICE_PATH.exists():
        LOOP_DEVICE_PATH.mkdir(parents=True, exist_ok=True)
    utils.run(
        "dd",
        ["if=/dev/zero", f"of={LOOP_DEVICE_PATH / name}", f"bs={BS}", f"count={COUNT}"],
    )
    lo_device = utils.run(
        "losetup", ["--show", "--find", str(LOOP_DEVICE_PATH / name)]
    ).strip()
    LOG.debug("Created loop device %s", lo_device)
    return lo_device


def setup_osd(i: int) -> Path:
    name = f"ceph-{i}"
    lo_device = setup_loop_device(name)
    utils.run("wipefs", ["--all", lo_device])
    utils.run("sgdisk", ["--zap-all", lo_device])
    utils.run("ceph-volume", ["raw", "prepare", "--bluestore", "--data", lo_device])
    utils.run("ceph-volume", ["raw", "activate", "--osd-id", str(i)])
    utils.restart_service(f"ceph-osd@{i}")
    return LOOP_DEVICE_PATH / name


def ensure_pool(name: str) -> str:
    pools = utils.run("ceph", ["osd", "pool", "ls"]).splitlines()
    for pool in pools:
        if name == pool.strip():
            return name
    utils.run("ceph", ["osd", "pool", "create", name, "32"])
    return name


def ensure_authenticate(pool: str, user: typing.Optional[str] = None) -> Path:
    keyring = Path(f"/etc/ceph/ceph.client.{pool}.keyring")
    if keyring.exists():
        return keyring
    utils.run(
        "ceph-authtool",
        [
            "--create-keyring",
            str(keyring),
            "--gen-key",
            "-n",
            f"client.{pool}",
            "--cap",
            "mon",
            "profile rbd",
            "--cap",
            "osd",
            f"profile rbd pool={pool}",
        ],
    )
    utils.run(
        "ceph",
        ["auth", "import", "-i", str(keyring)],
    )
    if user:
        shutil.chown(keyring, user=user)
    keyring.chmod(0o600)
    return keyring


def get_key(user: str) -> str:
    return utils.run("ceph", ["auth", "get-key", f"client.{user}"]).strip()


@functools.lru_cache
def rbd_uuid() -> str:
    if RBD_UUID.exists():
        return RBD_UUID.read_text().strip()
    uuid_str = str(uuid.uuid4())
    RBD_UUID.write_text(uuid_str)
    return uuid_str
