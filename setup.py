from setuptools import setup, find_packages
from os.path import join, dirname
import core

setup(
    author='Paul D. Allen',
    name='CloudCoreoClient',
    version=core.__version__,
    packages=find_packages(),
    url='https://github.com/CloudCoreo/cloudcoreo-client',
    long_description=open(join(dirname(__file__), 'README.txt')).read(),
    entry_points={
        'console_scripts':
            ['run_agent = core.cloudcoreo_agent:start_agent']
    },
    include_package_data=True,
    install_requires=[
        'boto3==1.3.1',
        'requests==2.3.0',
        'rsa==3.1.2',
        'pyaml==14.5.7'
    ]
)
