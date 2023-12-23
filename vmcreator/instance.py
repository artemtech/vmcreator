from typing import List
from vmcreator.connection import LibvirtConnect
from vmcreator.network import Network
from vmcreator.storage import Storage, Cloudinit
from libvirt import virDomain
import string
import xml.etree.ElementTree as ET


class Instance(LibvirtConnect):
    def __init__(
        self,
        name: str,
        vcpu: int = 1,
        ram: int = 512,
        shared_ram: bool = True,
        networks: List[Network] = None,
        storages: List[Storage] = None,
        debug: bool = False,
        uri: str = "qemu:///system",
    ):
        super(Instance, self).__init__(uri)

        self._name = name
        self._vcpu = vcpu
        self._ram = ram
        self._shared_ram = shared_ram

        self._storages = storages
        if storages is None:
            self._storages = []

        self._networks = networks
        if networks is None:
            self._networks = []

        self._debug = debug
        self._instance = None
        self._xml = None

    def get_instance(self) -> virDomain:
        if not self._instance:
            self.create()
        self._xml = ET.fromstring(self._instance.XMLDesc())
        return self._instance

    def get_networks(self):
        return self._networks

    def create(self) -> virDomain:
        try:
            instance = self.get_connection().lookupByName(self._name)
            self._instance = instance
            return
        except:
            print(f"Instance {self._name} not found. Creating...")
            if self._debug:
                import traceback
                print(traceback.format_exc())

        dev_counter = 1

        ram_size = f'<memory unit="MiB">{self._ram}</memory>'

        ram_config = ""
        if self._shared_ram:
            ram_config = f"""
            <memoryBacking>
              <source type="memfd"/>
              <access mode="shared"/>
            </memoryBacking>
            <memballoon model="virtio">
            <address type="pci" domain="0x0000" bus="0x0{dev_counter}" slot="0x00" function="0x0"/>
            </memballoon>
            """

        # cpu configs
        cpu = f'<cpu mode="host-passthrough"></cpu><vcpu placement="static">{self._vcpu}</vcpu>'

        # storage config
        disk_opt = ""
        disk_counter = 0
        alphabet_letter = string.ascii_lowercase
        for disk in self._storages:
            if type(disk) == Cloudinit:
                # attaching cloudinit disk
                disk_opt += f"""
                <disk type="file" device="cdrom">
                <driver name="qemu" type="raw"/>
                <source file="{disk.get_disk().path()}"/>
                <target dev="sda" bus="sata"/>
                <readonly/>
                <address type="drive" controller="0" bus="0" target="0" unit="0"/>
                </disk>
                """
            else:
                disk_opt += f"""
                <disk type="file" device="disk">
                    <driver name="qemu" type="qcow2"/>
                    <source file="{disk.get_disk().path()}"/>
                    <target dev="vd{alphabet_letter[disk_counter]}" bus="virtio"/>
                </disk>
                """
            disk_counter += 1

        # network config
        net_opt = ""
        for net in self._networks:
            this_mac = net.get_mac()

            net_opt += f"""
            <interface type="network">
                <mac address="{net.get_mac()}"/>
                <source network="{net.get_name()}"/>
                <model type="virtio"/>
                <address type="pci" domain="0x0000" bus="0x0{dev_counter}" slot="0x00" function="0x0"/>
            </interface>
            """
            dev_counter += 1

        # instance define
        instanceXML = f"""
        <domain type="kvm">
            <name>{self._name}</name>
            <features>
              <acpi/>
              <apic/>
              <vmport state="off"/>
            </features>
            {ram_size}
            {ram_config}
            <on_poweroff>destroy</on_poweroff>
            <on_reboot>restart</on_reboot>
            <on_crash>destroy</on_crash>
            {cpu}
            <os>
                <type arch="x86_64" machine="q35">hvm</type>
                <boot dev="hd"/>
            </os>
            <devices>
                {disk_opt}
                {net_opt}
                <serial type="pty">
                <target type="isa-serial" port="0">
                    <model name="isa-serial"/>
                </target>
                </serial>
                <console type="pty">
                <target type="serial" port="0"/>
                </console>
                <channel type="spicevmc">
                <target type="virtio" name="com.redhat.spice.0"/>
                <address type="virtio-serial" controller="0" bus="0" port="1"/>
                </channel>
                <input type="tablet" bus="usb">
                <address type="usb" bus="0" port="1"/>
                </input>
                <input type="mouse" bus="ps2"/>
                <input type="keyboard" bus="ps2"/>
                <graphics type="spice" autoport="yes">
                <listen type="address"/>
                <image compression="off"/>
                </graphics>
                <sound model="ich6">
                <address type="pci" domain="0x0000" bus="0x00" slot="0x04" function="0x0"/>
                </sound>
                <audio id="1" type="spice"/>
                <video>
                <model type="qxl" ram="65536" vram="65536" vgamem="16384" heads="1" primary="yes"/>
                <address type="pci" domain="0x0000" bus="0x00" slot="0x02" function="0x0"/>
                </video>
                <redirdev bus="usb" type="spicevmc">
                <address type="usb" bus="0" port="2"/>
                </redirdev>
                <redirdev bus="usb" type="spicevmc">
                <address type="usb" bus="0" port="3"/>
                </redirdev>
            </devices>
        </domain>
        """

        instance = self.get_connection().defineXML(instanceXML)
        instance.create()

        self._instance = self.get_connection().lookupByName(self._name)
        print(f"Instance {self._name} successfully created.")

        return self._instance

    def get_associated_storages(self):
        instance = self.get_instance()

        root = ET.fromstring(instance.XMLDesc())
        disks = root.findall(".//disk/source")

        for disk in disks:
            d = self.get_connection().storageVolLookupByPath(disk.get("file"))

            storage = Storage.from_virsh(d)

            self._storages.append(storage)

        return self._storages

    def delete(self, with_storage: bool = False):
        instance = self.get_instance()

        disks = self.get_associated_storages()

        if instance.isActive():
            instance.destroy()
        instance.undefine()

        # delete if we have storage
        if with_storage:
            for disk in disks:
                print(f"deleting storage: {disk.get_disk().name()}")
                disk.delete()

        # delete dhcp lease in network
        for network in self.get_networks():
            network.delete()
