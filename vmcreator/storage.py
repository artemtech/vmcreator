from connection import LibvirtConnect
from libvirt import virStoragePool, virStorageVol
from abc import abstractmethod
import xml.etree.ElementTree as ET


class StorageNotFoundException(Exception):
    def __init__(self, message):
        super(self, message)


class Storage(LibvirtConnect):
    def __init__(self, vm_name, storage_pool_name, uri: str = "qemu:///system"):
        self._storage_pool_name = storage_pool_name
        self._vm_name = vm_name
        self._disk: virStorageVol = None
        super(uri)

    @abstractmethod
    def create(self) -> None:
        pass
    
    @abstractmethod
    def delete(self) -> None:
        pass

    def get_pool_path(self, name) -> str:
        # retrieve abs path of pool
        xml_tree = ET.fromstring(
            self.get_connection().storagePoolLookupByName(name).XMLDesc()
        )
        return xml_tree.find(".//target/path").text

    def get_storage_pool(self) -> virStoragePool:
        return self.get_connection().storagePoolLookupByName(self._storage_pool_name)

    def get_disk(self) -> virStorageVol:
        if not self._disk:
            self.generate_disk()
        return self._disk


class RootStorage(Storage):
    def __init__(
        self,
        vm_name,
        storage_pool_name='default',
        disk_mount='vda',
        size='1G',
        image=None,
        image_pool='default',
        uri: str = "qemu:///system",
    ):
        super(vm_name, storage_pool_name, uri)
        self._size = size
        self._image = image
        self._image_pool = image_pool
        self._disk_mount = disk_mount

    def create(self):
        disk = self.get_storage_pool().storageVolLookupByName(
            f"{self._vm_name}-{self._disk_mount}.qcow2"
        )
        if disk:
            self._disk = disk
            return

        vm_path = self.get_pool_path(self._storage_pool_name)
        isos_path = self.get_pool_path(self._image_pool)

        command = f"qemu-img create -f qcow2 -F qcow2 -b {isos_path}/{self._image} {vm_path}/{self._vm_name}-root-{self._disk_mount}.qcow2 {self._size}"
        r = subprocess.check_call(command.split(" "))
        self.get_storage_pool().refresh()
        self._disk = self.get_storage_pool().storageVolLookupByName(
            f"{self._vm_name}-root-{self._disk_mount}.qcow2"
        )

    def delete(self):
        volumes : List[virStorageVol] = self.get_storage_pool().listVolumes()
        for volume in volumes:
            print(volume)
        raise NotImplementedError

class BasicStorage(Storage):
    def __init__(
        self, vm_name, storage_pool_name='default', disk_mount='vdb', size='1G', uri: str = "qemu:///system"
    ):
        super(vm_name, storage_pool_name, uri)
        self._size = size
        self._disk_mount = disk_mount

    def create(self):
        disk = self.get_storage_pool().storageVolLookupByName(
            f"{self._vm_name}-{self._disk_mount}.qcow2"
        )
        if disk:
            self._disk = disk
            return

        vm_path = self.get_pool_path(self._storage_pool_name)

        command = f"qemu-img create -f qcow2 {self._output} {self._size}"
        r = subprocess.check_call(command.split(" "))
        self.get_storage_pool().refresh()
        self._disk = self.get_storage_pool().storageVolLookupByName(
            f"{self._vm_name}-{self._disk_mount}.qcow2"
        )

    def delete(self):
        raise NotImplementedError


class Cloudinit(Storage):
    def __init__(
        self,
        vm_name,
        storage_pool_name='default',
        config=None,
        force=False,
        uri: str = "qemu:///system",
    ):
        super(vm_name, storage_pool_name, uri)
        self._config = config
        self._force_create = force

    def create(self):
        vm_path = self.get_pool_path(self._storage_pool_name)
        cloudinit_path = f"{vm_path}/{self._vm_name}.cloudinit.iso"

        if os.path.exists(cloudinit_path):
            if self._force_create:
                self.__do_generate()
            self._disk = cloudinit_path
            return

        self.__do_generate()
        self._disk = cloudinit_path
    
    def delete(self):
        raise NotImplementedError

    def __do_generate(self):
        tmpdir = tempfile.mkdtemp()

        user = self.__userinit(tmpdir)
        metadata = self.__metadatainit(tmpdir)
        network = self.__networkinit(tmpdir)

        # generate .iso file
        cmd = f"genisoimage -output {tmpdir}/{self._vm_name}.cloudinit.iso -V cidata -r -J {user} {metadata} {network}"
        a = subprocess.check_call(cmd.split(" "))

        # copy to vms pool libvirt folder
        try:
            copyfile(
                f"{tmpdir}/{self._vm_name}.cloudinit.iso",
                f"{self._outdir}/{self._vm_name}.cloudinit.iso",
            )
        except Exception as e:
            print(e)

        # cleanup tmpdirs
        try:
            rmtree(tmpdir)
        except Exception as e:
            print(e)
            exit(-10)

    def __metadatainit(self, outdir):
        metadataconfig = {}
        metadataconfig["instance-id"] = f"iid-{self._vm_name}"
        metadataconfig["local-hostname"] = self._vm_name

        with open(f"{outdir}/meta-data", "w+") as f:
            yaml.safe_dump(
                metadataconfig, f, allow_unicode=True, sort_keys=True, width=2048
            )

        return f"{outdir}/meta-data"

    def __userinit(self, outdir):
        userconfig = {}
        userconfig["fqdn"] = self._config.get("fqdn", "local")
        userconfig["timezone"] = self._config.get("timezone", "UTC")
        userconfig["users"] = []

        for user in self._config.get("users"):
            userconfig["users"].append(
                {
                    "name": user.get("name"),
                    "lock_passwd": False,
                    "shell": "/bin/bash",
                    "sudo": "ALL=(ALL) NOPASSWD:ALL",
                    "groups": "sudo",
                    "ssh_authorized_keys": [key for key in user.get("ssh_key")],
                    "passwd": crypt.crypt(user.get("password", "student")),
                }
            )

        with open(f"{outdir}/user-data", "w+") as f:
            f.write("#cloud-config\n")
            yaml.safe_dump(
                userconfig, f, allow_unicode=True, sort_keys=True, width=2048
            )

        return f"{outdir}/user-data"

    def __networkinit(self, outdir):
        networkconfig = {}
        iface_start = 1
        networkconfig["version"] = 2
        networkconfig["ethernets"] = {}

        for net in self._config.get("networks"):
            networkconfig["ethernets"][f"enp{iface_start}s0"] = {
                "dhcp4": True,
                "dhcp6": False,
            }
            iface_start += 1

        with open(f"{outdir}/network-config", "w+") as f:
            yaml.safe_dump(networkconfig, f, allow_unicode=True, sort_keys=True)

        return f"{outdir}/network-config"
