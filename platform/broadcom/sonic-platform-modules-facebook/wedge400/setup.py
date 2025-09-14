#!/usr/bin/env python

import os
import sys
from setuptools import setup, Extension
os.listdir

module1 = Extension("fbfpgaio", sources = ["wedge400/lib/fbfpgaiomodule.c"])

setup(
   name='wedge400',
   version='1.0',
   description='Module to initialize Facebook Wedge400 platforms',

   packages=['wedge400'],
   package_dir={'wedge400': 'wedge400/classes'},
   ext_modules=[module1],
   
)

