from setuptools import setup, find_packages

with open("requirements.txt") as f:
	install_requires = f.read().strip().split("\n")

# get version from __version__ variable in mapro/__init__.py
from mapro import __version__ as version

setup(
	name="mapro",
	version=version,
	description="manufacuring mode ",
	author="Pradip",
	author_email="21pradipjadhav@gmail.com",
	packages=find_packages(),
	zip_safe=False,
	include_package_data=True,
	install_requires=install_requires
)
