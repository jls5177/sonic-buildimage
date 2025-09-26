#!/usr/bin/env python

from setuptools import setup

# NOTE:
# SONiC infrastructure (pmon daemon, led daemon, etc.) expects a PURE PYTHON
# wheel named 'sonic_platform-<version>-py3-none-any.whl' in /usr/share/sonic/platform.
# To keep the wheel platform-agnostic (py3-none-any), we intentionally exclude
# native/C extensions here. Any hardware-specific shared objects (e.g. FPGA IO)
# should be packaged via a separate Debian package or installed into a
# predictable location consumed by the python code at runtime.
#
# We also bundle an auxiliary 'wedge400' package (mapped from wedge400/classes)
# so existing helper imports like `import wedge400.domutil` continue to work.

setup(
   name='sonic_platform',
   version='1.0',
   description='SONiC platform package for Facebook Wedge400',
   packages=['sonic_platform', 'wedge400'],
   package_dir={
      'sonic_platform': 'sonic_platform',
      'wedge400': 'wedge400/classes',
   },
   # No ext_modules to preserve universal (py3-none-any) compatibility
   python_requires='>=3.7',
   classifiers=[
      'Programming Language :: Python :: 3',
      'License :: OSI Approved :: Apache Software License',
      'Operating System :: POSIX :: Linux'
   ],
   # Removed 'universal' wheel flag so tag becomes py3-none-any instead of py2.py3
)

