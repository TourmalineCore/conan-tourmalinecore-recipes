import os
import shutil
import stat

from conan import ConanFile
from conan.errors import ConanException, ConanInvalidConfiguration
from conan.tools.build import build_jobs, check_min_cppstd
from conan.tools.files import copy, get, rm
from conan.tools.layout import basic_layout

required_conan_version = ">=2.0.9"


class LibOdbConan(ConanFile):
    name = "libodb"
    description = (
        "ODB is an open-source, cross-platform, and cross-database "
        "object-relational mapping (ORM) system for C++."
    )
    license = "GPL-2.0-only"
    url = "https://github.com/conan-io/conan-center-index"
    homepage = "https://www.codesynthesis.com/products/odb/"
    topics = ("odb", "orm", "database", "c++")
    package_type = "library"

    settings = "os", "arch", "compiler", "build_type"

    options = {
        "shared": [True, False],
        "fPIC": [True, False],
    }
    default_options = {
        "shared": False,
        "fPIC": True,
    }

    implements = ["auto_shared_fpic"]

    _b2_src = "build2-toolchain-src"
    _odb_src = "libodb-src"
    _b_bin = "b-bin"

    def layout(self):
        basic_layout(self, src_folder="src")

    def validate(self):
        if str(self.settings.os) not in ("Windows", "Linux", "Macos"):
            raise ConanInvalidConfiguration(
                f"{self.ref} supports only Windows, Linux and macOS"
            )

        if str(self.settings.arch) not in ("x86_64", "armv8"):
            raise ConanInvalidConfiguration(
                f"{self.ref} supports only x86_64 and armv8"
            )

        if self.settings.get_safe("compiler.cppstd"):
            check_min_cppstd(self, 11)

    def source(self):
        src_data = self.conan_data["sources"][self.version]

        get(
            self,
            **src_data["libodb"],
            strip_root=True,
            destination=self._odb_source_dir,
        )

        get(
            self,
            **src_data["build2_toolchain"],
            strip_root=True,
            destination=self._build2_source_dir,
        )

    @property
    def _build2_source_dir(self):
        return os.path.join(self.source_folder, self._b2_src)

    @property
    def _odb_source_dir(self):
        return os.path.join(self.source_folder, self._odb_src)

    @property
    def _build2_bootstrap_dir(self):
        return os.path.join(self._build2_source_dir, "build2")

    @property
    def _build2_bin_source_dir(self):
        return os.path.join(self._build2_bootstrap_dir, "build2")

    @property
    def _build2_bin_b_bin_executable_dir(self):
        return os.path.join(self.source_folder, self._b_bin, "bin")

    def _exe_suffix(self):
        return ".exe" if str(self.settings.os) == "Windows" else ""

    def _is_msvc(self):
        return str(self.settings.compiler) == "msvc"

    def _make_executable(self, path):
        if str(self.settings.os) != "Windows":
            os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    def _cxx_executable(self):
        compiler = str(self.settings.compiler)

        if self._is_msvc():
            return "cl"

        cxx = os.getenv("CXX")
        if cxx:
            return cxx

        if compiler == "gcc":
            return "g++"

        if compiler in ("clang", "apple-clang"):
            return "clang++"

        return "c++"

    def _b_executable(self):
        return os.path.join(self._build2_bin_b_bin_executable_dir, f"b{self._exe_suffix()}")

    def _bootstrap_build2(self):
        cxx = self._cxx_executable()
        b_boot = os.path.join(self._build2_bin_source_dir, f"b-boot{self._exe_suffix()}")
        b_full = os.path.join(self._build2_bin_source_dir, f"b{self._exe_suffix()}")

        if self._is_msvc():
            self.run(f"bootstrap-msvc.bat {cxx} /w", cwd=self._build2_bootstrap_dir)
        else:
            bootstrap = os.path.join(self._build2_bootstrap_dir, "bootstrap.sh")
            self._make_executable(bootstrap)
            self.run(f"./bootstrap.sh {cxx} -w", cwd=self._build2_bootstrap_dir)

        self.run(
            f'"{b_boot}" config.cxx={cxx} config.bin.lib=static build2/exe{{b}}',
            cwd=self._build2_bootstrap_dir,
        )

        if not os.path.isfile(b_full):
            raise ConanException(
                "build2 bootstrap failed: final 'b' executable was not created"
            )

        os.makedirs(self._build2_bin_b_bin_executable_dir, exist_ok=True)
        b_final = self._b_executable()
        shutil.copy2(b_full, b_final)
        self._make_executable(b_final)

    def _build_args(self):
        args = []
        jobs = build_jobs(self)
        debug = str(self.settings.build_type) in ("Debug", "RelWithDebInfo")

        if jobs > 1:
            args.append(f"-j {jobs}")

        args.extend(
            [
                f"config.cxx={self._cxx_executable()}",
                "config.cxx.std=c++11",
                f"config.bin.debug={'true' if debug else 'false'}",
                f"config.bin.lib={'shared' if self.options.shared else 'static'}",
            ]
        )

        if not self.options.shared and self.options.get_safe("fPIC") and not self._is_msvc():
            args.append("config.cc.coptions+=-fPIC")

        return args

    def build(self):
        self._bootstrap_build2()

        args = " ".join(self._build_args())
        self.run(f'"{self._b_executable()}" {args} ./odb/', cwd=self._odb_source_dir)

    def _copy_headers(self):
        src = os.path.join(self._odb_source_dir, "odb")
        dst = os.path.join(self.package_folder, "include", "odb")

        for pattern in ("*.hxx", "*.ixx", "*.txx", "*.h"):
            copy(self, pattern, src, dst)

    def _copy_libraries(self):
        lib_dir = os.path.join(self.package_folder, "lib")
        bin_dir = os.path.join(self.package_folder, "bin")

        if self.options.shared:
            copy(self, "*.dll", self._odb_source_dir, bin_dir, keep_path=False)
            copy(self, "*.so*", self._odb_source_dir, lib_dir, keep_path=False)
            copy(self, "*.dylib", self._odb_source_dir, lib_dir, keep_path=False)
            copy(self, "*.lib", self._odb_source_dir, lib_dir, keep_path=False)
        else:
            copy(self, "*.a", self._odb_source_dir, lib_dir, keep_path=False)
            copy(self, "*.lib", self._odb_source_dir, lib_dir, keep_path=False)

    def package(self):
        self._copy_headers()
        self._copy_libraries()

        copy(
            self,
            "LICENSE",
            self._odb_source_dir,
            os.path.join(self.package_folder, "licenses"),
            keep_path=False,
        )
        rm(self, "*.pdb", self.package_folder, recursive=True)

    def package_info(self):
        self.cpp_info.libs = ["odb"]
        self.cpp_info.set_property("cmake_file_name", "libodb")
        self.cpp_info.set_property("cmake_target_name", "libodb::libodb")
        self.cpp_info.set_property("pkg_config_name", "libodb")

        if not self.options.shared:
            self.cpp_info.defines.append("LIBODB_STATIC")

        if str(self.settings.os) == "Linux":
            self.cpp_info.system_libs.append("pthread")

        if str(self.settings.os) == "Windows":
            self.cpp_info.system_libs.append("ws2_32")