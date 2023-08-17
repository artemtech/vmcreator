VM Creator using KVM (libvirt)
===

This is one of my python coding journey in infras project, inspired by [terraform libvirt provider](https://github.com/dmacvicar/terraform-provider-libvirt).
The flows are follow:
```
supply config.yaml -> vmcreator.py -> launched vm
```

Development
===
This script were compiled on top of Arch Linux, python 3.10, libvirt 1:8.10.0-1, cdrtools (genisoimage) 3.02a09-5, qemu-img 7.2.0-1

preqs:
- genisoimage
- qemu-img
- libvirt-python
- lxml
- pyyaml

installing:  
```bash
git clone https://github.com/artemtech/vmcreator
cd vmcreator
#----------------------------
# global install
sudo pip3 install .
#----------------------------
# install for current user only
pip3 install .
export PATH="~/.local/bin:$PATH"
#----------------------------
```

Usage
===
```bash
vmcreator --help
```
- install (deploying) new vm
```bash
vmcreator -c config.yaml install
```
- update
```bash
tbd
```
- destroy
```bash
vmcreator -c config.yaml destroy

# if with storage
vmcreator -c config.yaml destroy --delete-storage

# if with network
vmcreator -c config.yaml destroy --delete-network

# destroy all
vmcreator -c config.yaml destroy --delete-storage --delete-network
```
