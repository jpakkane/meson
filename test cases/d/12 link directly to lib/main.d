import std.stdio;
import std.string;
import std.conv;

extern (C++) int char_to_int(const char * value);

int main(string[] args)
{
    char * c = cast(char *) toStringz(args[1]);
    int i = char_to_int(c);
    return i;
}
