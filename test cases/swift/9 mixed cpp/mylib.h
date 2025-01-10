#pragma once
#include <string>

class Test {
public:
    Test();
    Test(int param);

    void testCallFromClass();
};

void testCallFromSwift();
void testCallWithParam(const std::string &param);
