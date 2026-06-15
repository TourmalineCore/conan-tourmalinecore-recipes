# conan-tourmalinecore-recipes

Repository for conan recipes used in the Tourmaline Core organization.

## Local testing

### Windows

System requirements:
* Installed Python with pip latest version https://www.python.org/downloads/
* Installed conan `pip install conan`
* Installed Build Tools for Visual Studio with Desktop development with C++ https://visualstudio.microsoft.com/downloads/?q=build+tools#build-tools-for-visual-studio-2026

1. Run the `Developer Command Prompt for VS` from the *Start bar* with Administrator rights. 
2. Move workspace of terminal into `conan-tourmalinecore-recipes` repository folder.
3. Run `conan create recipes/libodb/all --version=2.5.0 -b missing`

## Known issues

#### Stuck in `libname/X.Y.Z: Calling source() in C:\Users\user\.conan2\p\libname************\s\src`.
Please use another network with access to sources. Requested url you might find in `recipes\libname\all\conandata.yml` file.
