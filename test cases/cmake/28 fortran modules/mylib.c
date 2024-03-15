#if defined _WIN32 || defined __CYGWIN__
  #define DLL_PUBLIC __declspec(dllexport)
#else
  #if defined __GNUC__
    #define DLL_PUBLIC __attribute__ ((visibility("default")))
  #else
    #pragma message ("Compiler does not support symbol visibility.")
    #define DLL_PUBLIC
  #endif
#endif
extern void layers_of_calculations(int* input, int* output);

int DLL_PUBLIC c_lib_function(int input) {
    int output;
    layers_of_calculations(&input, &output);
    return output;
}
