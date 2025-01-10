int main() {
    #ifdef _MSVC_LANG
        static_assert(_MSVC_LANG >= EXPECTED);
    #else
        static_assert(__cplusplus >= EXPECTED);
    #endif
    return 0;
}