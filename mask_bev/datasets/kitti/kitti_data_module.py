import pathlib
import random
from typing import Callable

import pytorch_lightning as pl
from torch.utils.data import DataLoader, Subset

import mask_bev.utils.pipeline as pp
from mask_bev.datasets.apply_transform import ApplyTransform
from mask_bev.datasets.collate_type import CollateType
from mask_bev.datasets.kitti.kitti_dataset import KittiDataset
from mask_bev.datasets.kitti.kitti_transforms import FrameMaskListCollate, FrameMaskTensorCollate, FrameToPointCloud, \
    ShufflePointCloud, FrameScanToMask, FrameMasksToLabelInstanceMasks, FrameMetaData, FrameDifficulty, \
    FrameRoundedHeight, \
    FilterLabelDifficulty, ObjectRangeFilter, LabelMaskToMask2FormerLabel


# TODO unify with other DataModules
class KittiDataModule(pl.LightningDataModule):
    def __init__(self, root_path: str, batch_size: int, min_num_points: int, num_queries: int, x_range: (int, int),
                 y_range: (int, int), z_range: (int, int), voxel_size: float, remove_unseen: bool,
                 num_workers: int = 8, pin_memory: bool = True, collate_fn: CollateType = CollateType.ListCollate,
                 shuffle_train: bool = True, frame_transform: Callable = None, mask_transform: Callable = None,
                 filter_difficulty: bool = False, head_num_classes: int = 1, **kwargs):
        """
        Pytorch lightning wrapper around WaymoDataset
        :param root_path: root path of the dataset
        :param batch_size: mini-batch size
        :param min_num_points: minimum number of points to be considered seen
        :param num_workers: number of workers for the data preparation (0 to disable multi-process)
        :param pin_memory: allow the GPU to directly access memory
        :param collate_fn: collate function that collects samples into batchs
        :param frame_transform: transform to apply to `SemanticKittiMaskDataset`
        """
        super().__init__()
        self._root_path = pathlib.Path(root_path).expanduser()
        self._batch_size = batch_size
        self._min_num_points = min_num_points
        self._num_queries = num_queries
        self._x_range = x_range
        self._y_range = y_range
        self._z_range = z_range
        self._voxel_size = voxel_size
        self._remove_unseen = remove_unseen
        self._num_workers = num_workers
        self._pin_memory = pin_memory
        self._shuffle_train = shuffle_train
        self._frame_transform = frame_transform if frame_transform is not None else pp.Identity()
        self._mask_transform = mask_transform if mask_transform is not None else pp.Identity()
        self._filter_difficulty = filter_difficulty
        self._num_classes = head_num_classes

        self._dataset = KittiDataset(root_path, 'training')

        train_split = self._root_path.joinpath('train.txt')
        val_split = self._root_path.joinpath('val.txt')

        with open(train_split, 'r') as f:
            train_idx = [int(line.strip()) for line in f.readlines()]
            random.shuffle(train_idx)
        with open(val_split, 'r') as f:
            val_idx = [int(line.strip()) for line in f.readlines()]

        self._train_dataset = Subset(self._dataset, train_idx)
        self._valid_dataset = Subset(self._dataset, val_idx)

        transform_to_pair = self._build_transform()

        self._train_dataset = ApplyTransform(self._train_dataset, transform_to_pair)
        self._valid_dataset = ApplyTransform(self._valid_dataset, transform_to_pair)

        if collate_fn == CollateType.ListCollate:
            self._collate_fn = FrameMaskListCollate()
        elif collate_fn == CollateType.TensorCollate:
            self._collate_fn = FrameMaskTensorCollate()
        else:
            raise ValueError('Invalid collate_fn')

    @property
    def num_queries(self):
        return self._num_queries

    def _build_transform(self):
        return pp.Compose([
            self._frame_transform,
            ObjectRangeFilter(self._x_range, self._y_range),
            pp.Tupled(3),
            pp.First(pp.Compose([
                FrameToPointCloud(),
                ShufflePointCloud(),
            ])),
            pp.Second(pp.Compose([
                FilterLabelDifficulty() if self._filter_difficulty else pp.Identity(),
                FrameScanToMask(self._x_range, self._y_range, self._z_range, self._voxel_size, self._min_num_points,
                                self._remove_unseen),
                FrameMasksToLabelInstanceMasks(self._num_queries),
                LabelMaskToMask2FormerLabel(self._num_classes),
                self._mask_transform,
            ])),
            pp.Third(pp.Compose([
                FrameMetaData(),
                FrameDifficulty(),
                FrameRoundedHeight(),
            ])),
        ])

    def train_dataloader(self):
        return DataLoader(self._train_dataset, batch_size=self._batch_size, num_workers=self._num_workers,
                          pin_memory=self._pin_memory, shuffle=self._shuffle_train, drop_last=True,
                          collate_fn=self._collate_fn)

    def val_dataloader(self):
        return DataLoader(self._valid_dataset, batch_size=self._batch_size, num_workers=self._num_workers,
                          pin_memory=self._pin_memory, shuffle=False, drop_last=True, collate_fn=self._collate_fn)
