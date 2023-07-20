#!/usr/bin/env python3

import argparse
import json
import subprocess
import os
import wget
import tarfile
from threading import Thread, Event
import time
import shutil
import git


class DcsDeploy:
    def __init__(self):
        self.parser = self.create_parser()
        self.args = self.parser.parse_args()
        self.sanitize_args()
        self.load_db()
        if self.args.command != 'list':
            self.load_selected_config()
            self.init_filesystem()

    def add_common_parser(self, subparser):
        target_device_help = 'REQUIRED. Which type of device are we setting up. Options: [xavier_nx]'
        subparser.add_argument(
            'target_device', help=target_device_help)

        jetpack_help = 'REQUIRED. Which jetpack are we going to use. Options: [51].'
        subparser.add_argument(
            'jetpack', help=jetpack_help)

        hwrev_help = 'REQUIRED. Which hardware revision of carrier board are we going to use. Options: [1.2].'
        subparser.add_argument(
            'hwrev', help=hwrev_help)
        
        storage_help = 'REQUIRED. Which storage medium are we going to use. Options: [emmc, nvme].'
        subparser.add_argument(
            'storage', help=storage_help)
        
        force_help = 'Files will be deleted, downloaded and extracted again.'
        subparser.add_argument(
            '--force', action='store_true',  default='', help=force_help)

    def create_parser(self):
        """
        Create an ArgumentParser and all its options
        """
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest='command', help='Command')

        list = subparsers.add_parser(
            'list', help='list available versions')

        flash = subparsers.add_parser(
            'flash', help='Run the entire flash process')
        

        self.add_common_parser(flash)
        
        return parser
    
    def sanitize_args(self):
        """
        Check if the supplied arguments are valid and perform some fixes
        """
        if self.args.command is None:
            print("No command specified!")
            self.parser.print_usage()
            quit()

    def load_db(self):
        db_file = open('local/config_db.json')

        self.config_db = json.load(db_file)

    def loading_animation(self, event):
        """Just animate rotating line - | / — \
        """
        cnt = 0

        while True:
            if cnt == 0:
                print ("\r | ", end="")
            elif cnt == 1:  
                print ("\r / ", end="")
            elif cnt == 2:
                print ("\r — ", end="")
            elif cnt == 3:
                print ("\r \\ ", end="")

            cnt += 1
            cnt %= 4
            time.sleep(0.5)
            
            if event.is_set():
                print()
                return

    def save_downloaded_versions(self):
        if os.path.isfile(self.downloaded_config_path):
            with open(self.downloaded_config_path, "r+") as download_dict:
                file_data = json.load(download_dict)
                file_data[self.current_config_name] = self.config
                download_dict.seek(0)
                json.dump(file_data, download_dict, indent = 4)
        else:
            with open(self.downloaded_config_path, "a") as download_dict:
                config_to_save = {}
                config_to_save[self.current_config_name] = self.config
                json.dump(config_to_save, download_dict, indent=4)

    def run_loading_animation(self, event):
        t = Thread(target=self.loading_animation, args=(event,))
        t.start()
        return t

    def init_filesystem(self):
        config_relative_path = (
            self.config['device'] + '_' + 
            self.config['storage'] + '_' + 
            self.config['board'] + '_' +
            self.config['l4t_version']
        )

        self.home = os.path.expanduser('~')
        self.dsc_deploy_root = os.path.join(self.home, '.dcs_deploy')
        self.download_path = os.path.join(self.dsc_deploy_root, 'download', config_relative_path)
        self.flash_path = os.path.join(self.dsc_deploy_root, 'flash', config_relative_path)
        self.rootfs_file_path = os.path.join(self.download_path, 'rootfs.tbz2')
        self.l4t_file_path = os.path.join(self.download_path, 'l4t.tbz2')
        self.nvidia_overlay_file_path = os.path.join(self.download_path, 'nvidia_overlay.tbz2')
        self.airvolute_overlay_file_path = os.path.join(self.download_path, 'airvolute_overlay.tbz2')
        self.rootfs_extract_dir = os.path.join(self.flash_path, 'Linux_for_Tegra', 'rootfs')
        self.l4t_root_dir = os.path.join(self.flash_path, 'Linux_for_Tegra')
        self.downloaded_config_path = os.path.join(self.dsc_deploy_root, 'downloaded_versions.json')
        self.apply_binaries_path = os.path.join(self.l4t_root_dir, 'apply_binaries.sh')
        self.create_user_script_path = os.path.join(self.l4t_root_dir, 'tools', 'l4t_create_default_user.sh')
        self.first_boot_file_path = os.path.join(self.rootfs_extract_dir, 'etc', 'first_boot')

        if self.config['device'] == 'xavier_nx': 
            self.device_type = 't194'

        # Handle dcs-deploy root dir
        if not os.path.isdir(self.dsc_deploy_root):
            os.mkdir(self.dsc_deploy_root)

        # Handle dcs-deploy download dir
        if not os.path.isdir(self.download_path):
            os.makedirs(self.download_path)

        # Handle dcs-deploy flash dir
        if not os.path.isdir(self.flash_path):
            os.makedirs(self.flash_path)
        else:
            print('Removing previous L4T folder ...')
            subprocess.call(
                [
                    'sudo',
                    'rm', 
                    '-r', 
                    self.flash_path,
                ]
            )
            os.makedirs(self.flash_path)

    def compare_downloaded_source(self):
        """Compares current input of the program with previously 
        downloaded sources.

        return True, if sources are already present locally.
        return False, if sources need to be downloaded.
        """
        if self.args.force == True:
            return False

        if os.path.exists(self.downloaded_config_path):
            downloaded_configs = json.load(open(self.downloaded_config_path))

            for config in downloaded_configs:
                if config == self.current_config_name:
                    print('Resources for your config are already downloaded!')
                    return True
            
            print('New resources will be downloaded!')
            return False

        else:
            return False

    
    def download_resources(self):
        if self.compare_downloaded_source():
            return

        print('Downloading rootfs:')
        wget.download(
            self.config['rootfs'],
            self.rootfs_file_path
        )
        print()

        print('Downloading Linux For Tegra:')
        wget.download(
            self.config['l4t'],
            self.l4t_file_path
        )
        print()

        if self.config['nvidia_overlay'] != 'none':
            print('Downloading Nvidia overlay:')
            wget.download(
                self.config['nvidia_overlay'],
                self.nvidia_overlay_file_path
            )
            print()

        print('Downloading Airvolute overlay:')
        wget.download(
            self.config['airvolute_overlay'],
            self.airvolute_overlay_file_path
        )
        print()

        self.save_downloaded_versions()

    def prepare_sources_production(self):
        stop_event = Event()

        # Extract Linux For Tegra
        print('Extracting Linux For Tegra ...')
        stop_event.clear()
        tar = tarfile.open(self.l4t_file_path)
        l4t_animation_thread = self.run_loading_animation(stop_event)
        tar.extractall(path=self.flash_path)
        stop_event.set()
        l4t_animation_thread.join()

        # Extract Root Filesystem
        print('Extracting Root Filesystem ...')
        stop_event.clear()
        print('This part needs sudo privilegies:')
        # Run sudo identification
        subprocess.call(["/usr/bin/sudo", "/usr/bin/id"], stdout=subprocess.DEVNULL)
        rootfs_animation_thread = self.run_loading_animation(stop_event)
        subprocess.call(
            [
                'sudo',
                'tar', 
                'xpf', 
                self.rootfs_file_path,
                '--directory', 
                self.rootfs_extract_dir
            ]
        )
        stop_event.set()
        rootfs_animation_thread.join()

        if self.config['nvidia_overlay'] != 'none':
            print('Applying Nvidia overlay ...')
            self.prepare_nvidia_overlay()

        # Apply binaries
        print('Applying binaries ...')
        print('This part needs sudo privilegies:')
        # Run sudo identification
        subprocess.call(["/usr/bin/sudo", "/usr/bin/id"], stdout=subprocess.DEVNULL)
        subprocess.call(['/usr/bin/sudo', self.apply_binaries_path])

        print('Applying Airvolute overlay ...')
        self.prepare_airvolute_overlay()

        subprocess.call(['/usr/bin/sudo', self.apply_binaries_path, '-t  False'])

        print('Creating default user ...')
        subprocess.call(
            [
                'sudo',
                self.create_user_script_path,
                '-u',
                'dcs_user',
                '-p',
                'dronecore',
                '-n',
                'dcs',
                '--accept-license'
            ]
        )

        self.install_first_boot_setup()

    def prepare_airvolute_overlay(self):
        tar = tarfile.open(self.airvolute_overlay_file_path)
        tar.extractall(self.flash_path)

    def prepare_nvidia_overlay(self):
        tar = tarfile.open(self.nvidia_overlay_file_path)
        tar.extractall(self.flash_path)

    def install_first_boot_setup(self):
        """
        Installs script that would be run on a device after the
        very first boot.
        """
        # Create firstboot check file.
        subprocess.call(
            [
                'sudo',
                'touch',
                self.first_boot_file_path
            ]
        )

        # Setup systemd first boot
        service_destination = os.path.join(
            self.rootfs_extract_dir,
            'etc',
            'systemd',
            'system'
        )

        # Bin destination
        bin_destination = os.path.join(
            self.rootfs_extract_dir,
            'usr',
            'local',
            'bin'
        )

        # uhubctl destination
        uhubctl_destination = os.path.join(
            self.rootfs_extract_dir,
            'home',
            'dcs_user'
        )
        
        # USB3_CONTROL service
        subprocess.call(
            [
                'sudo',
                'cp',
                'resources/usb3_control/usb3_control.service',
                service_destination
            ]
        )

        subprocess.call(
            [
                'sudo',
                'cp',
                'resources/usb3_control/usb3_control.sh',
                bin_destination
            ]
        )

        subprocess.call(
            [
                'sudo',
                'chmod',
                '+x',
                os.path.join(bin_destination,'usb3_control.sh'),
            ]
        )

        # USB3_CONTROL service
        subprocess.call(
            [
                'sudo',
                'cp',
                'resources/usb3_control/usb3_control.service',
                service_destination
            ]
        )

        subprocess.call(
            [
                'sudo',
                'cp',
                'resources/usb3_control/usb3_control.sh',
                bin_destination
            ]
        )

        subprocess.call(
            [
                'sudo',
                'chmod',
                '+x',
                os.path.join(bin_destination,'usb3_control.sh'),
            ]
        )

        # USB_HUB_CONTROL service
        subprocess.call(
            [
                'sudo',
                'cp',
                'resources/usb_hub_control/usb_hub_control.service',
                service_destination
            ]
        )

        subprocess.call(
            [
                'sudo',
                'cp',
                'resources/usb_hub_control/usb_hub_control.sh',
                bin_destination
            ]
        )

        subprocess.call(
            [
                'sudo',
                'chmod',
                '+x',
                os.path.join(bin_destination,'usb_hub_control.sh'),
            ]
        )

        # FIRST_BOOT service
        subprocess.call(
            [
                'sudo',
                'cp',
                'resources/dcs_first_boot.service',
                service_destination
            ]
        )

        subprocess.call(
            [
                'sudo',
                'cp',
                'resources/dcs_first_boot.sh',
                bin_destination
            ]
        )

        subprocess.call(
            [
                'sudo',
                'chmod',
                '+x',
                os.path.join(bin_destination,'dcs_first_boot.sh'),
            ]
        )

        subprocess.call(
            [
                'sudo',
                'ln',
                '-s',
                '/etc/systemd/system/dcs_first_boot.service',
                os.path.join(service_destination, 'multi-user.target.wants/dcs_first_boot.service')
            ]
        )

        # uhubctl
        subprocess.call(
            [
                'sudo',
                'cp',
                'resources/uhubctl_2.1.0-1_arm64.deb',
                uhubctl_destination
            ]
        )

    def check_compatibility(self):
        """
        Check compatibility based on user input config.
        """
        for config in self.config_db:
            if (
                self.config_db[config]['device'] == self.args.target_device and
                self.config_db[config]['l4t_version'] == self.args.jetpack and
                self.config_db[config]['board'] == self.args.hwrev and
                self.config_db[config]['storage'] == self.args.storage
            ):
                return True
                
        return False

    def list_all_versions(self):
        for config in self.config_db:
            print('====', config, '====')
            print('Device:', self.config_db[config]['device'])
            print('L4T version:', self.config_db[config]['l4t_version'])
            print('Board:', self.config_db[config]['board'])
            print('Storage:', self.config_db[config]['storage'])
            print('====================')
            print()

    def load_selected_config(self):
        if not self.check_compatibility():
            print('Unsupported configuration!')
            return
        
        for config in self.config_db:
            if (
                self.config_db[config]['device'] == self.args.target_device and
                self.config_db[config]['l4t_version'] == self.args.jetpack and
                self.config_db[config]['board'] == self.args.hwrev and
                self.config_db[config]['storage'] == self.args.storage
            ):
                self.config = self.config_db[config]
                self.current_config_name = config

    def flash(self):
        flash_script_path = os.path.join(self.l4t_root_dir, 'tools/kernel_flash/l4t_initrd_flash.sh')

        if (self.config['storage'] == 'emmc' and
            self.config['device'] == 'xavier_nx'):
            os.chdir(self.l4t_root_dir)

            subprocess.call(
            [
                'sudo',
                'bash',
                flash_script_path,
                'airvolute-dcs' + self.config['board'] + '+p3668-0001-qspi-emmc', 
                'mmcblk0p1'
            ]
        )

        if (self.config['storage'] == 'nvme' and
            self.config['device'] == 'xavier_nx'):
            external_xml_config_path = os.path.join(self.l4t_root_dir, 'tools/kernel_flash/flash_l4t_external_custom.xml')
            os.chdir(self.l4t_root_dir)

            subprocess.call(
            [
                'sudo',
                'bash',
                flash_script_path,
                '--external-only',
                '--external-device',
                'nvme0n1p1',
                '-c',
                external_xml_config_path,
                '--showlogs',
                'airvolute-dcs' + self.config['board'] + '+p3668-0001-qspi-emmc', 
                'nvme0n1p1'
            ]
        )

    def airvolute_flash(self):
        if not self.check_compatibility():
            print('Unsupported configuration!')
            return

        self.download_resources()
        self.prepare_sources_production()
        self.flash()
        quit() 

    def run(self):
        if self.args.command == 'list':
            self.list_all_versions()
            quit()

        if self.args.command == 'flash':
            self.airvolute_flash()
            quit()


if __name__ == "__main__":
    dcs_deploy = DcsDeploy()
    dcs_deploy.run()