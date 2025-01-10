#include <cstdio>
#include <cstring>
#include "whereareyoufindingme.h"

int main(int argc, char* argv[])
{
  if (argc != 2)
  {
    std::puts("No input string to compare with: " MSG_FROM_HEADER);
    return 1;
  }
  
  std::puts(MSG_FROM_HEADER);
  return std::strcmp(MSG_FROM_HEADER, argv[1]);
}
