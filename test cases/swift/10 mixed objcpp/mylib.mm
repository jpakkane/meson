#include "mylib.h"
#include <iostream>

Test::Test() {
    std::cout << "Test initialized" << std::endl;
}

void Test::testCallFromClass() {
    std::cout << "Calling Objective-C++ class function from Swift is working" << std::endl;
}

@implementation ObjCPPTest
- (id)init {
    self = [super init];
    if (self) {
        test = new Test();
    }
    return self;
}

- (void)dealloc {
    delete test;
    [super dealloc];
}

- (void)testCallToObjCPP {
    test->testCallFromClass();
}
@end
