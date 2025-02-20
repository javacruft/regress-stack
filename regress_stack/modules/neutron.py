import ipaddress
import logging
import time

from regress_stack.modules import keystone, mysql, ovn, rabbitmq, utils

PACKAGES = ["neutron-server", "neutron-ovn-metadata-agent"]
LOG = logging.getLogger(__name__)

CONF = "/etc/neutron/neutron.conf"
METADATA_AGENT_CONF = "/etc/neutron/neutron_ovn_metadata_agent.ini"
ML2_CONF = "/etc/neutron/plugins/ml2/ml2_conf.ini"
URL = f"http://{utils.fqdn()}:9696/"

METADATA_SECRET = "bonjour"


def setup():
    db_user, db_pass = mysql.ensure_service("neutron")
    rabbit_user, rabbit_pass = rabbitmq.ensure_service("neutron")
    username, password = keystone.ensure_service_account("neutron", "network", URL)
    utils.cfg_set(
        CONF,
        (
            "database",
            "connection",
            mysql.connection_string("neutron", db_user, db_pass),
        ),
        ("database", "max_pool_size", "1"),
        *utils.dict_to_cfg_set_args(
            "DEFAULT",
            {
                "core_plugin": "ml2",
                "service_plugins": "metering,segments,ovn-router,port_forwarding,trunk",
                "router_distributed": "false",
                "l3_ha": "false",
                "allow_automatic_l3agent_failover": "false",
                "allow_automatic_dhcp_failover": "true",
                "network_scheduler_driver": "neutron.scheduler.dhcp_agent_scheduler.AZAwareWeightScheduler",
                "dhcp_load_type": "networks",
                "router_scheduler_driver": "neutron.scheduler.l3_agent_scheduler.AZLeastRoutersScheduler",
                "dhcp_agents_per_network": "1",
            },
        ),
        ("DEFAULT", "api_workers", "1"),
        ("DEFAULT", "rpc_workers", "1"),
        ("DEFAULT", "transport_url", rabbitmq.transport_url(rabbit_user, rabbit_pass)),
        ("DEFAULT", "notify_nova_on_port_status_changes", "true"),
        ("DEFAULT", "notify_nova_on_port_data_changes", "true"),
        ("oslo_concurrency", "lock_path", "/var/lib/neutron/tmp"),
        *utils.dict_to_cfg_set_args("nova", keystone.account_dict(username, password)),
        *utils.dict_to_cfg_set_args(
            "placement", keystone.account_dict(username, password)
        ),
        ("DEFAULT", "auth_strategy", "keystone"),
        *utils.dict_to_cfg_set_args(
            "keystone_authtoken", keystone.authtoken_service(username, password)
        ),
    )
    utils.cfg_set(
        ML2_CONF,
        *utils.dict_to_cfg_set_args(
            "ml2",
            {
                "extension_drivers": "port_security,qos,dns_domain_ports,port_forwarding,uplink_status_propagation",
                "type_drivers": "geneve,vlan,flat",
                "tenant_network_types": "geneve,vlan,flat",
                "mechanism_drivers": "ovn",
            },
        ),
        ("ml2_type_vlan", "network_vlan_ranges", "physnet1:1:4094"),
        ("ml2_type_flat", "flat_networks", "physnet1"),
        ("ml2_type_geneve", "vni_ranges", "1:65535"),
        ("ml2_type_geneve", "max_header_size", "38"),
        ("securitygroup", "enable_security_group", "true"),
        ("ovs", "enable_tunneling", "true"),
        ("ovs", "igmp_snooping_enable", "false"),
        *utils.dict_to_cfg_set_args(
            "ovn",
            {
                "ovn_nb_connection": ovn.OVNNB_CONNECTION,
                "ovn_sb_connection": ovn.OVNSB_CONNECTION,
                "ovn_l3_scheduler": "leastloaded",
                "ovn_metadata_enabled": "true",
                "enable_distributed_floating_ip": "true",
                "dhcp_default_lease_time": "600",
            },
        ),
    )
    utils.cfg_set(
        METADATA_AGENT_CONF,
        ("DEFAULT", "nova_metadata_host", utils.fqdn()),
        ("DEFAULT", "metadata_proxy_shared_secret", METADATA_SECRET),
        ("ovs", "ovsdb_connection", ovn.OVSDB_CONNECTION),
        ("ovn", "ovn_sb_connection", ovn.OVNSB_CONNECTION),
    )
    utils.sudo(
        "neutron-db-manage",
        ["--config-file", CONF, "--config-file", ML2_CONF, "upgrade", "head"],
        user="neutron",
    )
    utils.restart_service("neutron-server")
    utils.restart_service("neutron-ovn-metadata-agent")
    # wait for neutron-server to accept http connections
    for _ in range(10):
        try:
            ensure_public_network()
            break
        except Exception as e:
            if "Connection refused" in str(e):
                LOG.debug("Waiting for neutron-server to start...")
                time.sleep(1)
                continue
            raise e


def ensure_public_network():
    """"""
    conn = keystone.o7k()

    # create external network
    network = conn.network.find_network("external-network", ignore_missing=True)
    if not network:
        network = conn.network.create_network(
            name="external-network",
            is_router_external=True,
            is_shared=True,
            is_default=True,
            provider_network_type="flat",
            provider_physical_network="physnet1",
        )

    subnet = conn.network.find_subnet("external-subnet", ignore_missing=True)
    if not subnet:
        ip_net = ipaddress.ip_network(ovn.EXTERNAL_CIDR)
        hosts = list(ip_net.hosts())
        gw = hosts[0]
        first_host = hosts[1]
        last_host = hosts[-2]
        conn.network.create_subnet(
            name="external-subnet",
            network_id=network.id,
            ip_version=4,
            cidr=ovn.EXTERNAL_CIDR,
            gateway_ip=str(gw),
            allocation_pools=[{"start": str(first_host), "end": str(last_host)}],
            enable_dhcp=False,
        )
