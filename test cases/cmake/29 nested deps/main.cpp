#include <iostream>

#define cmModClass cmModClass1
#include <cmMod.hpp>

#undef cmModClass
#define cmModClass cmModClass2
#include <cmMod.hpp>

using namespace std;

int main(void) {
  cmModClass1 obj1("Hello1");
  cmModClass2 obj2("Hello2");
  cout << obj1.getStr() << endl;
  cout << obj2.getStr() << endl;
  return 0;
}
