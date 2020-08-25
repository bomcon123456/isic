# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/model.ipynb (unless otherwise specified).

__all__ = ['Model']

# Cell
import warnings
import re

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
    def __init__(self, steps_epoch, epochs=30, lr=1e-2, wd=0., n_out=7, concat_pool=True, arch='resnet50'):
        super().__init__()
        self.save_hyperparameters()
        # create body
        body, self.split, num_ftrs = create_body(arch)

        # create head
        head = create_head(num_ftrs, n_out)

        #model
        self.model = nn.Sequential(body, head)
        apply_init(self.model[1])

        # Setup so that batchnorm will not be freeze
        for p in get_bias_batchnorm_params(self.model, False):
            p.force_train = True
        for p in get_bias_batchnorm_params(self.model, True):
            p.skip_wd = True

        n_groups = self.create_opt(lr, skip_bn_wd=True)
        freeze(self, n_groups)

        self.loss_func = LabelSmoothingCrossEntropy()

    def get_params(self, split_bn=True):
        if split_bn:
            non_bns = []
            bns = []
            splits = self.split(self.model)
            for param_group in splits:
                non_bn, bn = [], []
                for param in param_group:
                    if not param.requires_grad:
                        continue
                    elif getattr(param, 'skip_wd', False):
                        bn.append(param)
                    else:
                        non_bn.append(param)
                non_bns.append(non_bn)
                bns.append(bn)
            return non_bns + bns
        else:
            return self.split(self.model)

    def forward(self, x):
        return self.model(x)

    def training_step(self, batch, batch_idx):
        x, y = batch['img'], batch['label']
        y_hat = self(x)
        loss = self.loss_func(y_hat, y)
        acc = FM.accuracy(y_hat, y, num_classes=7)
        result = pl.TrainResult(minimize=loss)
        result.log('train_loss', loss)
        result.log('train_acc', acc, prog_bar=True)
        return result

    def validation_step(self, batch, batch_idx):
        x, y = batch['img'], batch['label']
        y_hat = self(x)
        loss = self.loss_func(y_hat, y)
        acc = FM.accuracy(y_hat, y, num_classes=7)
        result = pl.EvalResult(checkpoint_on=loss)
        result.log('val_loss', loss, prog_bar=True)
        result.log('val_acc', acc, prog_bar=True)
        return result

    def create_opt(self, lr=None, skip_bn_wd=True):
        if lr is None:
            lr = self.hparams.lr
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
                    "weight_decay": self.hparams.wd if i < n_groups else 0.
                })
            print(lrs)
            opt = torch.optim.Adam(grps,
                        lr=lr, weight_decay=self.hparams.wd
            )
            scheduler = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lrs, steps_per_epoch=self.hparams.steps_epoch, epochs=self.hparams.epochs)
            sched = {
                'scheduler': scheduler, # The LR schduler
                'interval': 'step', # The unit of the scheduler's step size
                'frequency': 1, # The frequency of the scheduler
                'reduce_on_plateau': False, # For ReduceLROnPlateau scheduler
            }
            return [opt], [sched]
        self.configure_optimizers = _inner
        return n_groups