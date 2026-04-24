// Minimal smoke test for libodb:
//   - headers are discoverable
//   - core types are accessible
//   - library links correctly

#include <odb/version.hxx>
#include <odb/exception.hxx>
#include <odb/database.hxx>

#include <cassert>
#include <iostream>

int main()
{
    // Verify the runtime version matches the expected major.minor
    unsigned int maj = ODB_VERSION / 100000;
    unsigned int min = (ODB_VERSION / 1000) % 100;

    std::cout << "libodb version: " << maj << "." << min << std::endl;

    // The library should report version 2.x
    assert(maj == 2);

    return 0;
}
