#from ..mesonlib import MesonException

def stringifyUserArguments(args, quote=False, ex=Exception()):
    if isinstance(args, list):
        return '[%s]' % ', '.join([stringifyUserArguments(x, True, ex) for x in args])
    elif isinstance(args, dict):
        return '{%s}' % ', '.join(['{} : {}'.format(stringifyUserArguments(k, True, ex), stringifyUserArguments(v, True, ex)) for k, v in args.items()])
    elif isinstance(args, int):
        return str(args)
    elif isinstance(args, str):
        return f"'{args}'" if quote else args
    raise ex('Function accepts only strings, integers, lists and lists thereof.')
