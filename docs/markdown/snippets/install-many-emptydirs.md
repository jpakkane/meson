## [[install_emptydir]] now supports multiple dirs inside one call

Prior to this release passing multiple paths as `dirpath` argument was resulting in only the first path to get created. Now passing more than one path in `dirpath` will create all of them.
