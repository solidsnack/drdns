#!/usr/bin/env python
from setuptools import find_packages, setup

from v2 import v2


conf = dict(name='drdns',
            version=v2.from_git().from_file().imprint().version,
            author='Jason Dusek',
            author_email='jason.dusek@gmail.com',
            url='https://github.com/drcloud/drdns',
            install_requires=['boto3', 'botocore', 'v2'],
            setup_requires=['pytest-runner', 'setuptools', 'v2'],
            tests_require=['flake8', 'pytest', 'tox'],
            description='DNS provider for AWS.',
            packages=find_packages(),
            classifiers=['Environment :: Console',
                         'Intended Audience :: Developers',
                         'License :: OSI Approved :: MIT License',
                         'Operating System :: Unix',
                         'Operating System :: POSIX',
                         'Programming Language :: Python',
                         'Programming Language :: Python :: 2.7',
                         'Programming Language :: Python :: 3.6',
                         'Topic :: Software Development',
                         'Development Status :: 5 - Production/Stable'])


if __name__ == '__main__':
    setup(**conf)
