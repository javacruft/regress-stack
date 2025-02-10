import logging

from regress_stack.modules import mysql, keystone, utils

PACKAGES = ["glance-api"]
LOG = logging.getLogger(__name__)

CONF = "/etc/glance/glance-api.conf"
URL = f"http://{utils.fqdn()}:9292/"
SERVICE = "glance"
SERVICE_TYPE = "image"


def setup():
    db_user, db_pass = mysql.ensure_service(SERVICE)
    username, password = keystone.ensure_service_account(SERVICE, SERVICE_TYPE, URL)
    utils.cfg_set(
        CONF,
        (
            "database",
            "connection",
            mysql.connection_string(SERVICE, db_user, db_pass),
        ),
        ("database", "max_pool_size", "1"),
        ("paste_deploy", "flavor", "keystone"),
        *utils.dict_to_cfg_set_args(
            "keystone_authtoken", keystone.authtoken_service(username, password)
        ),
        ("DEFAULT", "workers", "1"),
        ("DEFAULT", "enabled_backends", "fs:file"),
        ("glance_store", "default_backend", "fs"),
        ("fs", "filesystem_store_datadir", "/var/lib/glance/images/"),
    )
    utils.sudo("glance-manage", ["db_sync"], user=SERVICE)
    utils.restart_service("glance-api")
