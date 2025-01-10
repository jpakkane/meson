#include <cstdio>
#include <cstring>
#include "src_only.h"
#include "build_only.h"

int main(int argc, char* argv[])
{
  if (argc != 3)
  {
    std::puts("Expect 2 args to compare with: " SRC_ONLY_MSG ", " BUILD_ONLY_MSG);
    return 1;
  }
  
  std::puts(SRC_ONLY_MSG ", " BUILD_ONLY_MSG);
  if (std::strcmp(SRC_ONLY_MSG, argv[1])==0 && std::strcmp(BUILD_ONLY_MSG, argv[2])==0)
    return 0;

  return 1;
}
