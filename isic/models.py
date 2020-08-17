# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/model.ipynb (unless otherwise specified).

__all__ = ['ResnetModel']

# Cell
import warnings

import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models

import pytorch_lightning as pl
from pytorch_lightning.core import LightningModule
from pytorch_lightning.metrics import functional as FM

# Cell
from .dataset import SkinDataModule
from .callback.hyperlogger import HyperparamsLogger
from .callback.logtable import LogTableMetricsCallback

# Cell
class ResnetModel(LightningModule):
    def __init__(self):
        super().__init__()
#         self.save_hyperparameters()
        self.resnet = models.resnet50(pretrained=True)
        num_ftrs = self.resnet.fc.in_features
        self.resnet.fc = nn.Linear(num_ftrs, 7)

    def forward(self, x):
        return self.resnet(x)

    def training_step(self, batch, batch_idx):
        x, y = batch
        y_hat = self(x)
        loss = F.cross_entropy(y_hat, y)
        acc = FM.accuracy(y_hat, y, num_classes=7)
        result = pl.TrainResult(minimize=loss)
        result.log('train_loss', loss)
        result.log('train_acc', acc, prog_bar=True)
        return result

    def validation_step(self, batch, batch_idx):
        x, y = batch
        y_hat = self(x)
        loss = F.cross_entropy(y_hat, y)
        acc = FM.accuracy(y_hat, y, num_classes=7)
        result = pl.EvalResult(checkpoint_on=loss)
        result.log('val_loss', loss, prog_bar=True)
        result.log('val_acc', acc, prog_bar=True)
        return result

    def configure_optimizers(self):
        opt = torch.optim.Adam(self.parameters(), lr=1e-2)
        scheduler = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=1e-2, steps_per_epoch=140, epochs=10)
        sched = {
            'scheduler': scheduler, # The LR schduler
            'interval': 'step', # The unit of the scheduler's step size
            'frequency': 1, # The frequency of the scheduler
            'reduce_on_plateau': False, # For ReduceLROnPlateau scheduler
        }
        return [opt], [sched]