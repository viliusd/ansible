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

DOCUMENTATION = '''
module: vcenter_nfs_ds
short_description: Add host to nfs datastore
description:
    - Add host to specified nfs datastore
options:

    esxi_hostname:
        description:
            - The esxi hostname or ip to add to nfs ds
        required: True
    nfs_host:
        description:
            - The nfs service providing nfs service
        required: True
    nfs_path:
        description:
            - The remove file path ex: /nfs1
        required: True
    nfs_name:
        description:
            - The name of the datastore as seen by vcenter
        required: True
    nfs_access:
        description:
            - The access type
        choices: [readWrite, readOnly]
        required: True
    nfs_type:
        description:
            - The type of volume. Defaults to nfs if not specified
        choices: [nfs, cifs]
        required: False
    nfs_username:
        description:
            - The username to access the nfs ds if required
        required: False
    nfs_password:
        description:
            - The password to access the nfs ds if required
        required: False
    state:
        description:
            - If the datacenter should be present or absent
        choices: ['present', 'absent']
        required: True
'''

EXAMPLES = '''
- name: Add NFS DS to Host
  ignore_errors: no
  vcenter_nfs_ds:
    esxi_hostname: '192.168.1.102'
    nfs_host: '192.168.1.145'
    nfs_path: '/nfs1'
    nfs_name: 'nfs_ds_1'
    nfs_access: 'readWrite'
    nfs_type: 'nfs'
    state: 'present'
  tags:
    - addnfs
'''

try:
    from pyVmomi import vim, vmodl
    HAS_PYVMOMI = True
except ImportError:
    HAS_PYVMOMI = False


vc = {}


def find_vcenter_object_by_name(content, vimtype, object_name):
    vcenter_object = get_all_objs(content, [vimtype])

    for k, v in vcenter_object.items():
        if v == object_name:
            return k
    else:
        return None


def nfs_spec(module):

    nfs_remote_host = module.params['nfs_host']
    nfs_remote_path = module.params['nfs_path']
    nfs_local_name = module.params['nfs_name']
    nfs_access_mode = module.params['nfs_access']
    nfs_type = module.params['nfs_type']
    nfs_username = module.params['nfs_username']
    nfs_password = module.params['nfs_password']

    nfs_config_spec = vim.host.NasVolume.Specification(
        remoteHost=nfs_remote_host,
        remotePath=nfs_remote_path,
        localPath=nfs_local_name,
        accessMode=nfs_access_mode,
        type=nfs_type,
    )

    if nfs_username and nfs_password:
        nfs_config_spec.userName = nfs_username
        nfs_config_spec.password = nfs_password

    return nfs_config_spec


def check_host_added_to_nfs_ds(module):

    state = None

    nfs_ds = vc['nfs']
    host = vc['host']

    for esxhost in nfs_ds.host:
        if esxhost.key == host:
            state = True

    return state


def state_exit_unchanged(module):
    module.exit_json(change=False, msg="EXIT UNCHANGED")


def state_delete_nfs(module):

    changed = False
    result = None

    host = vc['host']
    ds = vc['nfs']

    try:
        host.configManager.datastoreSystem.RemoveDatastore(ds)
        changed = True
        result = "Removed Datastore: {}".format(ds.name)
    except Exception as e:
        module.fail_json(msg="Failed to remove datastore: %s" % str(e))

    module.exit_json(changed=changed, result=result)

def state_create_nfs(module):

    changed = False
    result = None

    host = vc['host']
    ds_spec = nfs_spec(module)

    try:
        ds = host.configManager.datastoreSystem.CreateNasDatastore(ds_spec)
        changed = True
        result = ds.name
    except vim.fault.DuplicateName as duplicate_name:
        module.fail_json(msg="Failed duplicate name: %s" % duplicate_name)
    except vim.fault.AlreadyExists as already_exists:
        module.exit_json(changed=False, result=str(already_exists))
    except vim.HostConfigFault as config_fault:
        module.fail_json(msg="Failed to configure nfs on host: %s" % config_fault.msg)
    except vmodl.fault.InvalidArgument as invalid_arg:
        module.fail_json(msg="Failed with invalid arg: %s" % invalid_arg)
    except vim.fault.NoVirtualNic as no_virt_nic:
        module.fail_json(msg="Failed no virtual nic: %s" % no_virt_nic)
    except vim.fault.NoGateway as no_gwy:
        module.fail_json(msg="Failed no gateway: %s" % no_gwy)
    except vmodl.MethoFault as method_fault:
        module.fail_json(msg="Failed to configure nfs on host method fault: %s" % method_fault.msg)

    module.exit_json(change=changed, result=result)

def check_nfs_host_state(module):

    esxi_hostname = module.params['esxi_hostname']
    nfs_ds_name = module.params['nfs_name']

    si = connect_to_api(module)
    vc['si'] = si

    host = find_hostsystem_by_name(si, esxi_hostname)

    if host is None:
        module.fail_json(msg="Esxi host: %s not in vcenter".format(esxi_hostname))

    vc['host'] = host

    nfs_ds = find_vcenter_object_by_name(si, vim.Datastore, nfs_ds_name)

    if nfs_ds is None:
        return 'absent'
    else:
        vc['nfs'] = nfs_ds

        if check_host_added_to_nfs_ds(module):
            return 'present'
        else:
            return 'update'



def main():
    argument_spec = vmware_argument_spec()

    argument_spec.update(
        dict(
            esxi_hostname=dict(required=True, type='str'),
            nfs_host=dict(required=True, type='str'),
            nfs_path=dict(required=True, type='str'),
            nfs_name=dict(required=True, type='str'),
            nfs_access=dict(required=True, type='str'),
            nfs_type=dict(required=False, type='str'),
            nfs_username=dict(required=False, type='str'),
            nfs_password=dict(required=False, type='str', no_log=True),
            state=dict(default='present', choices=['present', 'absent'], type='str'),
        )
    )

    module = AnsibleModule(argument_spec=argument_spec, supports_check_mode=False)

    if not HAS_PYVMOMI:
        module.fail_json(msg='pyvmomi is required for this module')

    try:
        nfs_host_states = {
            'absent': {
                'update': state_exit_unchanged,
                'present': state_delete_nfs,
                'absent': state_exit_unchanged,
            },
            'present': {
                'update': state_create_nfs,
                'present': state_exit_unchanged,
                'absent': state_create_nfs,
            }
        }

        nfs_host_states[module.params['state']][check_nfs_host_state(module)](module)

    except vmodl.RuntimeFault as runtime_fault:
        module.fail_json(msg=runtime_fault.msg)
    except vmodl.MethodFault as method_fault:
        module.fail_json(msg=method_fault.msg)
    except Exception as e:
        module.fail_json(msg=str(e))


from ansible.module_utils.basic import *
from ansible.module_utils.vmware import *

if __name__ == '__main__':
    main()
