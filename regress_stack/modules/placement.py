import logging

from regress_stack.modules import mysql, keystone, utils

PACKAGES = ["placement-api"]
LOG = logging.getLogger(__name__)

CONF = "/etc/placement/placement.conf"
URL = f"http://{utils.fqdn()}:8778/"


def setup():
    db_user, db_pass = mysql.ensure_service("placement")
    username, password = keystone.ensure_service_account("placement", "placement", URL)
    utils.run(
        "sed",
        [
            "-i",
            "s|placement-api processes=5 threads=1|placement-api processes=1 threads=1|",
            "/etc/apache2/sites-enabled/placement-api.conf",
        ],
    )
    utils.cfg_set(
        CONF,
        (
            "placement_database",
            "connection",
            mysql.connection_string("placement", db_user, db_pass),
        ),
        ("placement_database", "max_pool_size", "1"),
        ("api", "auth_strategy", "keystone"),
        *utils.dict_to_cfg_set_args(
            "keystone_authtoken", keystone.authtoken_service(username, password)
        ),
    )
    utils.sudo("placement-manage", ["db", "sync"], user="placement")
    utils.restart_apache()
