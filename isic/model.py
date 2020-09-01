# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/model.ipynb (unless otherwise specified).

__all__ = ['Model', 'fit_one_cycle']

# Cell
import warnings
import re
from functools import partial

import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models

import pytorch_lightning as pl
from pytorch_lightning.core import LightningModule
from pytorch_lightning.metrics import functional as FM

# Cell
from .dataset import SkinDataModule
from .layers import LabelSmoothingCrossEntropy
from .callback.hyperlogger import HyperparamsLogger
from .callback.logtable import LogTableMetricsCallback
from .callback.mixup import MixupDict
from .callback.cutmix import CutmixDict
from .callback.freeze import FreezeCallback, UnfreezeCallback
from .utils.core import reduce_loss, generate_val_steps
from .utils.model import apply_init, get_bias_batchnorm_params, apply_leaf, check_attrib_module, create_body, create_head, lr_find, freeze, unfreeze

# Cell
class Model(LightningModule):
    def __init__(self, lr=1e-2, wd=0., n_out=7, concat_pool=True, arch='resnet50'):
        super().__init__()
        self.save_hyperparameters()
        # create body
        body, self.split, num_ftrs = create_body(arch)

        # create head
        head = create_head(num_ftrs, n_out)

        #model
        self.model = nn.Sequential(body, head)
        apply_init(self.model[1])

        # Setup so that batchnorm will not be freeze.
        for p in get_bias_batchnorm_params(self.model, False):
            p.force_train = True
        # Setup so that biases and batchnorm will skip weight decay.
        for p in get_bias_batchnorm_params(self.model, True):
            p.skip_wd = True

        n_groups = self.create_opt(torch.optim.Adam, None)
        freeze(self, n_groups)

        self.loss_func = LabelSmoothingCrossEntropy()

    def exclude_params_with_attrib(self, splits, skip_list=['skip_wd']):
        includes = []
        excludes = []
        for param_group in splits:
            ins, exs = [], []
            for param in param_group:
                if not param.requires_grad:
                    continue
                elif any(getattr(param, attrib, False) for attrib in skip_list):
                    exs.append(param)
                else:
                    ins.append(param)
            includes.append(ins)
            excludes.append(exs)
        return includes + excludes

    def get_params(self, split_bn=True):
        if split_bn:
            splits = self.split(self.model)
            return self.exclude_params_with_attrib(splits)
        else:
            return self.split(self.model)

    def forward(self, x):
        return self.model(x)

    def shared_step(self, batch, batch_id):
        x, y = batch['img'], batch['label']
        y_hat = self(x)
        return self.loss_func(y_hat, y), (y_hat, y)

    def training_step(self, batch, batch_idx):
        loss, _ = self.shared_step(batch, batch_idx)
        result = pl.TrainResult(minimize=loss)
        result.log('train_loss', loss)
        return result

    def validation_step(self, batch, batch_idx):
        loss, (y_hat, y) = self.shared_step(batch, batch_idx)
        acc = FM.accuracy(y_hat, y, num_classes=7)
        result = pl.EvalResult(checkpoint_on=loss)
        result.log('val_loss', loss, prog_bar=True)
        result.log('val_acc', acc, prog_bar=True)
        return result

    def create_opt(self, opt_func, sched_func, lr=None, wd=None, skip_bn_wd=True):
        if lr is None:
            lr = self.hparams.lr
        if wd is None:
            wd = self.hparams.wd


        param_groups = self.get_params(skip_bn_wd)
        n_groups = real_n_groups = len(param_groups)
        if skip_bn_wd:
            # There are duplicates since we split the batchnorms out of it.
            n_groups //= 2

        def _inner():
            print('override_called')

            lrs = generate_val_steps(lr, n_groups)
            if skip_bn_wd:
                lrs += lrs
            assert len(lrs) == real_n_groups, f"Trying to set {len(lrs)} values for LR but there are {n_groups} parameter groups."

            grps = []
            for i, (pg, l) in enumerate(zip(param_groups, lrs)):
                grps.append({
                    "params": pg,
                    "lr": l,
                    "weight_decay": wd if i < n_groups else 0.
                })

            print(lrs)

            opt = opt_func(grps, lr=self.hparams.lr if isinstance(lr, slice) else lr)
            if sched_func is not None:
                scheduler = sched_func(opt, max_lr=lrs)
                sched = {
                    'scheduler': scheduler, # The LR schduler
                    'interval': 'step', # The unit of the scheduler's step size
                    'frequency': 1, # The frequency of the scheduler
                    'reduce_on_plateau': False, # For ReduceLROnPlateau scheduler
                }
                return [opt], [sched]
            else:
                return [opt]

        self.configure_optimizers = _inner
        return n_groups

# Cell
def fit_one_cycle(epochs, model, datamodule, opt='Adam', max_lr=None, pct_start=0.25,
                  div_factor=25., final_div_factor=1e5, wd=None,
                  skip_bn_wd=True, max_momentum=0.95, base_momentum=0.85, **kwargs):
    if isinstance(opt, str):
        opt_func = getattr(torch.optim, opt, False)
        if not opt_func:
            raise Exception("Invalid optimizer, please pass correct name as in pytorch.optim.")
    else:
        opt_func = opt
    sched_func = torch.optim.lr_scheduler.OneCycleLR
    steps_epoch = len(datamodule.train_dataloader())
    sched = partial(sched_func, epochs=epochs, steps_per_epoch=steps_epoch, pct_start=pct_start,
                    div_factor=div_factor, final_div_factor=final_div_factor,
                    base_momentum=base_momentum, max_momentum=max_momentum)
    model.create_opt(opt_func, sched, lr=max_lr, wd=wd)
    trainer = pl.Trainer(max_epochs=epochs, **kwargs)
    trainer.fit(model, datamodule)
    return trainer