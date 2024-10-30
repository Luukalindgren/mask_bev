import os
from pathlib import Path

# Paths to your dataset folders
velodyne_path = Path('data/KITTI/data_object_velodyne/training/velodyne')
label_path = Path('data/KITTI/data_object_label_2/training/label_2')

# Get all .bin and .txt files and sort them to keep order consistent
velodyne_files = sorted(velodyne_path.glob('*.bin'))
label_files = sorted(label_path.glob('*.txt'))

# Rename velodyne and label files to 6-digit zero-padded filenames
for i, (velodyne_file, label_file) in enumerate(zip(velodyne_files, label_files)):
    new_name = f"{i:06d}"  # Zero-padded 6-digit number
    
    # Rename velodyne file
    velodyne_file.rename(velodyne_path / f"{new_name}.bin")
    
    # Rename corresponding label file
    label_file.rename(label_path / f"{new_name}.txt")

print("Files have been renamed successfully!")
