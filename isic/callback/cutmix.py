# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/cb_cutmix.ipynb (unless otherwise specified).

__all__ = ['CutmixDict']

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

from ..utils import unsqueeze, reduce_loss, NoneReduce
from ..layers import MixLoss

# Cell
class CutmixDict(Callback):
    def __init__(self, alpha=1.):
        super().__init__()
        self.distrib = Beta(tensor(alpha), tensor(alpha))

    def on_train_start(self, trainer, pl_module):
        assert hasattr(pl_module, 'loss_func'), 'Your LightningModule should have loss_func attribute as your loss function.'
        self.old_lf = pl_module.loss_func
        self.loss_fnc = MixLoss(self.old_lf, self)
        pl_module.loss_func = self.loss_fnc
        self.pl_module = pl_module

    def _cutmix(self, batch, logger, log_image=False, pre_fix='train'):
        xb, yb = batch["img"], batch["label"]
        bs = yb.size(0)
        W, H = xb.size(3), xb.size(2)

        lam = self.distrib.sample((1,)).squeeze()
        lam = torch.stack([lam, 1-lam])
        self.lam = lam.max()

        # Permute the batch
        shuffle = torch.randperm(bs)
        xb_1, self.yb_1 = xb[shuffle], yb[shuffle]

        x1, y1, x2, y2 = self.rand_bbox(W, H, self.lam)
        xb[:, :, x1:x2, y1:y2] = xb_1[:, :, x1:x2, y1:y2]
        self.lam = (1 - ((x2-x1) * (y2-y1)) / float(W*H))

        if log_image:
            grid = torchvision.utils.make_grid(xb)
            logger.experiment.add_image(pre_fix + '_cutmix', grid)
            grid_g = torchvision.utils.make_grid(xb_1)
            logger.experiment.add_image(pre_fix + '_cut_from', grid_g)
            dif = abs(xb - xb_1)
            grid_d = torchvision.utils.make_grid(dif)
            logger.experiment.add_image(pre_fix + '_dif', grid_d)
        return xb

    def on_train_batch_start(self, trainer, pl_module, batch, batch_idx, dataloader_idx):
        x = self._cutmix(batch, trainer.logger)
        batch["img"] = x

#     def on_validation_batch_start(self, trainer, pl_module, batch, batch_idx, dataloader_idx):
#         x = self._cutmix(batch, trainer.logger, True, 'val')
#         batch["img"] = x

    def on_validation_start(self, trainer, pl_module):
        pl_module.loss_func = self.old_lf

    def on_validation_end(self, trainer, pl_module):
        pl_module.loss_func = self.loss_fnc

    def on_fit_end(self, trainer, pl_module):
        pl_module.loss_func = self.old_lf

    def rand_bbox(self, W, H, lam):
        cut_rat = torch.sqrt(1. - lam)
        cut_w = (W * cut_rat).type(torch.long)
        cut_h = (H * cut_rat).type(torch.long)
        # uniform
        cx = torch.randint(0, W, (1,))
        cy = torch.randint(0, H, (1,))
        x1 = torch.clamp(cx - cut_w // 2, 0, W)
        y1 = torch.clamp(cy - cut_h // 2, 0, H)
        x2 = torch.clamp(cx + cut_w // 2, 0, W)
        y2 = torch.clamp(cy + cut_h // 2, 0, H)
        return x1, y1, x2, y2