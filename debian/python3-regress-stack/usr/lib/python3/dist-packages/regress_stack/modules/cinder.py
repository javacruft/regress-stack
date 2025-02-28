from regress_stack.core import utils as core_utils
from regress_stack.modules import ceph, keystone, mysql, rabbitmq
from regress_stack.modules import utils as module_utils

DEPENDENCIES = {ceph, keystone, mysql, rabbitmq}
PACKAGES = ["cinder-api", "cinder-scheduler", "cinder-volume"]
LOGS = ["/var/log/cinder/"]

CONF = "/etc/cinder/cinder.conf"
URL = f"http://{core_utils.fqdn()}:8776/v3/%(project_id)s"
SERVICE = "cinder"
SERVICE_TYPE = "volumev3"
VOLUME_POOL = "volumes"
VOLUME_USER = VOLUME_POOL


def setup():
    db_user, db_pass = mysql.ensure_service(SERVICE)
    rabbit_user, rabbit_pass = rabbitmq.ensure_service(SERVICE)
    username, password = keystone.ensure_service_account(SERVICE, SERVICE_TYPE, URL)
    pool = ceph.ensure_pool(VOLUME_POOL)
    ceph.ensure_authenticate(VOLUME_POOL, SERVICE)
    core_utils.run(
        "sed",
        [
            "-i",
            "s|cinder-wsgi processes=5 threads=1|cinder-wsgi processes=1 threads=1|",
            "/etc/apache2/conf-enabled/cinder-wsgi.conf",
        ],
    )
    module_utils.cfg_set(
        CONF,
        (
            "database",
            "connection",
            mysql.connection_string(SERVICE, db_user, db_pass),
        ),
        ("DEFAULT", "my_ip", core_utils.my_ip()),
        ("DEFAULT", "transport_url", rabbitmq.transport_url(rabbit_user, rabbit_pass)),
        ("DEFAULT", "glance_api_version", "2"),
        ("DEFAULT", "enabled_backends", "ceph"),
        ("DEFAULT", "auth_strategy", "keystone"),
        *module_utils.dict_to_cfg_set_args(
            "keystone_authtoken", keystone.authtoken_service(username, password)
        ),
        ("oslo_concurrency", "lock_path", "/var/lib/cinder/tmp"),
        *module_utils.dict_to_cfg_set_args(
            "ceph",
            {
                "volume_driver": "cinder.volume.drivers.rbd.RBDDriver",
                "volume_backend_name": "ceph",
                "rbd_cluster_name": ceph.CLUSTER,
                "rbd_ceph_conf": ceph.CONF,
                "rbd_pool": pool,
                "rbd_user": pool,
                "rbd_secret_uuid": ceph.rbd_uuid(),
                "rbd_flatten_volume_from_snapshot": "false",
                "rbd_max_clone_depth": "5",
                "rbd_store_chunk_size": "4",
                "rbd_exclusive_cinder_pool": "true",
                "backend_host": f"{SERVICE}@{core_utils.fqdn()}",
            },
        ),
    )
    core_utils.sudo("cinder-manage", ["db", "sync"], SERVICE)
    core_utils.restart_apache()
    core_utils.restart_service("cinder-scheduler")
    core_utils.restart_service("cinder-volume")
