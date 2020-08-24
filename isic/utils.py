# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/utils.ipynb (unless otherwise specified).

__all__ = ['listify', 'is_listy', 'camel2snake', 'snakify_class_name', 'get_default_device', 'unsqueeze', 'reduce_loss',
           'NoneReduce', 'requires_grad', 'init_default', 'cond_init', 'apply_leaf', 'apply_init', 'norm_types',
           'get_bias_batchnorm_params', 'print_grad_block', 'print_grad_module', 'even_mults', 'generate_val_steps']

# Cell
import numpy as np
import torch.nn as nn

from functools import partial
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


# Cell
def unsqueeze(x, dim=-1, n=1):
    "Same as `torch.unsqueeze` but can add `n` dims"
    for _ in range(n): x = x.unsqueeze(dim)
    return x

# Cell
def reduce_loss(loss, reduction='mean'):
    return loss.mean() if reduction=='mean' else loss.sum() if reduction=='sum' else loss

# Cell
class NoneReduce():
    "A context manager to evaluate `loss_func` with none reduce."
    def __init__(self, loss_func): self.loss_func,self.old_red = loss_func,None

    def __enter__(self):
        if hasattr(self.loss_func, 'reduction'):
            self.old_red = self.loss_func.reduction
            self.loss_func.reduction = 'none'
            return self.loss_func
        else: return partial(self.loss_func, reduction='none')

    def __exit__(self, type, value, traceback):
        if self.old_red is not None: self.loss_func.reduction = self.old_red


# Cell
def requires_grad(m):
    "Check if the first parameter of `m` requires grad or not"
    ps = list(m.parameters())
    return ps[0].requires_grad if len(ps)>0 else False

# Cell
norm_types = (nn.BatchNorm1d, nn.BatchNorm2d, nn.BatchNorm3d, nn.InstanceNorm1d, nn.InstanceNorm2d, nn.InstanceNorm3d, nn.LayerNorm)

def init_default(m, func=nn.init.kaiming_normal_):
    "Initialize `m` weights with `func` and set `bias` to 0."
    if func:
        if hasattr(m, 'weight'): func(m.weight)
        if hasattr(m, 'bias') and hasattr(m.bias, 'data'): m.bias.data.fill_(0.)
    return m

def cond_init(m, func):
    "Apply `init_default` to `m` unless it's a batchnorm module"
    if (not isinstance(m, norm_types)) and requires_grad(m): init_default(m, func)

def apply_leaf(m, f):
    "Apply `f` to children of `m`."
    c = m.children()
    if isinstance(m, nn.Module): f(m)
    for l in c: apply_leaf(l,f)

# Cell
def apply_init(m, func=nn.init.kaiming_normal_):
    "Initialize all non-batchnorm layers of `m` with `func`."
    apply_leaf(m, partial(cond_init, func=func))


# Cell
def get_bias_batchnorm_params(m, with_bias=True):
    "Return all bias and and BatchNorm params"
    if isinstance(m, norm_types):
        return list(m.parameters())
    res = []
    for c in m.children():
        r = get_bias_batchnorm_params(c)
        res += r
    if with_bias and getattr(m, 'bias', None) is not None:
        res.append(m.bias)
    return res

# Cell
def print_grad_block(ms):
    """
        This version still print block module
    """
    for m in ms.children():
        r = []
        print(m)
        for p in m.parameters():
            if hasattr(p, 'requires_grad'):
                r.append(p.requires_grad)
        print(r)


def print_grad_module(ms):
    """
        This version only print the smallest module
    """
    for m in ms.children():
        if len(list(m.children()))>0:
            print_grad_module(m)
            continue
        print(m)
        r = []
        for p in m.parameters():
            if hasattr(p, 'requires_grad'):
                r.append(p.requires_grad)
        print(r)

# Cell
def even_mults(start, stop, n):
    "Build log-stepped array from `start` to `stop` in `n` steps."
    if n==1: return stop
    mult = stop/start
    step = mult**(1/(n-1))
    return np.array([start*(step**i) for i in range(n)])

# Cell
def generate_val_steps(val, n):
    if isinstance(val, slice):
        if val.start:
            val = even_mults(val.start, val.stop, n)
        else:
            val = [val.stop/10] * (n - 1) + [val.stop]
    vs = listify(val)
    if len(vs) == 1:
        vs = vs * n
    return vs