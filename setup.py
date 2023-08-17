#!/usr/bin/env python3

from distutils.core import setup
  
setup(
    name='vmcreator',
    version='0.1',
    description='A simple cli VM creator using libvirt and yaml',
    author='artemtech',
    author_email='sofyan@artemtech.id',
    packages=['vmcreator'],
    install_requires=[
        'requests',
        'PyYAML',
        'lxml',
        'libvirt-python'
    ],
)