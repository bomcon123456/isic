# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/utils_dataset.ipynb (unless otherwise specified).

__all__ = ['SkinLabels', 'from_label_idx_to_key', 'preprocess_df', 'get_default_train_transform',
           'get_advanced_train_transform', 'get_default_val_transform', 'split_df_to_cat_num_df', 'undersampling_df',
           'oversampling_df', 'oversampling_not_flat_df', 'AdvancedHairAugmentation', 'DrawHair', 'Microscope']

# Cell
import copy
import os
import random

import torch
from torch.utils.data import DataLoader, Dataset, RandomSampler
import torchvision.transforms as transforms

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
import matplotlib.pyplot as plt


import pytorch_lightning as pl
from tqdm import tqdm

import cv2
from PIL import Image
import albumentations as A

from ..config import *
from ..sampler import ImbalancedDatasetSampler

# Cell
class SkinLabels:
    lesion_type_dict = {
        'nv': 'Melanocytic nevi',
        'mel': 'Melanoma',
        'bkl': 'Benign keratosis-like lesions',
        'bcc': 'Basal cell carcinoma',
        'akiec': 'Actinic keratoses',
        'vasc': 'Vascular lesions',
        'df': 'Dermatofibroma'
    }

    lesion_type_dict_inversed = {
      'Melanocytic nevi': 'nv',
      'Melanoma': 'mel',
      'Benign keratosis-like lesions': 'bkl',
      'Basal cell carcinoma': 'bcc',
      'Actinic keratoses': 'akiec',
      'Vascular lesions': 'vasc',
      'Dermatofibroma': 'df'
    }

    lesion_type_vi_dict = {
        'nv': 'Nốt ruồi',
        'mel': 'Ung thư hắc tố',
        'bkl': 'Dày sừng lành tính',
        'bcc': 'Ung thư biểu mô tế bào đáy',
        'akiec': 'Dày sừng quang hóa',
        'vasc': 'Thương tổn mạch máu',
        'df': 'U xơ da'
    }

# Cell
def from_label_idx_to_key(label_idx, labels):
    label_string = labels[label_idx]
    key = SkinLabels.lesion_type_dict_inversed[label_string]
    return key

# Cell
def preprocess_df(df, valid_size=0.2, seed=AppConfig.SEED, image_label_only=False, img_path = PathConfig.IMAGE_PATH):

    df['age'].fillna((df['age'].mean()), inplace=True)

    df['path'] = img_path + '/' + df['image_id'] + '.jpg'
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
def get_default_train_transform(image_size=224, no_norm=False):
    transforms_train = [
        A.Transpose(p=0.5),
        A.VerticalFlip(p=0.5),
        A.HorizontalFlip(p=0.5),
        A.Resize(400, 400),
        A.RandomResizedCrop(image_size, image_size)
    ]
    norm = A.Normalize()
    if no_norm:
        norm = A.Normalize(mean=0, std=1)
    transforms_train.append(norm)
    return A.Compose(transforms_train)

def get_advanced_train_transform(image_size=224, cut_out=True, no_norm=False):
    transforms_train = [
        A.Transpose(p=0.5),
        A.VerticalFlip(p=0.5),
        A.HorizontalFlip(p=0.5),
        A.RandomBrightness(limit=0.2, p=0.75),
        A.RandomContrast(limit=0.2, p=0.75),
        A.OneOf([
            A.MotionBlur(blur_limit=5),
            A.MedianBlur(blur_limit=5),
            A.GaussianBlur(blur_limit=5),
            A.GaussNoise(var_limit=(5.0, 30.0)),
        ], p=0.7),

        A.OneOf([
            A.OpticalDistortion(distort_limit=1.0),
            A.GridDistortion(num_steps=5, distort_limit=1.),
            A.ElasticTransform(alpha=3),
        ], p=0.7),

        A.CLAHE(clip_limit=4.0, p=0.7),
        A.HueSaturationValue(hue_shift_limit=10, sat_shift_limit=20, val_shift_limit=10, p=0.5),
        A.ShiftScaleRotate(shift_limit=0.1, scale_limit=0.1, rotate_limit=15, border_mode=0, p=0.85),
        A.Resize(image_size, image_size)
    ]
    if cut_out:
        transforms_train.append(A.Cutout(max_h_size=int(image_size * 0.375), max_w_size=int(image_size * 0.375), num_holes=1, p=0.7))
    norm = A.Normalize()
    if no_norm:
        norm = A.Normalize(mean=0, std=1)
    transforms_train.append(norm)
    return A.Compose(transforms_train)

def get_default_val_transform(image_size=224):
    return A.Compose([
        A.Resize(image_size, image_size),
        A.Normalize()
    ])

# Cell
def split_df_to_cat_num_df(df):
    text_fields = ['image_id', 'lesion_id', 'dx', 'dx_type', 'localization', 'path', 'label_fullstr', 'sex']
    text_df = df.loc[:, df.columns.isin(text_fields)].copy()
    numerical_df = df.drop(columns = text_fields)

    image_id_cat = pd.Categorical(df['image_id'])
    text_df['img_id'] = image_id_cat.codes
    numerical_df['img_id']=image_id_cat.codes
    y = numerical_df['label_index']
    numerical_df = numerical_df.drop(columns=['label_index'])

    return text_df, numerical_df, y

# Cell
def undersampling_df(df):
    from imblearn.under_sampling import RandomUnderSampler
    rus = RandomUnderSampler(random_state=0)
    X_resampled, y_resampled = rus.fit_resample(df.drop(columns=['label_index']), df['label_index'])
    X_resampled['label_index'] = y_resampled
    return X_resampled

# Cell
def oversampling_df(df):
    from imblearn.over_sampling import RandomOverSampler
    ros = RandomOverSampler(random_state=0)
    X_resampled, y_resampled = ros.fit_resample(df.drop(columns=['label_index']), df['label_index'])
    X_resampled['label_index'] = y_resampled
    return X_resampled

# Cell
def oversampling_not_flat_df(df, data_aug_rate=None):
    if not data_aug_rate:
        data_aug_rate = [15,10,5,50,0,5,40]
    for i in range(7):
        if data_aug_rate[i]:
            df=df.append([df.loc[df['label_index'] == i,:]]*(data_aug_rate[i]-1), ignore_index=True)
    return df

# Cell
class AdvancedHairAugmentation:
    """
    Impose an image of a hair to the target image

    Args:
        hairs (int): maximum number of hairs to impose
        hairs_folder (str): path to the folder with hairs images
    """

    def __init__(self, hairs: int = 5, hairs_folder: str = ""):
        self.hairs = hairs
        self.hairs_folder = hairs_folder

    def __call__(self, img):
        """
        Args:
            img (PIL Image): Image to draw hairs on.

        Returns:
            PIL Image: Image with drawn hairs.
        """
        n_hairs = random.randint(0, self.hairs)

        if not n_hairs:
            return img

        height, width, _ = img.shape  # target image width and height
        hair_images = [im for im in os.listdir(self.hairs_folder) if 'png' in im]

        for _ in range(n_hairs):
            hair = cv2.imread(os.path.join(self.hairs_folder, random.choice(hair_images)))
            hair = cv2.flip(hair, random.choice([-1, 0, 1]))
            hair = cv2.rotate(hair, random.choice([0, 1, 2]))


            h_height, h_width, _ = hair.shape  # hair image width and height
            if img.shape[0] < hair.shape[0] or img.shape[1] < hair.shape[1]:
                hair = cv2.resize(hair, (int(width*0.8), int(height*0.8)))
            h_height, h_width, _ = hair.shape  # hair image width and height

            roi_ho = random.randint(0, img.shape[0] - hair.shape[0])
            roi_wo = random.randint(0, img.shape[1] - hair.shape[1])
            roi = img[roi_ho:roi_ho + h_height, roi_wo:roi_wo + h_width]

            # Creating a mask and inverse mask
            img2gray = cv2.cvtColor(hair, cv2.COLOR_BGR2GRAY)
            ret, mask = cv2.threshold(img2gray, 10, 255, cv2.THRESH_BINARY)
            mask_inv = cv2.bitwise_not(mask)

            # Now black-out the area of hair in ROI
            img_bg = cv2.bitwise_and(roi, roi, mask=mask_inv)

            # Take only region of hair from hair image.
            hair_fg = cv2.bitwise_and(hair, hair, mask=mask)

            # Put hair in ROI and modify the target image
            dst = cv2.add(img_bg, hair_fg)

            img[roi_ho:roi_ho + h_height, roi_wo:roi_wo + h_width] = dst

        return img

    def __repr__(self):
        return f'{self.__class__.__name__}(hairs={self.hairs}, hairs_folder="{self.hairs_folder}")'

# Cell
class DrawHair:
    """
    Draw a random number of pseudo hairs

    Args:
        hairs (int): maximum number of hairs to draw
        width (tuple): possible width of the hair in pixels
    """

    def __init__(self, hairs:int = 4, width:tuple = (1, 2)):
        self.hairs = hairs
        self.width = width

    def __call__(self, img):
        """
        Args:
            img (PIL Image): Image to draw hairs on.

        Returns:
            PIL Image: Image with drawn hairs.
        """
        if not self.hairs:
            return img

        width, height, _ = img.shape

        for _ in range(random.randint(0, self.hairs)):
            # The origin point of the line will always be at the top half of the image
            origin = (random.randint(0, width), random.randint(0, height // 2))
            # The end of the line
            end = (random.randint(0, width), random.randint(0, height))
            color = (0, 0, 0)  # color of the hair. Black.
            cv2.line(img, origin, end, color, random.randint(self.width[0], self.width[1]))

        return img

    def __repr__(self):
        return f'{self.__class__.__name__}(hairs={self.hairs}, width={self.width})'

# Cell
class Microscope:
    """
    Cutting out the edges around the center circle of the image
    Imitating a picture, taken through the microscope

    Args:
        p (float): probability of applying an augmentation
    """

    def __init__(self, p: float = 0.5):
        self.p = p

    def __call__(self, img):
        """
        Args:
            img (PIL Image): Image to apply transformation to.

        Returns:
            PIL Image: Image with transformation.
        """
        if random.random() < self.p:
            circle = cv2.circle((np.ones(img.shape) * 255).astype(np.uint8), # image placeholder
                        (img.shape[1]//2, img.shape[0]//2), # center point of circle
                        random.randint(img.shape[1]//2 - 3, img.shape[1]//2 + 15), # radius
                        (0, 0, 0), # color
                        -1)

            mask = circle - 255
            img = np.multiply(img, mask)

        return img

    def __repr__(self):
        return f'{self.__class__.__name__}(p={self.p})'