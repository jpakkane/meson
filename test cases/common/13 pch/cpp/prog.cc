// Note: if using PGI compilers, you will need to add #include "prog.hh"
// even though you're using precompiled headers.
void func() {
    std::cout << "This is a function that fails to compile if iostream is not included."
              << std::endl;
}

int main() {
    func();
    return 0;
}
