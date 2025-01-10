import std.stdio;
import std.string : format;

export int printLibraryString2(string str)
{
    writeln ("Library says: %s".format (str));
    return 4;
}

version (Windows)
{
    import core.sys.windows.dll;
    mixin SimpleDllMain;
}
