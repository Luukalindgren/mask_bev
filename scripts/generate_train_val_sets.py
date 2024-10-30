import os
import random
from pathlib import Path

# Set paths
dataset_path = Path('data/KITTI')
velodyne_path = dataset_path.joinpath('data_object_velodyne/training/velodyne')

# Get all .bin files (or any other data format you're using) and extract the base names
all_files = [f.stem for f in velodyne_path.glob('*.bin')]

# Shuffle the files to ensure a random split
random.shuffle(all_files)

# Define split ratio (e.g., 80% training, 20% validation)
train_ratio = 0.8
train_size = int(len(all_files) * train_ratio)

# Split the files
train_files = all_files[:train_size]
val_files = all_files[train_size:]

# Sort the files
train_files.sort()
val_files.sort()

# Write train.txt
with open(dataset_path / 'train.txt', 'w') as f:
    for item in train_files:
        f.write(f"{item}\n")

# Write val.txt
with open(dataset_path / 'val.txt', 'w') as f:
    for item in val_files:
        f.write(f"{item}\n")

print("train.txt and val.txt have been created successfully!")
