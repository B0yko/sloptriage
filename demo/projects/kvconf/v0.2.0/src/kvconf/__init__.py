"""kvconf: key = value configuration files with sections, includes and interpolation."""

from kvconf.interp import interpolate
from kvconf.parser import ConfigError, load, loads

__all__ = ["ConfigError", "interpolate", "load", "loads"]
__version__ = "0.2.0"
