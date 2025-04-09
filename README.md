## Luuka's Modifications

- Changed all the KITTI types to match our custom dataset's labes (Person, Table, Chair, Couch, Shelf, Robot, TrashCan, Misc, DontCare)
- Modified some threshold values to match these new, smaller objects
- Modified hardcoded paths to all be inside the project folders
- Two new helper scripts: `scripts/generate_train_val_sets.py` and `scripts/rename_frames_seq.py`
    - First generates train.txt and val.txt files
    - Second renames the label and point cloud files to `000001.extension` format, but this is already applied to the dataset
- New config file `configs/training/kitti/03_kitti_custom.yml`, made to be compatible with TIERS pc.

## Luuka's Instructions

1. Move the custom dataset `Custom_KITTI_Dataset_Final` to the project `data/` folder and rename it to `KITTI`
     - If you have the original KITTI dataset, give it temporary name, and switch these namings when you want to switch datasets
     - The 'active' dataset is the one named `data/KITTI`
2. Make sure you are on the project root when running commands.
3. Generate train.txt and val.txt with: `python scripts/generate_train_val_sets.py`
4. Follow the original authors instructions

*(Keep renaming the `images/` dir to keep the last tests images, since the testing code writes the images to that directory and rewrites if there is something.)*

## Back to the original authors README:

---

# MaskBEV: Joint Object Detection and Footprint Completion for Bird's-eye View 3D Point Clouds

This is a work in progress migration from mmlabs libraries 1.x to 2.0.

## Abstract

Recent works in object detection in LiDAR point clouds mostly focus on predicting bounding boxes around objects. This
prediction is commonly achieved using anchor-based or anchor-free detectors that predict bounding boxes, requiring
significant explicit prior knowledge about the objects to work properly. To remedy these limitations, we propose
MaskBEV, a bird's-eye view (BEV) mask-based object detector neural architecture. MaskBEV predicts a set of BEV instance
masks that represent the footprints of detected objects. Moreover, our approach allows object detection and footprint
completion in a single pass. MaskBEV also reformulates the detection problem purely in terms of classification, doing
away with regression usually done to predict bounding boxes. We evaluate the performance of MaskBEV on both
SemanticKITTI and KITTI datasets while analyzing the architecture advantages and limitations.

## Documentation

Follow [dataset installation instructions](docs/DATASETS.md) to download and prepare the datasets.

Follow [installation instructions](docs/INSTALLATION.md) to install the dependencies.

Follow [training instructions](docs/TRAINING.md) to start training and evaluating MaskBEV.

Follow [configuration instructions](docs/CONFIGURATION.md) to understand the configuration options.

Follow [testing instructions](docs/TESTING.md) to test the trained models.
