#pragma once
#import <Foundation/Foundation.h>

class Test {
public:
    Test();

    void testCallFromClass();
};

@interface ObjCPPTest: NSObject {
    @private Test *test;
}
- (id)init;
- (void)dealloc;
- (void)testCallToObjCPP;
@end
