using Foo;
using Bar;
using Baz;

class Main : GLib.Object {
    public static int main(string[] args) {
        var ignore = Foo.Foo.return_success();
        return Bar.Bar.return_success();
    }
}
