# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/utils.ipynb (unless otherwise specified).

__all__ = ['listify', 'is_listy', 'camel2snake', 'snakify_class_name', 'get_default_device']

# Cell
from collections import Iterable
from collections.abc import Generator
import re

import torch

# Cell
def listify(o):
    if o is None: return []
    if isinstance(o, list): return o
    if isinstance(o, str): return o
    if isinstance(o, Iterable): return list(o)
    return [o]

# Cell
def is_listy(x):
    "`isinstance(x, (tuple,list,L))`"
    return isinstance(x, (tuple, list, slice, Generator))

# Cell
_camel_re1 = re.compile('(.)([A-Z][a-z]+)')
_camel_re2 = re.compile('([a-z0-9])([A-Z])')


def camel2snake(name):
    s1 = re.sub(_camel_re1, r'\1_\2', name)
    return re.sub(_camel_re2, r'\1_\2', s1).lower()

# Cell
def snakify_class_name(obj, cls_name):
    return camel2snake(re.sub(rf'{cls_name}$', '', obj.__class__.__name__) or cls_name.lower())

# Cell
def get_default_device(use_cuda=None):
    "Return or set default device; `use_cuda`: None - CUDA if available; True - error if not availabe; False - CPU"
    b_GPU = use_cuda or (torch.cuda.is_available() and use_cuda is None)
    assert torch.cuda.is_available() or not b_GPU
    return torch.device(torch.cuda.current_device()) if b_GPU else torch.device('cpu')
