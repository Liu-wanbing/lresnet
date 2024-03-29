# Copyright 2021 Huawei Technologies Co., Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================
"""
python dataset.py
"""
import os
import mindspore.common.dtype as mstype
import mindspore.dataset.engine as de
import mindspore.dataset.vision.c_transforms as C
import mindspore.dataset.transforms.c_transforms as C2
from mindspore.communication.management import init, get_rank, get_group_size
import mxnet as mx
import numpy as np
import numbers


def create_dataset(dataset_path, do_train, repeat_num=1, batch_size=32, target="Ascend"):
    """
        create a train dataset

        Args:
            dataset_path(string): the path of dataset.
            do_train(bool): whether dataset is used for train or eval.
            repeat_num(int): the repeat times of dataset. Default: 1
            batch_size(int): the batch size of dataset. Default: 32
            target(str): the device target. Default: Ascend

        Returns:
            dataset
        """
    if target == "Ascend":
        device_num, rank_id = _get_rank_info()
    else:
        init("nccl")
        rank_id = get_rank()
        device_num = get_group_size()
        device_num, rank_id = _get_rank_info()


    class DatasetGenerator():
        def __init__(self, root_dir):

            self.root_dir = root_dir
            path_imgrec = os.path.join(root_dir, 'train.rec')
            path_imgidx = os.path.join(root_dir, 'train.idx')
            self.imgrec = mx.recordio.MXIndexedRecordIO(path_imgidx, path_imgrec, 'r')
            s = self.imgrec.read_idx(0)
            header, _ = mx.recordio.unpack(s)
            if header.flag > 0:
                self.header0 = (int(header.label[0]), int(header.label[1]))
                self.imgidx = np.array(range(1, int(header.label[0])))
            else:
                self.imgidx = np.array(list(self.imgrec.keys))

        def __getitem__(self, index):
            idx = self.imgidx[index]
            s = self.imgrec.read_idx(idx)
            header, img = mx.recordio.unpack(s)
            label = header.label
            if not isinstance(label, numbers.Number):
                label = label[0]
            label = np.int32(label)
            image = mx.image.imdecode(img).asnumpy()
            return image, label

        def __len__(self):
            return len(self.imgidx)

    dataset_generator = DatasetGenerator(dataset_path)

    # if do_train:
    #     if run_distribute:
    #         from mindspore.communication.management import get_rank, get_group_size
    #         data_set = ds.GeneratorDataset(dataset_generator, ["image", "label"],  num_parallel_workers=8, shuffle=True, \
    #             num_shards=get_group_size(), shard_id=get_rank())
    #     else:
    #         data_set = ds.GeneratorDataset(dataset_generator, ["image", "label"],  num_parallel_workers=8, shuffle=True)
    # else:
    #     data_set = ds.GeneratorDataset(dataset_generator, ["image", "label"],  num_parallel_workers=8, shuffle=True)
    

    if device_num == 1:
        ds = de.GeneratorDataset(dataset_generator, ["image", "label"],  num_parallel_workers=8, shuffle=True)
    else:
        ds = de.GeneratorDataset(dataset_generator, ["image", "label"],  num_parallel_workers=8, shuffle=True,
                                num_shards=device_num, shard_id=rank_id)


    # if device_num == 1:
    #     ds = de.ImageFolderDataset(
    #         dataset_path, num_parallel_workers=8, shuffle=True)
    # else:
    #     ds = de.ImageFolderDataset(dataset_path, num_parallel_workers=8, shuffle=True,
    #                                num_shards=device_num, shard_id=rank_id)

    image_size = 112
    mean = [0.5 * 255, 0.5 * 255, 0.5 * 255]
    std = [0.5 * 255, 0.5 * 255, 0.5 * 255]

    # define map operations
    if do_train:
        trans = [
            # C.RandomCropDecodeResize(image_size, scale=(0.08, 1.0), ratio=(0.75, 1.333)),
            # C.Decode(),
            C.RandomHorizontalFlip(prob=0.5),
            C.Normalize(mean=mean, std=std),
            C.HWC2CHW()
        ]
    else:
        trans = [
            # C.Decode(),
            C.Resize(256),
            C.CenterCrop(image_size),
            C.Normalize(mean=mean, std=std),
            C.HWC2CHW()
        ]

    type_cast_op = C2.TypeCast(mstype.int32)

    ds = ds.map(input_columns="image",
                num_parallel_workers=8, operations=trans)
    ds = ds.map(input_columns="label", num_parallel_workers=8,
                operations=type_cast_op)

    # apply batch operations
    ds = ds.batch(batch_size, drop_remainder=True)

    # apply dataset repeat operation
    ds = ds.repeat(repeat_num)

    return ds


def _get_rank_info():
    """
    get rank size and rank id
    """
    rank_size = int(os.environ.get("RANK_SIZE", 1))

    if rank_size > 1:
        rank_size = int(os.environ.get("RANK_SIZE"))
        rank_id = int(os.environ.get("RANK_ID"))
    else:
        rank_size = 1
        rank_id = 0

    return rank_size, rank_id
