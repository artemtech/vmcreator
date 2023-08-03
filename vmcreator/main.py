#!/usr/bin/env python3

import os
import yaml
import argparse
from connection import LibvirtConnect
from instance import Instance
from network import InstanceNetwork, VirtNetwork, VirtNetworkMode
from storage import RootStorage, BasicStorage, Cloudinit


def read_config(config_file="config.yaml"):
    filepath = os.path.abspath(config_file)
    config = None
    try:
        with open(filepath, "r") as f:
            config = yaml.safe_load(f)
    except OSError as e:
        print(e)
    except yaml.YAMLError as y:
        print(y)
    return config


def main():
    arg = argparse.ArgumentParser("vmcreator")
    arg.add_argument("--config", "-c", required=True, help="config file in yaml format")
    arg.add_argument(
        "action",
        default="install",
        metavar="action",
        help="one of [install, update, destroy]",
        choices=["install", "update", "destroy"],
    )
    arg.add_argument(
        "--delete-storage",
        help="also delete storages defined in config.yaml (section services inside volumes) when action=destroy",
        action="store_true",
    )
    arg.add_argument(
        "--delete-network",
        help="also delete network defined in config.yaml (section networks outside services) when action=destroy",
        action="store_true",
    )
    args = arg.parse_args()

    config = read_config(args.config)

    if not config:
        exit(-10)

    vm_storagepool = config.get("libvirt").get("vm-pool")
    iso_storagepool = config.get("libvirt").get("iso-pool")

    for vm in config.get("services"):
        # install
        if args.action == "install":
            storages = []
            networks = []

            # generate cloudinit
            cloudinit = Cloudinit(vm, vm_storagepool, config.get("services").get(vm))
            storages.append(cloudinit)

            # generate vm disks
            disk_counter = 0
            alphabet_letter = string.ascii_lowercase
            for vol in config.get("services").get(vm).get("volumes"):
                if vol.get("type") == "root":
                    new_vol = RootStorage(
                        vm,
                        storage_pool_name=vm_storagepool,
                        disk_mount=f"vd{alphabet_letter[disk_counter]}",
                        size=vol.get("size"),
                        image=config.get("services").get(vm).get("image"),
                        image_pool=iso_storagepool,
                    )
                else:
                    new_vol = BasicStorage(
                        vm,
                        storage_pool_name=vm_storagepool,
                        disk_mount=f"vd{alphabet_letter[disk_counter]}",
                        size=vol.get("size"),
                    )
                new_vol.create()
                storages.append(new_vol)
                disk_counter += 1

            # generate networks
            for net in config.get("services").get(vm).get("networks"):
                netconfig = config.get("networks").get(net.get("name"))
                this_net = VirtNetwork(
                    net.get("name"),
                    ipcidr=netconfig.get("ipCidr"),
                    dhcp=netconfig.get("dhcp").get("enabled", False),
                    dhcp_start=netconfig.get("dhcp").get("start"),
                    dhcp_end=netconfig.get("dhcp").get("end"),
                    mode=VirtNetworkMode[netconfig.get("mode")],
                    domain=netconfig.get("domain", netconfig),
                )
                this_instancenet = InstanceNetwork(vm, net.get("ipAddr"), this_net)
                this_instancenet.create()
                networks.append(this_instancenet)

            # create vms
            instance = Instance(
                vm,
                vcpu=config.get("services").get(vm).get("cpu"),
                ram=config.get("services").get(vm).get("ram").get("size"),
                shared_ram=config.get("services").get(vm).get("ram").get("shared"),
                networks=networks,
                storages=storages,
            )
            instance.create()

        if args.action == "destroy":
            instance = Instance(vm)
            instance.delete()
            if args.delete_storage:
                pass
            pass
        print(vm)


if __name__ == "__main__":
    main()
