import os
import shutil
import stat

from conan import ConanFile
from conan.errors import ConanInvalidConfiguration
from conan.tools.build import build_jobs
from conan.tools.files import copy, get, rm, rmdir
from conan.tools.layout import basic_layout

required_conan_version = ">=2.0.9"


class LibOdbPgsqlConan(ConanFile):
    name = "libodb-pgsql"
    description = (
        "PostgreSQL database runtime library for the ODB C++ ORM. "
        "Provides the backend needed to persist C++ objects to a PostgreSQL database."
    )
    license = "GPL-2.0-only"
    url = "https://github.com/conan-io/conan-center-index"
    homepage = "https://www.codesynthesis.com/products/odb/"
    topics = ("odb", "orm", "postgresql", "pgsql", "database", "c++")
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

    _b2_src    = "build2-toolchain"
    _pgsql_src = "libodb-pgsql-src"
    _b_bin     = "b-bin"

    def layout(self):
        basic_layout(self, src_folder="src")

    def requirements(self):
        self.requires("libodb/2.5.0", transitive_headers=True, transitive_libs=True)
        self.requires("libpq/[>=14 <17]", transitive_headers=True, transitive_libs=True)

    def validate(self):
        if self.settings.os == "Emscripten":
            raise ConanInvalidConfiguration(f"{self.ref} does not support WASM")

    def source(self):
        src_data = self.conan_data["sources"][self.version]
        get(self, **src_data["libodb_pgsql"], strip_root=True,
            destination=os.path.join(self.source_folder, self._pgsql_src))
        get(self, **src_data["build2_toolchain"], strip_root=True,
            destination=os.path.join(self.source_folder, self._b2_src))

    # ------------------------------------------------------------------
    # Helpers  (identical to libodb recipe)
    # ------------------------------------------------------------------

    def _b_exe(self):
        suffix = ".exe" if self.settings.os == "Windows" else ""
        return os.path.join(self.source_folder, self._b_bin, "bin", f"b{suffix}")

    def _cxx_exe(self):
        compiler = str(self.settings.compiler)
        version  = str(self.settings.compiler.version)
        os_      = str(self.settings.os)
        if compiler == "msvc":
            return "cl"
        elif compiler == "gcc":
            return "g++" if os_ == "Windows" else f"g++-{version}"
        elif compiler == "clang":
            return f"clang++-{version}"
        elif compiler == "apple-clang":
            return "clang++"
        return "c++"

    def _is_msvc(self):
        return str(self.settings.compiler) == "msvc"

    # ------------------------------------------------------------------
    # build2 bootstrap  (identical procedure to libodb recipe)
    # ------------------------------------------------------------------

    def _bootstrap_build2(self):
        """
        Bootstrap build2 `b` from the official release tarball.
        See libodb recipe for full layout commentary.

        Tarball layout (strip_root=True into b2_src):
            b2_src/build2/              ← b2_pkg
                bootstrap.sh / bootstrap-msvc.bat
                build2/                 ← b2_inner (compiler sources)
                    b-boot[.exe]        ← phase-1/2 output

        Phase 1:  CWD=b2_pkg   → build2/b-boot[.exe]
        Phase 2:  CWD=b2_pkg   → build2/b[.exe]  → renamed to build2/b-boot[.exe]
        Phase 3:  CWD=b2_src   → build2/build2/b-boot[.exe] configure + install
        """
        b2_src   = os.path.join(self.source_folder, self._b2_src)
        b2_pkg   = os.path.join(b2_src, "build2")
        b2_inner = os.path.join(b2_pkg, "build2")
        exe_sfx  = ".exe" if self.settings.os == "Windows" else ""
        b_boot   = os.path.join(b2_inner, f"b-boot{exe_sfx}")
        b_bin    = os.path.join(self.source_folder, self._b_bin)
        cxx      = self._cxx_exe()
        jobs     = build_jobs(self)

        # Phase 1
        if self._is_msvc():
            self.run(f"bootstrap-msvc.bat {cxx} /w", cwd=b2_pkg)
        else:
            bs = os.path.join(b2_pkg, "bootstrap.sh")
            os.chmod(bs, os.stat(bs).st_mode | stat.S_IEXEC)
            self.run(f"./bootstrap.sh {cxx} -w", cwd=b2_pkg)

        # Phase 2: rebuild b-boot with full build2 logic (static linkage)
        self.run(
            f"{b_boot} config.cxx={cxx} config.bin.lib=static build2/exe{{b}}",
            cwd=b2_pkg,
        )
        os.replace(os.path.join(b2_inner, f"b{exe_sfx}"), b_boot)

        # Phase 3: copy b-boot → b-bin/bin/b[.exe]
        # b-boot after Phase 2 is a fully-featured statically-linked b driver.
        # We avoid `b install:` because it tries to install the entire toolchain
        # (headers, docs, man pages) and fails on Windows when directories
        # don't pre-exist. A simple copy is sufficient.
        b_bin_dir = os.path.join(b_bin, "bin")
        os.makedirs(b_bin_dir, exist_ok=True)
        b_final = os.path.join(b_bin_dir, f"b{exe_sfx}")
        shutil.copy2(b_boot, b_final)
        if self.settings.os != "Windows":
            os.chmod(b_final, os.stat(b_final).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        self.output.info(f"build2 `b` ready at: {b_final}")

    # ------------------------------------------------------------------
    # Dependency path helpers
    # ------------------------------------------------------------------

    def _dep_dirs(self, name):
        """
        Return (include_dir, lib_dir) with forward slashes, single-quoted
        so build2's argument parser handles paths that contain spaces.
        """
        info = self.dependencies[name].cpp_info.aggregated_components()
        inc  = info.includedirs[0].replace("\\", "/")
        lib  = info.libdirs[0].replace("\\", "/")
        return inc, lib

    def _cc_flag(self, flag_type, value):
        """
        Build a build2 config assignment for a compiler/linker flag.
        No shell quoting — build2 is invoked directly (not via shell on Windows),
        so single/double quotes would be passed literally.
        Conan cache paths never contain spaces, so quoting is unnecessary.
        """
        if self._is_msvc():
            flag = f"/I{value}" if flag_type == "include" else f"/LIBPATH:{value}"
            key  = "config.cc.poptions" if flag_type == "include" else "config.cc.loptions"
        else:
            flag = f"-I{value}" if flag_type == "include" else f"-L{value}"
            key  = "config.cc.poptions" if flag_type == "include" else "config.cc.loptions"
        return f"{key}+={flag}"

    # ------------------------------------------------------------------
    # Conan lifecycle
    # ------------------------------------------------------------------

    def build(self):
        self._bootstrap_build2()

        b     = self._b_exe()
        cxx   = self._cxx_exe()
        jobs  = build_jobs(self)
        debug = self.settings.build_type in ("Debug", "RelWithDebInfo")

        odb_inc,   odb_lib   = self._dep_dirs("libodb")
        pgsql_inc, pgsql_lib = self._dep_dirs("libpq")

        args = [
            f"config.cxx={cxx}",
            "config.cxx.std=c++11",
            f"config.bin.debug={'true' if debug else 'false'}",
            f"config.bin.lib={'shared' if self.options.shared else 'static'}",
            self._cc_flag("include", odb_inc),
            self._cc_flag("include", pgsql_inc),
            self._cc_flag("libpath", odb_lib),
            self._cc_flag("libpath", pgsql_lib),
            "config.libodb_pgsql.develop=false",
        ]
        if self.options.shared and self.settings.os != "Windows":
            args.append(f"config.bin.rpath={self.package_folder}/lib")
        if not self.options.shared and self.options.get_safe("fPIC") and not self._is_msvc():
            args.append("config.cc.coptions+=-fPIC")
        if jobs > 1:
            args.insert(0, f"-j {jobs}")

        pgsql_src = os.path.join(self.source_folder, self._pgsql_src)
        # Build only the library (skip tests)
        self.run(f'"{b}" ' + " ".join(args) + " ./odb/pgsql/", cwd=pgsql_src)

    def package(self):
        pgsql_src = os.path.join(self.source_folder, self._pgsql_src)

        # Headers
        for pat in ("*.hxx", "*.ixx", "*.txx", "*.h"):
            copy(self, pat, os.path.join(pgsql_src, "odb", "pgsql"),
                 os.path.join(self.package_folder, "include", "odb", "pgsql"))

        # Libraries
        if self.options.shared:
            copy(self, "*.dll", pgsql_src, os.path.join(self.package_folder, "bin"), keep_path=False)
            copy(self, "*.so*", pgsql_src, os.path.join(self.package_folder, "lib"), keep_path=False)
            copy(self, "*.dylib", pgsql_src, os.path.join(self.package_folder, "lib"), keep_path=False)
            copy(self, "*.lib", pgsql_src, os.path.join(self.package_folder, "lib"), keep_path=False)
        else:
            copy(self, "*.lib", pgsql_src, os.path.join(self.package_folder, "lib"), keep_path=False)
            copy(self, "*.a",   pgsql_src, os.path.join(self.package_folder, "lib"), keep_path=False)

        copy(self, "LICENSE", pgsql_src, os.path.join(self.package_folder, "licenses"))
        rm(self, "*.pdb", self.package_folder, recursive=True)

    def package_info(self):
        self.cpp_info.libs = ["odb-pgsql"]
        self.cpp_info.set_property("cmake_file_name", "libodb-pgsql")
        self.cpp_info.set_property("cmake_target_name", "libodb-pgsql::libodb-pgsql")
        self.cpp_info.set_property("pkg_config_name", "libodb-pgsql")
        self.cpp_info.requires = ["libodb::libodb", "libpq::pq"]

        if not self.options.shared:
            self.cpp_info.defines.append("LIBODB_PGSQL_STATIC")
        if self.settings.os in ["Linux", "FreeBSD"]:
            self.cpp_info.system_libs.append("pthread")
        if self.settings.os == "Windows":
            self.cpp_info.system_libs.append("ws2_32")
