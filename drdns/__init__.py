from magiclog import log
from v2 import v2

from .db import db
from .aws import ec2


__version__ = v2.from_pkg().from_git().from_default().version

name = __name__
tag = '%s-%s' % (name, __version__)


def synchronize():
    data = sorted(ec2.instances())
    log.info('Synchronizing data for %s instances.', len(data))
    db.load(data)


def schema():
    db.schema()
