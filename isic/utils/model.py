# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/utils_model.ipynb (unless otherwise specified).

__all__ = ['set_require_grad', 'freeze_to', 'freeze', 'unfreeze', 'get_num_ftrs', 'params', 'has_pool_type',
           'create_head', 'create_body', 'apply_leaf', 'apply_init', 'get_bias_batchnorm_params', 'print_grad_block',
           'check_attrib_module', 'get_module_with_attrib', 'plot_lr_loss', 'lr_find', 'ParameterModule', 'has_params',
           'total_params', 'children_and_parameters', 'flatten_model', 'in_channels', 'one_param',
           'log_metrics_per_key', 'FocalLoss']

# Cell
from functools import partial
import re

import matplotlib.pyplot as plt
from matplotlib.ticker import LogLocator, NullFormatter

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models
from torch.autograd import Variable

import pytorch_lightning as pl
from pytorch_lightning.core import LightningModule
from pytorch_lightning.metrics import functional as FM

from ..layers import LabelSmoothingCrossEntropy, LinBnDrop, AdaptiveConcatPool2d, sigmoid, sigmoid_, norm_types, cond_init
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
def get_num_ftrs(model, cut):
    # TODO: Handle if used models using 1 channel
    c_in, h, w = 3, 64, 64
    modules = list(model.children())[:cut]
    test = nn.Sequential(*modules)
    x = torch.rand(1 , c_in, h, w)
    out = test.eval()(x)
    return out.shape[1]

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
def create_body(arch):
    from ..hook import num_features_model

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

    if isinstance(arch, str):
        model = getattr(models, arch)(pretrained=True)
        if 'xresnet' in arch:
            cut = -4
            split = _xresnet_split
        elif 'resnet' in arch:
            cut = -2
            split = _resnet_split
        elif 'squeeze' in arch:
            cut = -1
            split = _squeezenet_split
        elif 'dense' in arch:
            cut = -1
            split = _densenet_split
        elif 'vgg' in arch:
            cut = -2
            split = _vgg_split
        elif 'alex' in arch:
            cut = -2
            split = _alexnet_split
        else:
            ll = list(enumerate(model.children()))
            cut = next(i for i,o in reversed(ll) if has_pool_type(o))
            split = params
        body = nn.Sequential(*list(model.children())[:cut])
    else:
        model = arch
        ll = list(enumerate(model.children()))
        cut = next(i for i,o in reversed(ll) if has_pool_type(o))
        split = params
        body = nn.Sequential(*list(model.children())[:cut])
    num_ftrs = num_features_model(body)

    return body, split, num_ftrs

# Cell
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
def plot_lr_loss(lrs, losses):
    fig, ax = plt.subplots(1,1)
    ax.plot(lrs, losses)
    ax.set_xscale('log')
    ax.xaxis.set_major_locator(LogLocator(base=10, numticks=12))
    locmin = LogLocator(base=10.0,subs=np.arange(2, 10, 2)*.1,numticks=12)
    ax.xaxis.set_minor_locator(locmin)
    ax.xaxis.set_minor_formatter(NullFormatter())
    return fig, ax

# Cell
def lr_find(model, dm, min_lr=1e-7, max_lr=1., n_train=100,
            exp=True, cpu=False, fast_dev_run=False, skip_last=5, verbose=False):
    args = {}
    lr_finder=None
    if not cpu:
        args = {
            "gpus": 1,
            "precision": 16
        }
    if fast_dev_run:
        trainer = pl.Trainer(fast_dev_run=True, **args)
        trainer.fit(model, dm)
    else:
        trainer = pl.Trainer(max_epochs=1, **args)
        lr_finder = trainer.tuner.lr_find(model, dm.train_dataloader(), dm.val_dataloader(),
                                    min_lr=min_lr, max_lr=max_lr,
                                    num_training=n_train,
                                    mode='exponential' if exp else 'linear', early_stop_threshold=None)

        # Inspect results
        lrs, losses = lr_finder.results['lr'][:-skip_last], lr_finder.results['loss'][:-skip_last]
        fig, ax = plot_lr_loss(lrs, losses)

        opt_lr = lr_finder.suggestion()

        ax.plot(lrs[lr_finder._optimal_idx], losses[lr_finder._optimal_idx],
                markersize=10, marker='o', color='red')
        ax.set_ylabel("Loss")
        ax.set_xlabel("Learning Rate")
        print(f'LR suggestion: {opt_lr:e}')

    if verbose:
        print('Optimizer Information:')
        print(trainer.optimizers[0])
        print('='*88)
        print(('*'*30)+'Check requires_grad/ skip_wd' + ('*'*30))
        print(('-'*40)+'    BODY    ' + ('-'*40))
        check_attrib_module(model.model[0])
        print(('*'*40)+'    HEAD    ' + ('*'*40))
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

# Cell
def log_metrics_per_key(logger, metrics):
    keys = ['akiec', 'bcc', 'bkl', 'df', 'nv', 'mel', 'vasc']
    for m_k, v in metrics.items():
        for i,k in enumerate(keys):
            logger.log(f"val_{m_k}_{k}", v[i], prog_bar=True)
            logger.log(f"val_{m_k}_{k}", v[i], prog_bar=True)

# Cell
class FocalLoss(nn.Module):
    def __init__(self, class_num, alpha=None, gamma=2, size_average=True):
        super(FocalLoss, self).__init__()
        if alpha is None:
            self.alpha = Variable(torch.ones(class_num, 1))
        else:
            if isinstance(alpha, Variable):
                self.alpha = alpha
            else:
                self.alpha = Variable(alpha)
        self.gamma = gamma
        self.class_num = class_num
        self.size_average = size_average

    def forward(self, inputs, targets):
        device = inputs.device
        N = inputs.size(0)
        C = inputs.size(1)
        P = F.softmax(inputs)
        class_mask = inputs.data.new(N, C).fill_(0)
        class_mask = Variable(class_mask)
        ids = targets.view(-1, 1)
        class_mask.scatter_(1, ids.data, 1.)
        #print(class_mask)
        if inputs.is_cuda and not self.alpha.is_cuda:
            self.alpha = self.alpha.to(device)
        alpha = self.alpha[ids.data.view(-1)]
        probs = (P*class_mask).sum(1).view(-1,1)
        log_p = probs.log()
        #print('probs size= {}'.format(probs.size()))
        #print(probs)
        batch_loss = -alpha*(torch.pow((1-probs), self.gamma))*log_p
        #print('-----bacth_loss------')
        #print(batch_loss)
        if self.size_average:
            loss = batch_loss.mean()
        else:
            loss = batch_loss.sum()
        return loss