import os
import shutil
import stat

from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.build import build_jobs
from conan.tools.files import copy, get, rm, rmdir
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

    _b2_src  = "build2-toolchain"
    _odb_src = "libodb-src"
    _b_bin   = "b-bin"

    def layout(self):
        basic_layout(self, src_folder="src")

    def validate(self):
        if self.settings.os == "Emscripten":
            raise ConanInvalidConfiguration(f"{self.ref} does not support WASM")

    def source(self):
        src_data = self.conan_data["sources"][self.version]
        get(self, **src_data["libodb"], strip_root=True,
            destination=os.path.join(self.source_folder, self._odb_src))
        get(self, **src_data["build2_toolchain"], strip_root=True,
            destination=os.path.join(self.source_folder, self._b2_src))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _b_exe(self):
        suffix = ".exe" if self.settings.os == "Windows" else ""
        return os.path.join(self.source_folder, self._b_bin, "bin", f"b{suffix}")

    def _cxx_exe(self):
        compiler = str(self.settings.compiler)
        version  = str(self.settings.compiler.version)
        os_      = str(self.settings.os)
        if compiler == "msvc":   return "cl"
        if compiler == "gcc":    return "g++" if os_ == "Windows" else f"g++-{version}"
        if compiler == "clang":  return f"clang++-{version}"
        if compiler == "apple-clang": return "clang++"
        return "c++"

    def _is_msvc(self):
        return str(self.settings.compiler) == "msvc"

    # ------------------------------------------------------------------
    # build2 bootstrap: phases 1+2 only, then copy b-boot → b
    # ------------------------------------------------------------------

    def _bootstrap_build2(self):
        b2_src   = os.path.join(self.source_folder, self._b2_src)
        b2_pkg   = os.path.join(b2_src, "build2")
        b2_inner = os.path.join(b2_pkg, "build2")
        exe_sfx  = ".exe" if self.settings.os == "Windows" else ""
        b_boot   = os.path.join(b2_inner, f"b-boot{exe_sfx}")
        cxx      = self._cxx_exe()
        jobs     = build_jobs(self)

        # Phase 1
        if self._is_msvc():
            self.run(f"bootstrap-msvc.bat {cxx} /w", cwd=b2_pkg)
        else:
            bs = os.path.join(b2_pkg, "bootstrap.sh")
            os.chmod(bs, os.stat(bs).st_mode | stat.S_IEXEC)
            self.run(f"./bootstrap.sh {cxx} -w", cwd=b2_pkg)

        # Phase 2: rebuild b-boot statically with full build2 logic
        self.run(
            f"{b_boot} config.cxx={cxx} config.bin.lib=static build2/exe{{b}}",
            cwd=b2_pkg,
        )
        os.replace(os.path.join(b2_inner, f"b{exe_sfx}"), b_boot)

        # Phase 3: copy b-boot → b-bin/bin/b[.exe]
        b_bin_dir = os.path.join(self.source_folder, self._b_bin, "bin")
        os.makedirs(b_bin_dir, exist_ok=True)
        b_final = os.path.join(b_bin_dir, f"b{exe_sfx}")
        shutil.copy2(b_boot, b_final)
        if self.settings.os != "Windows":
            os.chmod(b_final, os.stat(b_final).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    # ------------------------------------------------------------------
    # Conan lifecycle
    # ------------------------------------------------------------------

    def build(self):
        self._bootstrap_build2()

        b     = self._b_exe()
        cxx   = self._cxx_exe()
        jobs  = build_jobs(self)
        debug = self.settings.build_type in ("Debug", "RelWithDebInfo")
        odb_src = os.path.join(self.source_folder, self._odb_src)

        # Build into a local output directory, then copy in package().
        # This avoids build2's install rule entirely — it cannot create
        # intermediate directories on Windows.
        out = os.path.join(self.build_folder, "out")

        args = [
            f"config.cxx={cxx}",
            "config.cxx.std=c++11",
            f"config.bin.debug={'true' if debug else 'false'}",
            f"config.bin.lib={'shared' if self.options.shared else 'static'}",
        ]
        if not self.options.shared and self.options.get_safe("fPIC") and not self._is_msvc():
            args.append("config.cc.coptions+=-fPIC")
        if jobs > 1:
            args.insert(0, f"-j {jobs}")

        # Build only the library (skip tests)
        self.run(f'"{b}" ' + " ".join(args) + " ./odb/", cwd=odb_src)

    def package(self):
        odb_src = os.path.join(self.source_folder, self._odb_src)

        # Headers (including .h files such as details/config-vc.h)
        for pat in ("*.hxx", "*.ixx", "*.txx", "*.h"):
            copy(self, pat, os.path.join(odb_src, "odb"),
                 os.path.join(self.package_folder, "include", "odb"))

        # Build artifacts: libs live in odb/ subdir of source after build
        if self.options.shared:
            copy(self, "*.dll", odb_src, os.path.join(self.package_folder, "bin"), keep_path=False)
            copy(self, "*.so*", odb_src, os.path.join(self.package_folder, "lib"), keep_path=False)
            copy(self, "*.dylib", odb_src, os.path.join(self.package_folder, "lib"), keep_path=False)
            copy(self, "*.lib", odb_src, os.path.join(self.package_folder, "lib"), keep_path=False)
        else:
            copy(self, "*.lib", odb_src, os.path.join(self.package_folder, "lib"), keep_path=False)
            copy(self, "*.a",   odb_src, os.path.join(self.package_folder, "lib"), keep_path=False)

        copy(self, "LICENSE", odb_src, os.path.join(self.package_folder, "licenses"))
        rm(self, "*.pdb", self.package_folder, recursive=True)

    def package_info(self):
        self.cpp_info.libs = ["odb"]
        self.cpp_info.set_property("cmake_file_name", "libodb")
        self.cpp_info.set_property("cmake_target_name", "libodb::libodb")
        self.cpp_info.set_property("pkg_config_name", "libodb")

        if not self.options.shared:
            self.cpp_info.defines.append("LIBODB_STATIC")
        if self.settings.os in ["Linux", "FreeBSD"]:
            self.cpp_info.system_libs.append("pthread")
        if self.settings.os == "Windows":
            self.cpp_info.system_libs.append("ws2_32")
