from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version

try:
	from ._version import __version__
except ModuleNotFoundError:
	# Editable/source checkouts may not have generated _version.py.
	try:
		__version__ = package_version("fomo")
	except PackageNotFoundError:
		__version__ = "0+unknown"

__all__ = ["__version__"]
