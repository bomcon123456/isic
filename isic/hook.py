# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/hook.ipynb (unless otherwise specified).

__all__ = ['Hook', 'Hooks', 'hook_output', 'hook_outputs', 'dummy_eval', 'model_sizes', 'num_features_model',
           'layer_info', 'module_summary']

# Cell
import warnings
import re

import torch
from torch import Tensor
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models

# Cell
from .utils.core import reduce_loss, generate_val_steps, is_listy, to_detach, apply, PrettyString
from .utils.model import flatten_model, in_channels, one_param, create_body, total_params

# Cell
class Hook:
    def __init__(self, m, hook_func, is_forward=True, detach=True, cpu=False):
        self.hook_func = hook_func
        self.detach = detach
        self.cpu = cpu
        f = m.register_forward_hook if is_forward else m.register_backward_hook
        self.hook = f(self.hook_fn)
        self.stored, self.removed = None, False

    def hook_fn(self, module, input, output):
        if self.detach:
            input, output = to_detach(input, cpu=self.cpu), to_detach(output, cpu=self.cpu)
        self.stored = self.hook_func(module, input, output)

    def remove(self):
        if not self.removed:
            self.hook.remove()
            self.removed = True

    def __enter__(self, *args): return self
    def __exit__(self, *args): self.remove()

# Cell
class Hooks:
    def __init__(self, ms, hook_func, is_forward=True, detach=True, cpu=False):
        self.hooks = [Hook(m, hook_func, is_forward, detach, cpu) for m in ms]

    def __getitem__(self, i): return self.hooks[i]
    def __len__(self): return len(self.hooks)
    def __iter__(self): return iter(self.hooks)

    @property
    def stored(self): return list([o.stored for o in self])

    def remove(self):
        for h in self.hooks:
            h.remove()

    def __enter__(self, *args): return self
    def __exit__(self, *args): self.remove()

# Cell
def _hook_inner(m,i,o):
    "Function that returns ouput of a layer."
    return o if isinstance(o, Tensor) or is_listy(o) else list(o)

def hook_output(module, detach=True, cpu=False, grad=False):
    "Return a `Hook` that stores outputs of `module` in `self.stored`"
    return Hook(module, _hook_inner, detach=detach, cpu=cpu, is_forward=not grad)

def hook_outputs(modules, detach=True, cpu=False, grad=False):
    "Return `Hooks` that store outputs of all `modules` in `self.stored`"
    return Hooks(modules, _hook_inner, detach=detach, cpu=cpu, is_forward=not grad)

# Cell
def dummy_eval(m, size=(64,64)):
    "Evaluate `m` on a dummy input of a certain `size`"
    ch_in = in_channels(m)
    x = one_param(m).new(1, ch_in, *size).requires_grad_(False).uniform_(-1.,1.)
    with torch.no_grad(): return m.eval()(x)

# Cell
def model_sizes(m, size=(64,64)):
    "Pass a dummy input through the model `m` to get the output size of each layers."
    with hook_outputs(m) as hooks:
        _ = dummy_eval(m, size=size)
        return [o.stored.shape for o in hooks]

# Cell
def num_features_model(m):
    "Return the number of output features for `m`."
    sz,ch_in = 32,in_channels(m)
    while True:
        #Trying for a few sizes in case the model requires a big input size.
        try:
            return model_sizes(m, (sz,sz))[-1][1]
        except Exception as e:
            sz *= 2
            if sz > 2048: raise e

# Cell
def layer_info(model, xb):
    "Return layer infos of `model` on `xb`"
    def _track(m, i, o): return (m.__class__.__name__,)+total_params(m)+(apply(lambda x:x.shape, o),)
    with Hooks(flatten_model(model), _track) as h:
        batch = apply(lambda o:o[:1], xb)
        r = model.eval()(batch)
        return h.stored

# Cell
def _print_shapes(o, bs):
    "Print shape with format BS x CHANNELS x HEIGHT x WIDTH"
    if isinstance(o, torch.Size): return ' x '.join([str(bs)] + [str(t) for t in o[1:]])
    else: return str([_print_shapes(x, bs) for x in o])

# Cell
def module_summary(model, bs=64, size=(3, 64, 64)):
    "Print a summary (input/output of each layer, #params, trainabled) of `model` depends on the `size` of a batch"
    xb = torch.rand(bs, *size)
    infos = layer_info(model, xb)
    line_size = 64
    inp_sz = _print_shapes(apply(lambda x:x.shape, xb), bs)
    res = f"{model.__class__.__name__} (Input shape: {inp_sz})\n"
    res += "=" * line_size + "\n"
    res += f"{'Layer (type)':<20} {'Output Shape':<20} {'Param #':<10} {'Trainable':<10}\n"
    res += "=" * line_size + "\n"
    ps,trn_ps = 0,0
    infos = [o for o in infos if o is not None] #see comment in previous cell
    for typ,np,trn,sz in infos:
        if sz is None: continue
        ps += np
        if trn: trn_ps += np
        res += f"{typ:<20} {_print_shapes(sz, bs)[:19]:<20} {np:<10,} {str(trn):<10}\n"
        res += "_" * line_size + "\n"
    res += f"\nTotal params: {ps:,}\n"
    res += f"Total trainable params: {trn_ps:,}\n"
    res += f"Total non-trainable params: {ps - trn_ps:,}\n\n"
    return PrettyString(res)