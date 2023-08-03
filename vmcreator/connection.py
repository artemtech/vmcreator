import libvirt

class LibvirtConnect:
    def __init__(self, uri = "qemu:///system"):
        self._conn = libvirt.open(uri)
        if self._conn == None:
            print(f"Failed open connection to {uri}", file=sys.stderr)
            exit(1)
    
    def get_connection(self):
        return self._conn