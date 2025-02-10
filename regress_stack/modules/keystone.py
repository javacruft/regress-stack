import functools
import logging
import os
import pathlib
import typing

from regress_stack.modules import mysql, utils

PACKAGES = ["keystone", "apache2", "libapache2-mod-wsgi-py3"]
LOG = logging.getLogger(__name__)

CONF = "/etc/keystone/keystone.conf"
ADMIN_PASSWORD = "changeme"
OS_AUTH_URL = f"http://{utils.fqdn()}:5000/v3/"
SERVICE_DOMAIN = "service"
SERVICE_PROJECT = "service"


def setup():
    username, password = mysql.ensure_service("keystone")
    utils.run(
        "sed",
        [
            "-i",
            "s|keystone-public processes=5 threads=1|keystone-public processes=1 threads=1|",
            "/etc/apache2/sites-enabled/keystone.conf",
        ],
    )
    utils.cfg_set(
        CONF,
        (
            "database",
            "connection",
            mysql.connection_string("keystone", username, password),
        ),
        ("database", "max_pool_size", "1"),
        ("token", "provider", "fernet"),
    )
    LOG.debug("Running keystone-manage db_sync...")
    utils.sudo(
        "keystone-manage",
        ["--config-dir", "/etc/keystone", "db_sync"],
        user="keystone",
    )
    opts = "--keystone-user", "keystone", "--keystone-group", "keystone"
    LOG.debug("Running bootstrapping keystone...")
    utils.run("keystone-manage", ["fernet_setup", *opts])
    utils.run("keystone-manage", ["credential_setup", *opts])
    utils.run(
        "keystone-manage",
        [
            "bootstrap",
            "--bootstrap-password",
            ADMIN_PASSWORD,
            "--bootstrap-admin-url",
            OS_AUTH_URL,
            "--bootstrap-internal-url",
            OS_AUTH_URL,
            "--bootstrap-public-url",
            OS_AUTH_URL,
            "--bootstrap-region-id",
            utils.REGION,
        ],
    )
    utils.restart_apache()
    authrc = auth_rc()
    print(authrc)
    pathlib.Path("~/auth.rc").expanduser().write_text(authrc)
    ensure_domain(SERVICE_DOMAIN)
    ensure_project(SERVICE_PROJECT, SERVICE_DOMAIN)
    ensure_role("_member_")


def auth_env() -> typing.Dict[str, str]:
    return {
        "OS_USERNAME": "admin",
        "OS_PASSWORD": ADMIN_PASSWORD,
        "OS_PROJECT_NAME": "admin",
        "OS_USER_DOMAIN_NAME": "Default",
        "OS_PROJECT_DOMAIN_NAME": "Default",
        "OS_AUTH_URL": OS_AUTH_URL,
        "OS_IDENTITY_API_VERSION": "3",
        "OS_REGION_NAME": utils.REGION,
    }


def account_dict(service: str, password: str) -> typing.Dict[str, str]:
    return {
        "auth_url": OS_AUTH_URL,
        "auth_type": "password",
        "project_domain_name": SERVICE_DOMAIN,
        "user_domain_name": SERVICE_DOMAIN,
        "project_name": SERVICE_PROJECT,
        "username": service,
        "password": password,
        "region_name": utils.REGION,
    }


def authtoken_service(service: str, password: str) -> typing.Dict[str, str]:
    return {
        **account_dict(service, password),
        "www_authenticate_uri": OS_AUTH_URL,
        "service_token_roles": "admin",
        "service_token_roles_required": "true",
    }


def auth_rc():
    return "\n".join(f"export {k}={v}" for k, v in auth_env().items())


@functools.lru_cache()
def o7k():
    os.environ.update(auth_env())
    import openstack

    openstack.enable_logging(debug=True)
    conn = openstack.connect(load_envvars=True)
    return conn


@functools.lru_cache()
def region() -> str:
    conn = o7k()
    return conn.identity.find_region(utils.REGION).id


def ensure_domain(name: str):
    conn = o7k()
    LOG.debug("Ensuring domain %r exists...", name)
    if conn.identity.find_domain(name, ignore_missing=True):
        return
    LOG.debug("Creating domain %r...", name)
    conn.identity.create_domain(name=name)


@functools.lru_cache()
def service_domain() -> str:
    conn = o7k()
    return conn.identity.find_domain(SERVICE_DOMAIN).id


def ensure_project(name: str, domain: str):
    conn = o7k()
    LOG.debug("Ensuring project %r exists...", name)
    domain = service_domain()

    if conn.identity.find_project(name, domain_id=domain, ignore_missing=True):
        return
    LOG.debug("Creating project %r...", name)
    conn.identity.create_project(name=name, domain_id=domain)


@functools.lru_cache()
def service_project() -> str:
    conn = o7k()
    return conn.identity.find_project(SERVICE_PROJECT, service_domain()).id


def ensure_service_account(name: str, type: str, url: str) -> typing.Tuple[str, str]:
    """Ensure service account exists for a given service.


    Args:
        name: Name of the service.

    Returns:
        Tuple of (username, password).
    """
    password = "changeme"

    user = ensure_user(name, password, service_domain())
    ensure_admin(user, service_project())
    service = ensure_service(name, type)
    ensure_endpoint(service, url)
    return name, password


def ensure_user(name, password, domain):
    conn = o7k()
    LOG.debug("Ensuring user %r exists...", name)

    user = conn.identity.find_user(name, domain_id=domain, ignore_missing=True)
    if user:
        return user
    LOG.debug("Creating user %r...", name)
    return conn.identity.create_user(name=name, password=password, domain_id=domain)


@functools.lru_cache()
def admin_role() -> str:
    conn = o7k()
    return conn.identity.find_role("admin").id


def ensure_role(name: str):
    conn = o7k()
    LOG.debug("Ensuring role %r exists...", name)
    role = conn.identity.find_role(name, ignore_missing=True)
    if role:
        return role
    LOG.debug("Creating role %r...", name)
    return conn.identity.create_role(name=name)


def ensure_admin(user, project):
    conn = o7k()
    LOG.debug("Ensuring user %r is admin of project %r...", user.name, project)

    conn.identity.assign_project_role_to_user(project, user, admin_role())


def ensure_service(name: str, type: str):
    conn = o7k()
    LOG.debug("Ensuring service %r exists...", name)
    service = conn.identity.find_service(name, ignore_missing=True)
    if service:
        return service
    LOG.debug("Creating service %r...", name)
    return conn.identity.create_service(name=name, type=type)


def _ensure_endpoint_interface(
    conn, service, url: str, region: str, interface: str, endpoints: list
):
    for endpoint in endpoints:
        if endpoint.interface == interface:
            return endpoint

    LOG.debug("Creating endpoint %r:%s...", service.name, interface)
    return conn.identity.create_endpoint(
        service_id=service.id, url=url, interface=interface, region_id=region
    )


def ensure_endpoint(service, url: str):
    conn = o7k()
    LOG.debug("Ensuring endpoints %r exists...", service.name)
    endpoints = list(conn.identity.endpoints(service_id=service.id))
    for interface in ("public", "internal", "admin"):
        _ensure_endpoint_interface(conn, service, url, region(), interface, endpoints)
    # Clear connection after updating endpoints
    conn.close()
    o7k.cache_clear()
