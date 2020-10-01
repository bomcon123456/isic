# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/dataset.ipynb (unless otherwise specified).

__all__ = ['SkinLabels', 'preprocess_df', 'SkinDataset', 'SkinDataModule']

# Cell
import copy

import torch
from torch.utils.data import DataLoader, Dataset
import torchvision.transforms as transforms
import pandas as pd
from sklearn.model_selection import train_test_split
import pytorch_lightning as pl

from tqdm import tqdm

import cv2
import numpy as np
from PIL import Image
import matplotlib.pyplot as plt

from .config import *
from .utils.dataset import undersampling_df, oversampling_df, oversampling_not_flat_df


# Cell
class SkinLabels():
    lesion_type_dict = {
        'nv': 'Melanocytic nevi',
        'mel': 'Melanoma',
        'bkl': 'Benign keratosis-like lesions ',
        'bcc': 'Basal cell carcinoma',
        'akiec': 'Actinic keratoses',
        'vasc': 'Vascular lesions',
        'df': 'Dermatofibroma'
    }

    lesion_type_vi_dict = {
        'nv': 'Nốt ruồi',
        'mel': 'Ung thư hắc tố',
        'bkl': 'U sừng hóa ác tính ',
        'bcc': 'U da ung thư tế bào đáy',
        'akiec': 'Dày sừng quang hóa',
        'vasc': 'Thương tổn mạch máu',
        'df': 'U da lành tính'
    }

# Cell
def preprocess_df(df, valid_size=0.2, seed=AppConfig.SEED, image_label_only=False):

    df['path'] = PathConfig.IMAGE_PATH + '/' + df['image_id'] + '.jpg'
    df['label_fullstr'] = df['dx'].map(SkinLabels.lesion_type_dict.get)

    label_str = pd.Categorical(df['label_fullstr'])
    df['label_index'] = label_str.codes

    df_undup = df.groupby('lesion_id').count()
    df_undup = df_undup[df_undup['image_id'] == 1]
    df_undup.reset_index(inplace=True)

    _, valid = train_test_split(df_undup['lesion_id'], test_size=valid_size,
                                random_state=seed,
                                stratify=df_undup['label_index'])
    valid = set(valid)
    df['val'] = df['lesion_id'].apply(lambda x: 1 if str(x) in valid else 0)

    df_train = df[df['val'] == 0]
    df_valid = df[df['val'] == 1]

    dest_df_train = df_train.reset_index(drop=True)
    dest_df_valid = df_valid.reset_index(drop=True)
    if not image_label_only:
        return dest_df_train, dest_df_valid, list(label_str.categories)
    else:
        train_imgs = []
        val_imgs = []
        i = 0
        for df in (dest_df_train, dest_df_valid):
            for j, path in enumerate(df['path']):
                x = np.array(Image.open(path))
                y = torch.tensor(int(df['label_index'][j]))
                if i == 0:
                    train_imgs.append((x, y))
                else:
                    val_imgs.append((x, y))
            i += 1
        return train_imgs, val_imgs, list(label_str.categories)

# Cell
class SkinDataset(Dataset):
    def __init__(self, df, transform=None, labels=None):
        self.df = df
        self.transform = transform
        self.labels = labels

    def __getitem__(self, i):
        if i >= len(self): raise IndexError
        x = Image.open(self.df['path'][i])
        y = torch.tensor(int(self.df['label_index'][i]))

        if self.transform:
            x = self.transform(x)

        return {"img": x, "label": y}

    def __len__(self):
        return len(self.df)

    def show_image(self, index=None):
        dataset = self
        n_samples = len(dataset)

        if not index:
            index = int(np.random.random()*n_samples)
        else:
            if index >= n_samples or index < 0:
                print('Invalid index.')
                return

        d = dataset[index]

        plt.imshow(d['img'].permute(1,2,0))
        plt.axis('off')
        plt.title(self.labels[d['label']] if self.labels else d['label'])

    def show_grid(self, n_rows=5, n_cols=5):
        dataset = self
        array = torch.utils.data.Subset(dataset, np.random.choice(len(dataset), n_rows*n_cols, replace=False))

        plt.figure(figsize=(12, 12))
        for row in range(n_rows):
            for col in range(n_cols):
                index = n_cols * row + col
                plt.subplot(n_rows, n_cols, index + 1)
                plt.imshow(array[index]['img'].permute(1, 2, 0))
                plt.axis('off')
                label = self.labels[int(array[index]['label'])] if self.labels else int(array[index]['label'])
                plt.title(label, fontsize=12)
        plt.tight_layout()

# Cell
class SkinDataModule(pl.LightningDataModule):
    def __init__(self, df_path=PathConfig.CSV_PATH, valid_size=0.2, bs=64, train_df=None, valid_df=None):
        self.df_path = df_path
        self.valid_size = valid_size
        self.bs = bs
        self.train_df, self.valid_df = train_df, valid_df
        self.t_transform = transforms.Compose([
            transforms.Resize(350),
            transforms.RandomResizedCrop((224, 224)),
            transforms.ToTensor(),
#                 transforms.Normalize(mean=[0.7579628, 0.5485365, 0.5737883],
#                                      std=[0.1419983, 0.15297663, 0.17065412])
        ])
        self.v_transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
#                 transforms.Normalize(mean=[0.7579628, 0.5485365, 0.5737883],
#                                      std=[0.1419983, 0.15297663, 0.17065412])
        ])

        self.dims = (3, 224, 224)

    def setup(self, stage):
        if self.train_df is not None or stage=='test':
            df = pd.read_csv(PathConfig.CSV_PATH)
            self.train_df, self.valid_df, self.labels = preprocess_df(df, self.valid_size)
        else:
            # If we pass train_df from the beginning, means that we use the augmented folder
            self.train_df["path"] = PathConfig.AUG_PATH + '/' + self.train_df['image_id'] + '.jpg'
            self.valid_df["path"] = PathConfig.AUG_PATH + '/' + self.valid_df['image_id'] + '.jpg'
        self.train_ds = SkinDataset(self.train_df, self.t_transform, self.labels)
        self.val_ds = SkinDataset(self.valid_df, self.v_transform, self.labels)

        self.dims = tuple(self.train_ds[0]["img"].shape)

    def train_dataloader(self):
        return DataLoader(self.train_ds, batch_size=self.bs, shuffle=True, num_workers=4, pin_memory=True)

    def val_dataloader(self):
        return DataLoader(self.val_ds, batch_size=self.bs, num_workers=4, pin_memory=True)

    def test_dataloader(self):
        #TODO
        return DataLoader(self.val_ds, batch_size=self.bs, num_workers=4, pin_memory=True)