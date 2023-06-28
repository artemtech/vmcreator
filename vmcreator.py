#!/usr/bin/env python3

import sys
import libvirt
import yaml
import os
import argparse
import crypt
import tempfile
import string
import random
import ipaddress
import subprocess
import xml.etree.ElementTree as ET 
from shutil import copyfile, rmtree

def get_all_interfaces(virsh):
    return [ iface.MACString() for iface in virsh.listAllInterfaces() ]

def generate_mac_address(virsh):
    initmac_qemu = [0x52, 0x54, 0x00]

    mac = initmac_qemu + [
            random.randint(0x00, 0xff),
            random.randint(0x00, 0xff),
            random.randint(0x00, 0xff)]
    
    mac_joined = ':'.join(["%02x" % x for x in mac])

    if mac_joined in get_all_interfaces(virsh):
        return generate_mac_address(virsh)
    return mac_joined


def read_config(config_file = "config.yaml"):
    filepath = os.path.abspath(config_file)
    config = None
    try:
        with open(filepath, 'r') as f:
            config = yaml.safe_load(f)
    except OSError as e:
        print(e)
    except yaml.YAMLError as y:
        print(y)
    return config


def connect(url = "qemu:///system"):
    conn = libvirt.open(url)
    if conn == None:
        print(f"Failed open connection to {url}", file=sys.stderr)
        exit(1)
    return conn

def network_cloudinit(configs, outdir):
    networkconfig = {}
    iface_start = 1
    networkconfig['version'] = 2
    networkconfig['ethernets'] = {}
    for net in configs.get('networks'):
        networkconfig['ethernets'][f"enp{iface_start}s0"] = {
            'dhcp4': True,
            'dhcp6': False
        }
        iface_start += 1
    with open(f"{outdir}/network-config", 'w+') as f:
        yaml.safe_dump(networkconfig, f, allow_unicode=True, sort_keys=True)
    return f"{outdir}/network-config"

def user_cloudinit(configs, outdir):
    userconfig = {}
    userconfig['fqdn'] = configs.get('fqdn', 'local')
    userconfig['timezone'] = 'Asia/Jakarta'
    userconfig['users'] = []
    for user in configs.get('users'):
        userconfig['users'].append({
            'name': user.get('name'),
            'lock_passwd': False,
            'shell': '/bin/bash',
            'sudo': 'ALL=(ALL) NOPASSWD:ALL',
            'groups': 'sudo',
            'ssh_authorized_keys': [ key for key in user.get('ssh_key') ],
            'passwd': crypt.crypt(user.get('password', 'student'))
        })
    with open(f"{outdir}/user-data", 'w+') as f:
        f.write("#cloud-config\n")
        yaml.safe_dump(userconfig, f, allow_unicode=True, sort_keys=True, width=2048)
    return f"{outdir}/user-data"

def metadata_cloudinit(vm_name, outdir):
    metadataconfig = {}
    metadataconfig['instance-id'] = f"iid-{vm_name}"
    metadataconfig['local-hostname'] = vm_name
    with open(f"{outdir}/meta-data", 'w+') as f:
        yaml.safe_dump(metadataconfig, f, allow_unicode=True, sort_keys=True, width=2048)
    return f"{outdir}/meta-data"

def generate_cloudinit(vm, configs, outdir):
    tmpdir = tempfile.mkdtemp()
    user_cloudinit(configs, tmpdir)
    network_cloudinit(configs, tmpdir)
    metadata_cloudinit(vm, tmpdir)
    # generate .iso file

    a = subprocess.check_call(f"genisoimage -output {tmpdir}/{vm}.cloudinit.iso -V cidata -r -J {tmpdir}/user-data {tmpdir}/meta-data {tmpdir}/network-config".split(' '))
    
    # copy to vms pool libvirt folder
    try:
        copyfile(f"{tmpdir}/{vm}.cloudinit.iso", f"{outdir}/{vm}.cloudinit.iso")
    except Exception as e:
        print(e)
    
    # cleanup tmpdirs
    try:
        rmtree(tmpdir)
    except Exception as e:
        print(e)
        exit(-10)
    return f"{outdir}/{vm}.cloudinit.iso"

def generate_vm(virsh, vm, configs, disks, init_disk):
    alphabet_letter = string.ascii_lowercase

    # config ram
    ram = configs.get('ram')
    ram_size = 1024
    ram_shared = True
    if ram:
        ram_size = ram.get('size')
        ram_shared = bool(ram.get('shared'))
    
    # config cpu
    cpu = configs.get('cpu', 1)
    
    # attaching disk
    disk_opt = ''
    disk_counter = 0
    for disk in disks:
        disk_opt += f'''
        <disk type="file" device="disk">
            <driver name="qemu" type="qcow2"/>
            <source file="{disk.path()}"/>
            <target dev="vd{alphabet_letter[disk_counter]}" bus="virtio"/>
        </disk>
        '''
        disk_counter += 1
    
    # attaching cloudinit disk
    disk_opt += f'''
    <disk type="file" device="cdrom">
      <driver name="qemu" type="raw"/>
      <source file="{init_disk}"/>
      <target dev="sda" bus="sata"/>
      <readonly/>
      <address type="drive" controller="0" bus="0" target="0" unit="0"/>
    </disk>
    '''
    
    # attaching network
    net_opt = ''
    dev_counter = 1
    for net in configs.get('networks'):
        ip_cidr = ipaddress.ip_interface(net.get('ipAddr'))
        net_opt += f'''
        <interface type="network">
            <mac address="{generate_mac_address(virsh)}"/>
            <source network="{net.get('name', 'default')}"/>
            <model type="virtio"/>
            <address type="pci" domain="0x0000" bus="0x0{dev_counter}" slot="0x00" function="0x0"/>
            <protocol family="ipv4">
                <ip address="{str(ip_cidr.ip)}" netmask="{str(ip_cidr.netmask)}"></ip>
            </protocol>
        </interface>
        '''
        dev_counter += 1
    
    # declare vm xml
    xml = f'''
        <domain type="kvm">
            <name>{vm}</name>
            <memory unit="MiB">{ram_size}</memory>
            <features>
              <acpi/>
              <apic/>
              <vmport state="off"/>
            </features>
            <memoryBacking>
              <source type="memfd"/>
              <access mode="shared"/>
            </memoryBacking>
            <memballoon model="virtio">
            <address type="pci" domain="0x0000" bus="0x0{dev_counter}" slot="0x00" function="0x0"/>
            </memballoon>
            <on_poweroff>destroy</on_poweroff>
            <on_reboot>restart</on_reboot>
            <on_crash>destroy</on_crash>
            <vcpu placement="static">{cpu}</vcpu>
            <os>
                <type arch="x86_64" machine="pc-q35-7.2">hvm</type>
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
    '''
    # create vm
    vm = virsh.defineXML(xml)
    
    

def generate_disks(virsh, vm, configs, isos_path, outdir):
    disksconfig = configs.get('volumes')
    storage_pool = virsh.storagePoolLookupByTargetPath(outdir)
    storages = []
    disk_counter = 0
    alphabet_letter = string.ascii_lowercase
    for disk in disksconfig:
        # if type root, generate from isos and save them in outdir
        if disk.get('type') == 'root':
            size = disk.get('size')
            image = configs.get('image')
            command = f"qemu-img create -f qcow2 -F qcow2 -b {isos_path}/{image} {outdir}/{vm}-vd{alphabet_letter[disk_counter]}.qcow2 {size}"
            r = subprocess.check_call(command.split(' '))
            storage_pool.refresh()
            new_disk = storage_pool.storageVolLookupByName(f"{vm}-vd{alphabet_letter[disk_counter]}.qcow2")
            storages.append(new_disk)
        else:
            size = disk.get('size')
            command = f"qemu-img create -f qcow2 {outdir}/{vm}-vd{alphabet_letter[disk_counter]}.qcow2 {size}"
            r = subprocess.check_call(command.split(' '))
            storage_pool.refresh()
            new_disk = storage_pool.storageVolLookupByName(f"{vm}-vd{alphabet_letter[disk_counter]}.qcow2")
            storages.append(new_disk)
        disk_counter += 1
    return storages            

def main():
    arg = argparse.ArgumentParser("vmcreator")
    arg.add_argument('--config', '-c', required=True, help="config file in yaml format")
    args = arg.parse_args()

    config = read_config(args.config)
    if not config:
        exit(-10)
    
    # connect to virsh
    virsh = connect()

    # find vm location path for copying cloudinit and generated disks
    vms_tree = ET.fromstring(virsh.storagePoolLookupByName(config.get('libvirt').get('vm-pool')).XMLDesc())
    vms_path = vms_tree.find('.//target/path').text

    # find iso location path for base image creation
    isos_tree = ET.fromstring(virsh.storagePoolLookupByName(config.get('libvirt').get('iso-pool')).XMLDesc())
    isos_path = isos_tree.find('.//target/path').text

    
    for vm in config.get('services'):
        # generate cloudinit
        this_init = generate_cloudinit(vm, config.get('services').get(vm), vms_path)

        # generate vm disks
        this_disk = generate_disks(virsh, vm, config.get('services').get(vm), isos_path, vms_path)

        # create vms
        generate_vm(virsh, vm, config.get('services').get(vm), this_disk, this_init)

        print(vm)

if __name__ == "__main__":
    main()