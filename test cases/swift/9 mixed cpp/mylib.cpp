#include "mylib.h"
#include <iostream>

Test::Test() {
    std::cout << "Test initialized" << std::endl;
}
    
Test::Test(int param) {
    std::cout << "Test initialized with param " << param << std::endl;
}

void Test::testCallFromClass() {
    std::cout << "Calling C++ class function from Swift is working" << std::endl;
}

void testCallFromSwift() {
    std::cout << "Calling this C++ function from Swift is working" << std::endl;
}

void testCallWithParam(const std::string &param) {
    std::cout << param << std::endl;
}
