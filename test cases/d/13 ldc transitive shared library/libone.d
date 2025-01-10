import libtwo;

export int printLibraryString(string str)
{
    printLibraryString2(str);
    return 4;
}

version (Windows)
{
    import core.sys.windows.dll;
    mixin SimpleDllMain;
}
