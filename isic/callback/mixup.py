# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/cb_mixup.ipynb (unless otherwise specified).

__all__ = ['MixupDict']

# Cell
from typing import Optional
from functools import partial

import torch
from torch import tensor
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions.beta import Beta
import torchvision

import pytorch_lightning as pl
from pytorch_lightning.core import LightningModule
from pytorch_lightning.metrics import functional as FM
from pytorch_lightning.callbacks.base import Callback
from pytorch_lightning.utilities import rank_zero_info, rank_zero_warn
from pytorch_lightning.utilities.exceptions import MisconfigurationException

from ..utils.core import unsqueeze, reduce_loss, NoneReduce
from ..layers import MixLoss

# Cell
class MixupDict(Callback):
    def __init__(self, alpha=0.4):
        super().__init__()
        self.distrib = Beta(tensor(alpha), tensor(alpha))

    def on_train_start(self, trainer, pl_module):
        assert hasattr(pl_module, 'loss_func'), 'Your LightningModule should have loss_func attribute as your loss function.'
        self.old_lf = pl_module.loss_func
        self.loss_fnc = MixLoss(self.old_lf, self)
        pl_module.loss_func = self.loss_fnc
        self.pl_module = pl_module

    def _mixup(self, batch, logger, log_image=False, pre_fix='train'):
        xb, yb = batch["img"], batch["label"]
        bs = yb.size(0)

        # Produce "bs" probability for each sample
        lam = self.distrib.sample((bs,)).squeeze()

        # Get those probability that >0.5, so that the first img (in the nonshuffle batch) has bigger coeff
        # Which avoid duplication mixup
        lam = torch.stack([lam, 1-lam], 1)
        self.lam = lam.max(1)[0]

        # Permute the batch
        shuffle = torch.randperm(bs)
        xb_1, self.yb_1 = xb[shuffle], yb[shuffle]
        nx_dims = len(xb.size())
        weight = unsqueeze(self.lam, n=nx_dims-1)
        x_new = torch.lerp(xb_1, xb, weight=weight)
        if log_image:
            grid = torchvision.utils.make_grid(x_new)
            logger.experiment.add_image(pre_fix + 'mixup', grid)
            grid_g = torchvision.utils.make_grid(xb)
            logger.experiment.add_image(pre_fix + 'norm', grid_g)
            dif = abs(xb - x_new)
            grid_d = torchvision.utils.make_grid(dif)
            logger.experiment.add_image(pre_fix + 'dif', grid_d)
        return x_new

    def on_train_batch_start(self, trainer, pl_module, batch, batch_idx, dataloader_idx):
        x = self._mixup(batch, trainer.logger)
        batch["img"] = x

#     def on_validation_batch_start(self, trainer, pl_module, batch, batch_idx, dataloader_idx):
#         x = self._mixup(batch, trainer.logger)
#         batch["img"] = x

    def on_validation_start(self, trainer, pl_module):
        pl_module.loss_func = self.old_lf

    def on_validation_end(self, trainer, pl_module):
        pl_module.loss_func = self.loss_fnc

    def on_fit_end(self, trainer, pl_module):
        pl_module.loss_func = self.old_lf