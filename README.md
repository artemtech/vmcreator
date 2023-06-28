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

Usage
===
- install (deploying) new vm
```
python3 vmcreator.py -c config.yaml install
```
- update
```
tbd
```
- destroy
```
tbd
```
