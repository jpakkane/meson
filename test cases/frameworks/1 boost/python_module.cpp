#define PY_SSIZE_T_CLEAN
#ifdef _DEBUG
#undef _DEBUG
#include <Python.h>
#include <boost/python.hpp>
#define _DEBUG
#else
#include <Python.h>
#include <boost/python.hpp>
#endif


struct World
{
    void set(std::string msg) { this->msg = msg; }
    std::string greet() { return msg; }
    std::string version() { return std::to_string(PY_MAJOR_VERSION) + "." + std::to_string(PY_MINOR_VERSION); }
    std::string msg;
};


BOOST_PYTHON_MODULE(MOD_NAME)
{
    using namespace boost::python;
    class_<World>("World")
        .def("greet", &World::greet)
        .def("set", &World::set)
        .def("version", &World::version)
    ;
}
