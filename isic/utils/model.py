# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/utils_model.ipynb (unless otherwise specified).

__all__ = ['set_require_grad', 'freeze_to', 'freeze', 'unfreeze', 'create_head', 'get_num_ftrs', 'params',
           'has_pool_type', 'create_body', 'requires_grad', 'init_default', 'cond_init', 'apply_leaf', 'apply_init',
           'norm_types', 'get_bias_batchnorm_params', 'print_grad_block', 'check_attrib_module',
           'get_module_with_attrib', 'lr_find', 'ParameterModule', 'has_params', 'total_params',
           'children_and_parameters', 'flatten_model', 'in_channels', 'one_param']

# Cell
from functools import partial

import matplotlib.pyplot as plt
from matplotlib.ticker import LogLocator, NullFormatter

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models

import pytorch_lightning as pl
from pytorch_lightning.core import LightningModule
from pytorch_lightning.metrics import functional as FM

from ..layers import LabelSmoothingCrossEntropy, LinBnDrop, AdaptiveConcatPool2d
from ..callback.freeze import FreezeCallback, UnfreezeCallback
from .core import first

# Cell
def set_require_grad(p, b):
    if getattr(p, 'force_train', False):
        p.requires_grad_(True)
        return
    p.requires_grad_(b)

def freeze_to(n, model, n_groups):
    frozen_idx = n if n >= 0 else n_groups + n
    if frozen_idx >= n_groups:
        #TODO use warnings.warn
        print(f"Freezing {frozen_idx} groups; model has {n_groups}; whole model is frozen.")
    for ps in model.get_params(split_bn=False)[n:]:
        for p in ps:
            # require_grad -> True
            set_require_grad(p, True)
    for ps in model.get_params(split_bn=False)[:n]:
        for p in ps:
            # require_grad -> False
            set_require_grad(p, False)

def freeze(model, n_groups):
    assert(n_groups>1)
    freeze_to(-1, model, n_groups)

def unfreeze(model, n_groups):
    freeze_to(0, model, n_groups)

# Cell
def create_head(n_in, n_out, lin_ftrs=None, p=0.5, concat_pool=True):
    n_in = n_in * (2 if concat_pool else 1)
    lin_ftrs = [n_in, 512, n_out] if lin_ftrs is None else [n_in] + lin_ftrs + [n_out]
    p_dropouts = [p/2] * (len(lin_ftrs) - 2) + [p]
    activations = [nn.ReLU(inplace=True)] * (len(lin_ftrs) - 2) + [None]
    pool = AdaptiveConcatPool2d() if concat_pool else nn.AdaptiveAvgPool2d(1)
    layers = [pool, nn.Flatten()]
    for ni, no, p, actn in zip(lin_ftrs[:-1], lin_ftrs[1:], p_dropouts, activations):
        layers += LinBnDrop(ni, no, bn=True, p=p, act=actn)

    return nn.Sequential(*layers)

# Cell
def get_num_ftrs(model, cut):
    # TODO: Handle if used models using 1 channel
    c_in, h, w = 3, 64, 64
    modules = list(model.children())[:cut]
    test = nn.Sequential(*modules)
    x = torch.rand(1 , c_in, h, w)
    out = test.eval()(x)
    return out.shape[1]

# Cell
def params(m):
    "Return all parameters of `m`"
    return list(m.parameters())

def has_pool_type(m):
    def _is_pool_type(l): return re.search(r'Pool[123]d$', l.__class__.__name__)
    "Return `True` if `m` is a pooling layer or has one in its children"
    if _is_pool_type(m): return True
    for l in m.children():
        if has_pool_type(l): return True
    return False

def create_body(arch):
    def _xresnet_split(m):
        return [params(m[0][:3]), params(m[0][3:]), params(m[1:])]
    def _resnet_split(m):
        return [params(m[0][:6]), params(m[0][6:]), params(m[1:])]
    def _squeezenet_split(m):
        return [params(m[0][0][:5]), params(m[0][0][5:]), params(m[1:])]
    def _densenet_split(m:nn.Module):
        return [params(m[0][0][:7]), params(m[0][0][7:]), params(m[1:])]
    def _vgg_split(m:nn.Module):
        return [params(m[0][0][:22]), params(m[0][0][22:]), params(m[1:])]
    def _alexnet_split(m:nn.Module):
        return [params(m[0][0][:6]), params(m[0][0][6:]), params(m[1:])]

    model = getattr(models, arch)(pretrained=True)

    if 'xresnet' in arch:
        cut = -4
        split = _xresnet_split
    elif 'resnet' in arch:
        cut = -2
        split = _resnet_split
        num_ftrs = model.fc.in_features
    elif 'squeeze' in arch:
        cut = -1
        split = _squeezenet_split
    elif 'dense' in arch:
        cut = -1
        split = _densenet_split
    elif 'vgg' in arch:
        cut = -2
        split = _vgg_split
        num_ftrs = 512
    elif 'alex' in arch:
        cut = -2
        split = _alexnet_split
    else:
        ll = list(enumerate(model.children()))
        cut = next(i for i,o in reversed(ll) if has_pool_type(o))
        split = params
    return nn.Sequential(*list(model.children())[:cut]), split, num_ftrs

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
        r = get_bias_batchnorm_params(c, with_bias)
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


def check_attrib_module(ms, attribs=['requires_grad', 'skip_wd']):
    """
        This version only print the smallest module
    """
    for m in ms.children():
        if len(list(m.children()))>0:
            check_attrib_module(m, attribs)
            continue
        print(m)
        r = []
        for name, p in m.named_parameters():
            for attr in attribs:
                if hasattr(p, attr):
                    r.append(name + '-' + attr + '-'+ str(getattr(p, attr)))
        print(r)

def get_module_with_attrib(model, attrib='requires_grad'):
    for n, p in model.named_parameters():
        if getattr(p, attrib, False):
            print(n)

# Cell
def lr_find(model, dm, min_lr=1e-7, max_lr=10, n_train=100, exp=True, cpu=True, lr_find=True, verbose=False):
    args = {}
    lr_finder=None
    if not cpu:
        args = {
            "gpus": 1,
            "precision": 16
        }
    if lr_find:
        trainer = pl.Trainer(max_epochs=1, **args)
        lr_finder = trainer.lr_find(model, dm.train_dataloader(), dm.val_dataloader(),
                                    min_lr=min_lr, max_lr=max_lr,
                                    num_training=n_train,
                                    mode='exponential' if exp else 'linear', early_stop_threshold=1e10)

        # Inspect results
        lrs, losses = lr_finder.results['lr'], lr_finder.results['loss']
        fig, ax = plt.subplots(1,1)
        ax.plot(lrs, losses)
        ax.set_xscale('log')
        ax.xaxis.set_major_locator(LogLocator(base=10, numticks=12))
        locmin = LogLocator(base=10.0,subs=np.arange(2, 10, 2)*.1,numticks=12)
        ax.xaxis.set_minor_locator(locmin)
        ax.xaxis.set_minor_formatter(NullFormatter())

        opt_lr = lr_finder.suggestion()

        ax.plot(lrs[lr_finder._optimal_idx], losses[lr_finder._optimal_idx],
                markersize=10, marker='o', color='red')
        ax.set_ylabel("Loss")
        ax.set_xlabel("Learning Rate")
        print(f'LR suggestion: {opt_lr:e}')

    else:
        trainer = pl.Trainer(max_epochs=1, fast_dev_run=True, **args)
        trainer.fit(model, dm)
    if verbose:
        print(trainer.optimizers[0])
        print(('*'*30)+'Check requires_grad/ skip_wd' + ('*'*30))
        check_attrib_module(model.model[0])
        print('-' * 80)
        check_attrib_module(model.model[1])

    return lr_finder

# Cell
class ParameterModule(nn.Module):
    "Register a lone parameter `p` in a module."
    def __init__(self, p): self.val = p
    def forward(self, x): return x

# Cell
def _has_children(m):
    try: next(m.children())
    except StopIteration: return False
    return True

# Cell
def has_params(m):
    "Check if `m` has at least one parameter"
    return len(list(m.parameters())) > 0

def total_params(m):
    "Give the number of parameters of a module and if it's trainable or not"
    params = sum([p.numel() for p in m.parameters()])
    trains = [p.requires_grad for p in m.parameters()]
    return params, (False if len(trains)==0 else trains[0])

# Cell
nn.Module.has_children = property(_has_children)

# Cell
def children_and_parameters(m):
    "Return the children of `m` and its direct parameters not registered in modules."
    children = list(m.children())
    children_p = sum([[id(p) for p in c.parameters()] for c in m.children()],[])
    for p in m.parameters():
        if id(p) not in children_p: children.append(ParameterModule(p))
    return children

def flatten_model(m):
    "Return the list of all submodules and parameters of `m`"
    return sum(map(flatten_model,children_and_parameters(m)),[]) if m.has_children else [m]

# Cell
def in_channels(m):
    "Return the shape of the first weight layer in `m`."
    for l in flatten_model(m):
        if getattr(l, 'weight', None) is not None and l.weight.ndim==4:
            return l.weight.shape[1]
    raise Exception('No weight layer')

# Cell
def one_param(m):
    "First parameter in `m`"
    return first(m.parameters())