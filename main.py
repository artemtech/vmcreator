#!/usr/bin/env python3

import sys
import libvirt
import yaml
import os
import argparse
import crypt
import tempfile
import subprocess
import xml.etree.ElementTree as ET 
from shutil import copyfile, rmtree
from pprint import pprint

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

    a = subprocess.check_output(f"genisoimage -output {tmpdir}/{vm}.cloudinit.iso -V cidata -r -J {tmpdir}/user-data {tmpdir}/meta-data {tmpdir}/network-config".split(' '))
    
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
    print(vms_path)
    print(isos_path)
    
    for vm in config.get('services'):
        # generate cloudinit
        generate_cloudinit(vm, config.get('services').get(vm), vms_path)

        # generate vm disks

        # create vms

if __name__ == "__main__":
    main()