"""The built-in build recipes.

A preset is a starting point: ``repro.build`` in ``.sloptriage.yml`` can replace any field.
Native presets assume a Debian or Ubuntu base image (packages come from ``apt-get``).
"""

from __future__ import annotations

from dataclasses import dataclass

PREFIX = "/opt/project"
SOURCE_DIR = "/build/src"
SANITIZER_FLAGS = (
    "-fsanitize=address,undefined",
    "-fno-sanitize-recover=undefined",
    "-fno-omit-frame-pointer",
    "-g",
    "-O1",
)


@dataclass(frozen=True)
class Preset:
    base_image: str
    packages: tuple[str, ...]
    configure: tuple[str, ...]
    build: tuple[str, ...]
    install: tuple[str, ...]
    python: bool = False


_CMAKE_FLAGS = (
    f"-DCMAKE_INSTALL_PREFIX={PREFIX} -DCMAKE_BUILD_TYPE=Debug "
    '"-DCMAKE_C_FLAGS=$SAN_FLAGS" "-DCMAKE_CXX_FLAGS=$SAN_FLAGS" '
    '"-DCMAKE_EXE_LINKER_FLAGS=$SAN_FLAGS" "-DCMAKE_SHARED_LINKER_FLAGS=$SAN_FLAGS"'
)

PRESETS: dict[str, Preset] = {
    "cmake-asan": Preset(
        base_image="debian:trixie-slim",
        packages=("build-essential", "cmake", "ninja-build", "pkg-config"),
        configure=(f"cmake -S . -B build -G Ninja {_CMAKE_FLAGS}",),
        build=("cmake --build build",),
        install=("cmake --install build",),
    ),
    "autotools-asan": Preset(
        base_image="debian:trixie-slim",
        packages=("build-essential", "autoconf", "automake", "libtool", "pkg-config"),
        configure=(
            "if [ ! -x ./configure ]; then autoreconf -fi; fi",
            f"./configure --prefix={PREFIX} --disable-docs --disable-manual",
        ),
        build=('make -j"$(nproc)"',),
        install=("make install",),
    ),
    "meson-asan": Preset(
        base_image="debian:trixie-slim",
        packages=("build-essential", "meson", "ninja-build", "pkg-config"),
        configure=(
            f"meson setup build --prefix={PREFIX} --buildtype=debug "
            "-Db_sanitize=address,undefined -Db_lundef=false",
        ),
        build=("meson compile -C build",),
        install=("meson install -C build",),
    ),
    "python-pip": Preset(
        base_image="python:3.12-slim",
        packages=(),
        configure=(),
        build=(),
        install=(f"pip install --no-index --no-build-isolation --no-deps {SOURCE_DIR}",),
        python=True,
    ),
}

PRESET_NAMES = tuple(sorted(PRESETS))
