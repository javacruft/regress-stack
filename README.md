
echo Acquire::http::Proxy "http://squid.lxd:3128" > /etc/apt/apt.conf.d/00-proxy
apt update
apt install -y python3-networkx python3-apt crudini keystone mysql-server placement-api python3-openstackclient tempest python3-tempestconf

lxc launch ubuntu:22.04 --vm --config limits.cpu=2 --config limits.memory=4GiB -d root,size=80GiB --config user.user-data="$(cat /home/gboutry/Documents/canonical/projects/openstack/openstack-deb-tester/cloud-init.yaml)" --profile ubuntu --profile default microstack
