#!/usr/bin/env python3

import os
import yaml
import argparse
import string
from connection import LibvirtConnect
from instance import Instance
from network import InstanceNetwork, VirtNetwork, VirtNetworkMode
from storage import RootStorage, BasicStorage, Cloudinit
from typing import List


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
    arg.add_argument(
        "--debug",
        help="enable debugging",
        action="store_true",
    )
    args = arg.parse_args()

    config = read_config(args.config)

    if not config:
        exit(-10)

    vm_storagepool = config.get("libvirt").get("vm-pool")
    iso_storagepool = config.get("libvirt").get("iso-pool")

    # install
    if args.action == "install":

        for vm in config.get("services"):
            storages = []
            networks = []
            # generate cloudinit
            cloudinit = Cloudinit(
                vm_name=vm,
                storage_pool_name=vm_storagepool,
                config=config.get("services").get(vm),
                debug=args.debug,
            )
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
                        debug=args.debug,
                    )
                else:
                    new_vol = BasicStorage(
                        vm,
                        storage_pool_name=vm_storagepool,
                        disk_mount=f"vd{alphabet_letter[disk_counter]}",
                        size=vol.get("size"),
                        debug=args.debug,
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
                    mode=VirtNetworkMode[netconfig.get("mode").upper()],
                    domain=netconfig.get("domain", net.get("name")),
                    debug=args.debug,
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
                debug=args.debug,
            )
            instance.create()
            print("==============")
    # end install

    # destroy
    if args.action == "destroy":
        for vm in config.get("services"):
            networks: List[VirtNetwork] = []
            instance_networks: List[InstanceNetwork] = []

            # populate networks
            for net in config.get("services").get(vm).get("networks"):
                netconfig = config.get("networks").get(net.get("name"))

                this_net = VirtNetwork(
                    net.get("name"),
                    ipcidr=netconfig.get("ipCidr"),
                    dhcp=netconfig.get("dhcp").get("enabled", False),
                    dhcp_start=netconfig.get("dhcp").get("start"),
                    dhcp_end=netconfig.get("dhcp").get("end"),
                    mode=VirtNetworkMode[netconfig.get("mode").upper()],
                    debug=args.debug,
                    domain=netconfig.get("domain", net.get("name")),
                )
                networks.append(this_net)

                this_instancenet = InstanceNetwork(
                    vm, net.get("ipAddr"), this_net, debug=args.debug
                )
                instance_networks.append(this_instancenet)

            instance = Instance(vm, networks=instance_networks, debug=args.debug)
            try:
                print(
                    f"deleting instance {vm} with delete_storage: {args.delete_storage}"
                )
                instance.delete(args.delete_storage)
            except:
                print("unable to delete instance and storages, skipping...")
                if args.debug:
                    import traceback

                    print(traceback.format_exc())

            print(f"processed {vm}")
            print("================")

        if args.delete_network:
            print("--delete-network flag is supplied, deleting defined networks...")
            for net in networks:
                netname = net.get_name()
                net.delete()
                print(f">> {netname} successfully deleted.")
            print("all process done.")
                

    # end destroy


if __name__ == "__main__":
    main()
