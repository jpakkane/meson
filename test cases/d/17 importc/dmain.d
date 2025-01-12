import file1 : type_defined_in_c;
import file2 : triple_arg;

int main() {
    type_defined_in_c ret = triple_arg(2);

    return !(ret == 6);
}
