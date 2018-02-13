#!/usr/bin/python
#
# (c) 2015, Joseph Callen <jcallen () csc.com>
# Portions Copyright (c) 2015 VMware, Inc. All rights reserved.
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

ANSIBLE_METADATA = {'metadata_version': '1.0',
                    'status': ['preview'],
                    'supported_by': 'community'}

DOCUMENTATION = '''
module: vcenter_host_ntp
Short_description: sets ntp setting for esx hosts in a cluster
description:
    sets ntp setting for esx hosts in a cluster
requirements:
    - pyvmomi 6
    - ansible 2.x
Tested on:
    - vcenter 6.0
    - pyvmomi 6.5
    - esx 6
    - ansible 2.1.2
options:
    hostname:
        description:
            - The hostname or IP address of the vSphere vCenter API server
        required: True
    username:
        description:
            - The username of the vSphere vCenter with Admin rights
        required: True
    password:
        description:
            - The password of the vSphere vCenter user
        required: True
        aliases: ['pass', 'pwd']
    cluster_name:
        description:
            - The name for the vsphere cluster
        required: True
    ntp_server:
        description:
            - The ip or fqdn for the NTP server
        required: True
    state:
        description:
            - Desired state of the disk group
        choices: ['present', 'absent']
        required: True

'''

EXAMPLES = '''
- name: Host NTP
  vcenter_host_ntp:
    hostname: "{{ vcenter }}"
    username: "{{ vcenter_user }}"
    password: "{{ vcenter_password }}"
    validate_certs: "{{ vcenter_validate_certs }}"
    cluster_name: "{{ cluster_name }}"
    ntp_server: ntp.your_org.com
    state: "{{ global_state }}"
  tags: workflow_tag
'''

RETURN = '''
host_results:
  description: List of dicts for hosts changed
  returned: host_results
  type: list
  sample: "{'name': str, 'host_ntp_server_changed': bool, 'restart_ntp': bool}"
'''

try:
    from pyVmomi import vim, vmodl
    IMPORTS = True
except ImportError:
    IMPORTS = False


class VcenterHostNtp(object):
    """docstring for VcenterHostNtp"""
    def __init__(self, module):
        super(VcenterHostNtp, self).__init__()
        self.module = module
        self.cluster_name = module.params['cluster_name']
        self.ntp_server = module.params['ntp_server']
        self.desired_state = module.params['state']
        self.hosts = None
        self.host_update_list = []
        self.content = connect_to_api(module)

    def run_state(self):

        desired_state = self.module.params['state']
        current_state = self.current_state()
        module_state  = (desired_state == current_state)

        if module_state:
            self.state_exit_unchanged()

        if desired_state == 'absent' and current_state == 'present':
            self.state_delete()

        if desired_state == 'present' and current_state == 'absent':
            self.state_create()

        if desired_state == 'present' and current_state == 'update':
            self.state_update()

        self.module.exit_json(changed=False, result=None)


    def ntp_spec(self):
        ntp_config_spec = vim.host.NtpConfig()

        if self.module.params['state'] == 'present':
            ntp_config_spec.server = [self.ntp_server]

        if self.module.params['state'] == 'absent':
            ntp_config_spec.server = []

        update_spec = vim.host.DateTimeConfig()
        update_spec.ntpConfig = ntp_config_spec

        return update_spec

    def update_host_date_time(self, host):
        state = False
        host_date_time_mgr = host.configManager.dateTimeSystem

        update_spec = self.ntp_spec()

        try:
            host_date_time_mgr.UpdateDateTimeConfig(update_spec)
            state = True
        except vim.fault.HostConfigFault as host_config_fault:
            msg = "Failed Host Config Fault: {}".format(host_config_fault)
            return state
        except Exception as e:
            msg = "Failed to config NTP on host: {}".format(e)
            return state

        return state

    def set_ntp_service(self, host, service_state):
        service_system = host.configManager.serviceSystem
        changed = False

        try:

            if service_state == 'start':
                service_system.StartService(id='ntpd')
            if service_state == 'stop':
                service_system.StopService(id='ntpd')
            if service_state == 'restart':
                service_system.RestartService(id='ntpd')
            changed = True

        except vim.fault.InvalidState as invalid_state:
            return changed
        except vim.fault.NotFound as not_found:
            return changed
        except vim.fault.HostConfigFault as config_fault:
            return changed

        return changed

    def state_create(self):
        changed = False
        results = []

        for host in self.host_update_list:
            host_results = {'name': host.name}

            if not self.check_host_ntp_server(host):
                host_ntp_server_changed = self.update_host_date_time(host)
                restart_ntp = self.set_ntp_service(host, 'restart')

                host_results.update({'host_ntp_server_changed': host_ntp_server_changed})
                host_results.update({'restart_ntp': restart_ntp})

            if not self.check_host_ntp_service(host):
                host_ntp_service_changed = self.set_ntp_service(host, 'start')
                host_results.update({'host_ntp_service_changed': host_ntp_service_changed})

            results.append(host_results)

        if results:
            changed = True

        self.module.exit_json(changed=changed, results=results, msg="STATE CREATE")

    def state_update(self):
        self.state_create()

    def state_exit_unchanged(self):
        self.module.exit_json(changed=False, msg="EXIT UNCHANGED")

    def state_delete(self):
        changed = False
        results = []

        for host in self.host_update_list:
            stop_ntp_service = self.set_ntp_service(host, 'stop')
            remove_ntp_server = self.update_host_date_time(host)
            host_results = {'name': host.name,
                            'stop_ntp_service': stop_ntp_service,
                            'remove_ntp_server': remove_ntp_server}
            results.append(host_results)

        if results:
            changed = True

        self.module.exit_json(changed=changed, results=results, msg="STATE DELETE")

    def check_host_ntp_service(self, host):
        ntp_status = False
        host_services = host.configManager.serviceSystem.serviceInfo.service

        try:
            ntp_status = [s.running for s in host_services if s.key == 'ntpd'][0]
        except IndexError:
            return ntp_status

        return ntp_status

    def check_host_ntp_server(self, host):
        state = False
        date_time_system = host.configManager.dateTimeSystem
        host_ntp_servers = date_time_system.dateTimeInfo.ntpConfig.server

        if self.ntp_server in host_ntp_servers:
            state = True

        return state

    def current_state(self):
        state = 'absent'

        cluster = find_cluster_by_name(self.content, self.cluster_name)

        if not cluster:
            msg = "Cannot find cluster: {}".format(self.cluster_name)
            self.module.fail_json(msg=msg)

        hosts = cluster.host

        if not hosts:
            msg = "No hosts present in cluster"
            self.module.exit_json(changed=False, msg=msg)

        self.hosts = hosts

        for host in self.hosts:

            ntp_server = self.check_host_ntp_server(host)
            ntp_service = self.check_host_ntp_service(host)

            if ntp_server and ntp_service:
                host_state = 'present'

            if (not ntp_server) or (not ntp_service):
                host_state = 'absent'

            if host_state == 'present' and self.desired_state == 'absent':
                self.host_update_list.append(host)
            if host_state == 'absent' and self.desired_state == 'present':
                self.host_update_list.append(host)

        if self.desired_state == 'present' and self.host_update_list:
            return state
        if self.desired_state == 'absent' and self.host_update_list:
            state = 'present'

        return state


def main():
    argument_spec = vmware_argument_spec()

    argument_spec.update(
        dict(
            cluster_name=dict(required=True, type='str'),
            ntp_server=dict(required=True, type='str'),
            state=dict(default='present', choices=['present', 'absent'], type='str'),
        )
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=False)

    if not IMPORTS:
        module.fail_json(msg='pyvmomi is required for this module')

    hostntp = VcenterHostNtp(module)
    hostntp.run_state()

from ansible.module_utils.basic import *
from ansible.module_utils.vmware import *

if __name__ == '__main__':
    main()
