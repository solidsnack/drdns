from collections import defaultdict, namedtuple
from contextlib import contextmanager
from functools import wraps
import logging
import re
import time

import boto3
from botocore.exceptions import ClientError


log = logging.getLogger()


def handler(event, context):
    log.setLevel(logging.INFO)
    ec2 = boto3.resource('ec2')
    action_cls, instance_id = figure_out_event(event)
    with throttle():
        try:
            instance = ec2.Instance(instance_id)
            if instance.tags is None:
                log.info('Skipping %s (no tags presently available, might be '
                         'ASG instance?).',
                         instance_id)
                return dict(instance=instance_id, action=None)
            info = InstanceInfo.from_resource(instance)
        except ClientError as e:
            if 'InvalidInstanceID.NotFound' not in str(e):
                raise
            log.warning('Instance %s has gone missing.', instance_id)
            return
    action = action_cls(info)
    with throttle():
        action()
    return dict(instance=instance_id, action=type(action).__name__)


def figure_out_event(event):
    detail = event['detail']
    if 'AutoScalingGroupName' in detail:
        instance_id = detail['EC2InstanceId']
        asg = detail['AutoScalingGroupName']
        action_cls = Add
        log.info('Running `%s` for %s in ASG %s...',
                 action_cls.__name__, instance_id, asg)
    else:
        instance_id, state = detail['instance-id'], detail['state']
        action_cls = Add if state in ['running', 'pending'] else Remove
        log.info('Running `%s` for %s in state `%s`...',
                 action_cls.__name__, instance_id, state)
    return action_cls, instance_id


def tags2names(something, token):
    for k, v in tags(something).items():
        if '.' not in v:
            continue
        names = []
        if k.lower() == 'name':
            offset = len(token) + 1 if v.startswith(token + '.') else 0
            normed = v[offset:]
            names += [normed, token + '.' + normed]
        if k.lower() == 'dns:fqdn' or k.lower().startswith('dns:fqdn:'):
            names += [v]
        if k.lower() == 'dns:base' or k.lower().startswith('dns:base:'):
            names += [v, token + '.' + v]
        for name in names:
            dns = DNS.parse(name)
            if dns is None:
                log.warning('Discarding %s (for %s), invalid DNS.', name, k)
                continue
            yield str(dns)


def dictify(f):
    @wraps(f)
    def g(*args, **kwargs):
        return dict(f(*args, **kwargs))
    return g


def listify(f):
    @wraps(f)
    def g(*args, **kwargs):
        return list(f(*args, **kwargs))
    return g


class Action(object):
    def __call__(self):
        for zone, changes in self.changes():
            with throttle():
                self.r53.change_resource_record_sets(
                    HostedZoneId=zone,
                    ChangeBatch=dict(Comment='Dr. DNS scripted change.',
                                     Changes=changes)
                )

    def changes(self):
        raise NotImplementedError()

    @property
    def r53(self):
        if not hasattr(self, '_r53'):
            setattr(self, '_r53', boto3.client('route53'))
        return getattr(self, '_r53')

    @property
    def zones(self):
        if not hasattr(self, '_zones'):
            setattr(self, '_zones', self.get_zones())
        return getattr(self, '_zones')

    @dictify
    def get_zones(self):
        paginator = self.r53.get_paginator('list_hosted_zones')
        for page in paginator.paginate():
            zones = page.get('HostedZones', [])
            for zone in zones:
                yield (zone['Name'], zone)

    def zones_for(self, name):
        full = DNS(name).dot
        zones = []
        found = None
        for dn, zone in self.zones.items():
            if not full.endswith('.' + dn):
                continue
            if found is None or len(dn) > len(found):
                zones = [zone]
                found = dn
                continue
            if len(dn) == len(found):
                zones += [zone]
                continue
        return zones

    @staticmethod
    def change(mode, name, targets, token):
        rrs = dict(Name=name,
                   Type='CNAME',
                   TTL=1,
                   SetIdentifier=token,
                   Weight=16,
                   ResourceRecords=[dict(Value=target) for target in targets])
        return dict(Action=mode, ResourceRecordSet=rrs)


class Add(namedtuple('Add', 'instance'), Action):
    def changes(self):
        token = self.instance.instance
        changes = defaultdict(list)
        dn = DNS(self.instance.nominal_dns).dot
        for name in self.instance.names:
            zones = self.zones_for(name)
            if len(zones) <= 0:
                log.warning('Skipping %s (for %s): no Route53 zone matches.',
                            name, token)
                continue
            for zone in zones:
                zone_id, zone_name = zone['Id'], zone['Name']
                log.info('Updating/creating %s in %s (%s) for %s.',
                         name, zone_name, zone_id, token)
                change = Action.change('UPSERT', name, [dn], token)
                changes[zone_id] += [change]
        return changes.items()


class Remove(namedtuple('Remove', 'instance'), Action):
    def changes(self):
        token = self.instance.instance
        changes = []
        for name in self.instance.names:
            name = DNS(name).dot
            zones = self.zones_for(name)
            if len(zones) <= 0:
                log.warning('Skipping %s (for %s): no Route53 zone matches.',
                            name, token)
                continue
            for zone in zones:
                zone_id, zone_name = zone['Id'], zone['Name']
                old = self.find_old(zone_id, name)
                if len(old) <= 0:
                    continue
                log.info('Deleting %s in %s (%s) for %s.',
                         name, zone_name, zone_id, token)
                change = Action.change('DELETE', name, old, token)
                changes += [(zone_id, [change])]
        return changes

    @listify
    def find_old(self, zone_id, name):
        token = self.instance.instance
        name = DNS(name).dot
        data = self.r53.list_resource_record_sets(HostedZoneId=zone_id,
                                                  StartRecordName=name,
                                                  StartRecordIdentifier=token,
                                                  StartRecordType='CNAME')
        for rr in data.get('ResourceRecordSets', []):
            if rr.get('Name') != name or rr.get('SetIdentifier') != token:
                continue
            for r in rr.get('ResourceRecords', []):
                yield r['Value']


class InstanceInfo(namedtuple('InstanceInfo',
                              'instance names nominal_dns private_ip')):
    @staticmethod
    def from_boto_dictionary(info):
        token = info['InstanceId']
        names = tags2names(info['Tags'], token)
        target = info['PublicDnsName'] or info['PrivateDnsName']
        return InstanceInfo(info['InstanceId'],
                            sorted(set(names)),
                            target,
                            info['PrivateIpAddress'])

    @staticmethod
    def from_resource(instance):
        token = instance.id
        names = tags2names(instance.tags, token)
        target = instance.public_dns_name or instance.private_dns_name
        return InstanceInfo(instance.id,
                            sorted(set(names)),
                            target,
                            instance.private_ip_address)


def tags(something):
    return {tag['Key']: tag['Value'] for tag in something}


@contextmanager
def throttle():
    n = 0
    while n < 5:
        try:
            yield
            return
        except ClientError as e:
            if 'Throttling' not in str(e):
                raise
            sleep = (1.6 ** n) / 2
            log.warning('Sleeping %s seconds due to AWS throttling...', sleep)
            time.sleep(sleep)
        n += 1
    raise RuntimeError('Failed due to AWS throttling.')


class DNS(object):
    ldh = re.compile(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$')

    @staticmethod
    def parse(s):
        try:
            return DNS(s)
        except AssertionError:
            pass

    def __init__(self, input):
        if isinstance(input, DNS):
            self.data = input.data
            return
        s = input.lower().replace('_', '.').rstrip('.')
        pieces = s.split('.')
        assert(all(DNS.ldh.match(x) for x in pieces))
        assert(len(pieces) <= 127)
        assert(len(s) <= 255)
        self.data = s

    def __str__(self):
        return self.undot

    def __repr__(self):
        return self.dot

    def __len__(self):
        return len(self.data)

    @property
    def undot(self):
        return self.data

    @property
    def dot(self):
        return self.data + '.'
