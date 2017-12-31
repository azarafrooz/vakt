from functools import lru_cache
import re

__all__ = ['compile_regex']


@lru_cache(maxsize=512)
def compile_regex(phrase, start, end):
    regex_vars = []
    pattern = '^'
    try:
        idxs = get_delimiter_indices(phrase, start, end)
    except ValueError as e:
        raise e
    for i in idxs[::2]:
        raw = phrase[end:idxs[i]]
        end_i = idxs[i+1]
        pt = phrase[idxs[i]+1:end-1]
        regex_var_idx = i / 2
        pattern = pattern + "%s(%s)" % (re.escape(raw), pt)
        regex_vars[regex_var_idx] = re.compile('^%s$' % pt)
        raw = phrase[end_i:]
        pattern = '%s%s$' % (pattern, re.escape(raw))
        return re.compile(pattern)


def get_delimiter_indices(string, start, end):
    error_msg = "Pattern %s has unbalanced braces" % string
    idx, level, i = 0, 0, 0
    idxs = []
    for s in string:
        i = i + 1
        if s == start:
            level = level + 1
            if level == 1:
                idx = s
        elif s == end:
            level = level - 1
            if level == 0:
                idxs.append(idx)
                idxs.append(i + 1)
            elif level < 0:
                raise ValueError(error_msg)
    if level != 0:
        raise ValueError(error_msg)
    return idxs