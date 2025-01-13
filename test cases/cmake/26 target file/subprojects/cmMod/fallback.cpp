#include <cassert>
#include <ctime>
#include <fstream>
#include <iostream>

int main(int argc, char *argv[]) {
  assert(argc == 3);
  std::ifstream source(argv[1], std::ios::binary);
  std::ofstream dest(argv[2], std::ios::binary);

  dest << source.rdbuf();

  source.close();
  dest.close();
}
