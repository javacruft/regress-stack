import json
import logging

from regress_stack.modules import utils

PACKAGES = ["rabbitmq-server"]
LOG = logging.getLogger(__name__)
VHOST = "openstack"


def setup():
    print("Setting up RabbitMQ...")
    ensure_vhost(VHOST)


def transport_url(username: str, password: str):
    return f"rabbit://{username}:{password}@localhost:5672/{VHOST}"


def ensure_vhost(name: str):
    LOG.debug("Ensuring RabbitMQ vhost %r exists...", name)
    output = utils.run("rabbitmqctl", ["list_vhosts", "--formatter", "json"])
    for vhost in json.loads(output):
        if vhost["name"] == name:
            return
    utils.run("rabbitmqctl", ["add_vhost", name])


def ensure_service(name: str):
    password = "changeme"
    ensure_user(name, password)
    ensure_permissions(name, VHOST)
    return name, password


def ensure_user(name: str, password: str):
    LOG.debug("Ensuring RabbitMQ user %r exists...", name)
    output = utils.run("rabbitmqctl", ["list_users", "--formatter", "json"])
    for user in json.loads(output):
        if user["user"] == name:
            return
    utils.run("rabbitmqctl", ["add_user", name, password])


def ensure_permissions(user: str, vhost: str):
    LOG.debug("Ensuring RabbitMQ user %r has permissions on %r...", user, vhost)
    utils.run(
        "rabbitmqctl", ["set_permissions", "--vhost", vhost, user, ".*", ".*", ".*"]
    )
