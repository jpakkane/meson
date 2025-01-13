#include <cassert>
#include <fstream>
#include <iostream>
#include <sstream>

using namespace std;

int main(int argc, const char *argv[]) {
  if (argc < 3) {
    cerr << argv[0] << " requires an input and output file!" << endl;
    return 1;
  }

  ifstream in(argv[1]);
  cerr << in.is_open() << "\t" << argv[1];
  stringstream buffer;
  buffer << in.rdbuf();
  cerr << buffer.str() << "\n";
  assert(buffer.str() == "example content\n");

  ofstream out(argv[2]);
  out << R"(
#include <string>
std::string getStr1() {
  return "Hello World 1";
}
)";

  return 0;
}
