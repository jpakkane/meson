#include <cassert>
#include <string>

std::string getStr1();
std::string getStr2();
void testGetStr() {
  assert(getStr1() == "Hello World 1");
  assert(getStr2() == "Hello World 2");
}
