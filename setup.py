#!/usr/bin/env python
# encoding=utf-8
import os
from setuptools import setup

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.md')).read()

setup(name='almar',
      version='0.7.0',  # Use bumpversio to update
      description='Search and replace for subject fields in Alma records.',
      long_description=README,
      classifiers=[
          'Programming Language :: Python',
          'Programming Language :: Python :: 2.7',
          'Programming Language :: Python :: 3.4',
          'Programming Language :: Python :: 3.5',
          'Programming Language :: Python :: 3.6',
      ],
      keywords='marc alma',
      author='Scriptoteket',
      author_email='scriptoteket@ub.uio.no',
      url='https://github.com/scriptotek/almar',
      license='MIT',
      install_requires=['six',
                        'requests',
                        'tqdm',
                        'prompter',
                        'pyyaml',
                        'colorama',
                        'coloredlogs',
                        'raven',
                        'vkbeautify',
                        'lxml',
                        'inquirer',
                        ],
      setup_requires=['pytest-runner'],
      tests_require=['pytest', 'pytest-pep8', 'pytest-cov', 'responses', 'mock'],
      entry_points={'console_scripts': ['almar=almar.almar:main']},
      options={
          'build_scripts': {
              'executable': '/usr/bin/env python',
          },
      },
      packages=['almar']
      # data_files=[(AppDirs('Lokar').user_config_dir, ['almar.cfg'])]
      )
