from connection import LibvirtConnect
from abc import abstractmethod, ABC
from enum import Enum
import xml.etree.ElementTree as ET
import ipaddress
from libvirt import (
    VIR_NETWORK_UPDATE_COMMAND_ADD_LAST,
    VIR_NETWORK_SECTION_IP_DHCP_HOST,
    VIR_NETWORK_UPDATE_COMMAND_DELETE,
    VIR_NETWORK_UPDATE_AFFECT_LIVE,
    VIR_NETWORK_UPDATE_AFFECT_CONFIG,
    virNetwork,
)
import random


class Network(ABC):
    @abstractmethod
    def create(self):
        pass

    @abstractmethod
    def delete(self):
        pass

    @abstractmethod
    def get_name(self):
        pass

    @abstractmethod
    def get_network(self) -> object:
        pass

    @abstractmethod
    def get_mac(self) -> str:
        pass


class VirtNetworkMode(Enum):
    ROUTE = 1
    NAT = 2
    ISOLATED = 3


class VirtNetwork(LibvirtConnect, Network):
    def __init__(
        self,
        name: str,
        ipcidr: str = None,
        dhcp: bool = False,
        mode: VirtNetworkMode = VirtNetworkMode.ROUTE,
        dhcp_start: str = None,
        dhcp_end: str = None,
        domain: str = None,
        gateway: str = None,
        netmask: int = None,
        flag=None,
        uri: str = "qemu:///system",
    ):
        self._name = name
        self._mode = mode
        self._ipcidr = ipcidr
        self._dhcp = dhcp
        if dhcp:
            if not dhcp_start or not dhcp_end:
                print("DHCP Disabled due to dhcp_start/dhcp_end not specified")
                self._dhcp = False
        self._dhcp_start = dhcp_start
        self._dhcp_end = dhcp_end
        self._domain = domain
        self._gateway = gateway
        self._interfaces: list = None
        if flag:
            self._flag = flag
        else:
            self._flag = (
                VIR_NETWORK_UPDATE_AFFECT_LIVE | VIR_NETWORK_UPDATE_AFFECT_CONFIG
            )
        self._network: virNetwork = None
        LibvirtConnect.__init__(self, uri)

    def get_name(self):
        return self._name

    def _convert_ipcidr(self):
        ip_interface = ipaddress.ip_interface(self._ipcidr)
        self._ip = str(ip_interface.ip)
        self._netmask = str(ip_interface.netmask)
        return self._ip, self._netmask

    def get_all_interfaces(self):
        if not self._interfaces:
            self._interfaces = [
                iface.MACString() for iface in self.get_connection().listAllInterfaces()
            ]
        return self._interfaces

    def generate_mac_address(self) -> str:
        initmac_qemu = [0x52, 0x54, 0x00]

        mac = initmac_qemu + [
            random.randint(0x00, 0xFF),
            random.randint(0x00, 0xFF),
            random.randint(0x00, 0xFF),
        ]

        mac_joined = ":".join(["%02x" % x for x in mac])

        if mac_joined in self.get_all_interfaces():
            return self.generate_mac_address()
        return mac_joined

    def create(self) -> virNetwork:
        net = self.get_connection().networkLookupByName(self._name)
        if net:
            self._network = net
            return self._network

        netname = f"<name>{self._name}</name>"

        netfwmode = ""
        if self._mode.name.lower() != "isolated":
            netfwmode = f'<forward mode="{self._mode.name.lower()}"/>'

        netdomain = ""
        if self._domain:
            netdomain = f'<domain name="{self._domain}"/>'

        netaddr = ""

        netdhcp = ""
        if self._dhcp:
            netdhcp = f'<dhcp><range start="{self._dhcp_start}" end="{self._dhcp_end}"/></dhcp>'

        netip, netnetmask = self._convert_ipcidr()
        netaddr = f'<ip address="{netip}" netmask="{netnetmask}">{netdhcp}</ip>'

        networkXML = f"""
        <network connections="1">
            {netname}
            {netfwmode}
            {netdomain}
            {netaddr}
        </network>
        """
        net = self.get_connection().networkDefineXML(networkXML)
        net.create()
        self._network = self.get_connection().networkLookupByName(self._name)

        return self._network

    def create_lease(self, port):
        found = False
        for host in self.get_leases():
            if port.get("mac") == host.get("mac"):
                found = True
                break

        if found:
            print("lease already exist, skip create new lease")
            return

        dhcp_entry = f"<host mac='{port.get('mac')}' name='{port.get('name')}' ip='{port.get('ip')}'/>"
        self.get_network().update(
            VIR_NETWORK_UPDATE_COMMAND_ADD_LAST,
            VIR_NETWORK_SECTION_IP_DHCP_HOST,
            0,
            dhcp_entry,
            self._flag,
        )

    def delete_lease(self, port):
        for host in self.get_leases():
            if port.get("mac") != host.get("mac"):
                continue

            dhcp_entry = f"<host mac='{port.get('mac')}' name='{port.get('name')}' ip='{port.get('ip')}'/>"
            self.get_network().update(
                VIR_NETWORK_UPDATE_COMMAND_DELETE,
                VIR_NETWORK_SECTION_IP_DHCP_HOST,
                0,
                dhcp_entry,
                self._flag,
            )

    def get_leases(self) -> list:
        hosts = []
        root = ET.fromstring(self.get_network().XMLDesc(0))
        dhcp = root.find(".//dhcp")
        if dhcp is not None:
            for host_elem in dhcp.findall(".//host"):
                host = {
                    "mac": host_elem.get("mac"),
                    "name": host_elem.get("name"),
                    "ip": host_elem.get("ip"),
                }
                hosts.append(host)
        return hosts

    def get_network(self) -> virNetwork:
        if self._network:
            return self._network
        return self.create()

    def get_mac(self) -> virNetwork:
        if not self._ip:
            self._convert_ipcidr()
        net = self.get_network()
        netxml = net.XMLDesc(0)
        mac = netxml.split("<mac address='")[1].split("'")[0]
        return mac

    def get_host_lease(self, hostname=None, ip=None):
        if hostname:
            for host in self.get_leases():
                if host.get("hostname") != hostname:
                    continue
                return host
        if ip:
            for host in self.get_leases():
                if host.get("ip") != ip:
                    continue
                return host
        return None

    def delete(self):
        raise NotImplementedError


class InstanceNetwork(Network):
    def __init__(self, vm_name: str, ipaddress: str, network: VirtNetwork):
        self._network = network
        self._vm_name = vm_name
        self._ipaddress = ipaddress
        self._mac = None

    def create(self):
        port = {"name": self._vm_name, "ip": self._ipaddress, "mac": self.get_mac()}
        self._network.create_lease(port)
        print(port)

    def get_name(self):
        self._network.get_name()

    def get_mac(self):
        if self._mac:
            return self._mac

        # get from netlease if any
        host_lease = self._network.get_host_lease(
            hostname=self._vm_name, ip=self._ipaddress
        )
        if host_lease:
            self._mac = host_lease.get("mac")
            return self._mac

        # create mac
        self._mac = self._network.generate_mac_address()
        return self._mac

    def get_network(self) -> VirtNetwork:
        return self._network

    def delete(self):
        port = {"name": self._vm_name, "ip": self._ipaddress, "mac": self.get_mac()}
        self._network.delete_lease(port)
        self._mac = None
        print(f"deleted port: {port}")
