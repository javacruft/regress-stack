from regress_stack.core import utils as core_utils
from regress_stack.modules import keystone, mysql
from regress_stack.modules import utils as module_utils

DEPENDENCIES = {keystone, mysql}
PACKAGES = ["glance-api"]
LOGS = ["/var/log/glance/"]

CONF = "/etc/glance/glance-api.conf"
URL = f"http://{core_utils.fqdn()}:9292/"
SERVICE = "glance"
SERVICE_TYPE = "image"


def setup():
    db_user, db_pass = mysql.ensure_service(SERVICE)
    username, password = keystone.ensure_service_account(SERVICE, SERVICE_TYPE, URL)
    module_utils.cfg_set(
        CONF,
        (
            "database",
            "connection",
            mysql.connection_string(SERVICE, db_user, db_pass),
        ),
        ("database", "max_pool_size", "1"),
        ("paste_deploy", "flavor", "keystone"),
        *module_utils.dict_to_cfg_set_args(
            "keystone_authtoken", keystone.authtoken_service(username, password)
        ),
        ("DEFAULT", "workers", "1"),
        ("DEFAULT", "enabled_backends", "fs:file"),
        ("glance_store", "default_backend", "fs"),
        ("fs", "filesystem_store_datadir", "/var/lib/glance/images/"),
    )
    core_utils.sudo("glance-manage", ["db_sync"], user=SERVICE)
    core_utils.restart_service("glance-api")
