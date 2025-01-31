"""Utilities for real-time data augmentation on image data.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import warnings
import numpy as np
import pandas as pd
import cv2
from .iterator import BatchFromFilesMixin, Iterator
from .utils import validate_filename


class DataFrameIterator(BatchFromFilesMixin, Iterator):
    """Iterator capable of reading images from a directory on disk
        through a dataframe.

    # Arguments
        dataframe: Pandas dataframe containing the filepaths relative to
            `directory` (or absolute paths if `directory` is None) of the
            images in a string column. It should include other column/s
            depending on the `class_mode`:
            - if `class_mode` is `"categorical"` (default value) it must
                include the `y_col` column with the class/es of each image.
                Values in column can be string/list/tuple if a single class
                or list/tuple if multiple classes.
            - if `class_mode` is `"binary"` or `"sparse"` it must include
                the given `y_col` column with class values as strings.
            - if `class_mode` is `"raw"` or `"multi_output"` it should contain
                the columns specified in `y_col`.
            - if `class_mode` is "image"
            - if `class_mode` is `"input"` or `None` no extra column is needed.
        directory: string, path to the directory to read images from. If `None`,
            data in `x_col` column should be absolute paths.
        image_data_generator: Instance of `ImageDataAugmentor` to use for
            random transformations and normalization. If None, no transformations
            and normalizations are made.
        x_col: string, column in `dataframe` that contains the filenames (or
            absolute paths if `directory` is `None`).
        y_col: string or list, column/s in `dataframe` that has the target data.
        weight_col: string, column in `dataframe` that contains the sample
            weights. Default: `None`.
        target_size: tuple of integers, dimensions to resize input images to.
        color_mode: One of `"rgb"`, `"rgba"`, `"grayscale"` (or `"gray"`),
            Color mode to read images.
        classes: Optional list of strings, classes to use (e.g. `["dogs", "cats"]`).
            If None, all classes in `y_col` will be used.
        class_mode: one of "binary", "categorical", "input", "multi_output",
            "raw", "sparse", "image" or None. Default: "categorical".
            Mode for yielding the targets:
            - `"binary"`: 1D numpy array of binary labels,
            - `"categorical"`: 2D numpy array of one-hot encoded labels.
                Supports multi-label output.
            - `"input"`: images identical to input images (mainly used to
                work with autoencoders),
            - `"multi_output"`: list with the values of the different columns,
            - `"raw"`: numpy array of values in `y_col` column(s),
            - `"sparse"`: 1D numpy array of integer labels,
            - `"color_target"`: string, filepaths relative to
                `directory` (or absolute paths if `directory` is None) will be opened in the
                 specified `color_mode`
            - `"grayscale_target"`: string, filepaths relative to
                `directory` (or absolute paths if `directory` is None) will be opened in the
                 `color_mode = 'gray'`
            - `None`, no targets are returned (the generator will only yield
                batches of image data, which is useful to use in
                `model.predict()`).
        batch_size: Integer, size of a batch.
        shuffle: Boolean, whether to shuffle the data between epochs.
        data_format: String, one of `channels_first`, `channels_last`.
        save_to_dir: Optional directory where to save the pictures
            being yielded, in a viewable format. This is useful
            for visualizing the random transformations being
            applied, for debugging purposes.
        save_prefix: String prefix to use for saving sample
            images (if `save_to_dir` is set).
        save_format: Format to use for saving sample images
            (if `save_to_dir` is set).
        subset: Subset of data (`"training"` or `"validation"`) if
            validation_split is set in ImageDataAugmentor.
        interpolation: Interpolation method used to
            resample the image if the
            target size is different from that of the loaded image.
            Supported methods are `"cv2.INTER_NEAREST"`, `"cv2.INTER_LINEAR"`, `"cv2.INTER_AREA"`, `"cv2.INTER_CUBIC"`
            and `"cv2.INTER_LANCZOS4"`
            By default, `"cv2.INTER_NEAREST"` is used.
        dtype: Output dtype into which the generated arrays will be casted before returning
        validate_filenames: Boolean, whether to validate image filenames in
        `x_col`. If `True`, invalid images will be ignored. Disabling this option
        can lead to speed-up in the instantiation of this class. Default: `True`.
    """
    allowed_class_modes = {
        'binary', 'categorical', 'input', 'multi_output', 'raw', 'sparse', 'color_target', 'grayscale_target', None
    }

    def __init__(self,
                 dataframe: pd.DataFrame,
                 directory: str = None,
                 image_data_generator=None,
                 x_col: str = "filename",
                 y_col: str = "class",
                 weight_col: str = None,
                 target_size: tuple = (256, 256),
                 color_mode: str = 'rgb',
                 classes: list = None,
                 class_mode: str = 'categorical',
                 batch_size: int = 32,
                 shuffle: bool = True,
                 data_format: str = 'channels_last',
                 save_to_dir: str = None,
                 save_prefix: str = '',
                 save_format: str = 'png',
                 subset: str = None,
                 interpolation: int = cv2.INTER_NEAREST,
                 dtype: str = 'float32',
                 validate_filenames: bool = True):

        super(DataFrameIterator, self).set_processing_attrs(image_data_generator,
                                                            target_size,
                                                            color_mode,
                                                            data_format,
                                                            save_to_dir,
                                                            save_prefix,
                                                            save_format,
                                                            subset,
                                                            interpolation,
                                                            dtype
                                                            )
        df = dataframe.copy()
        self.directory = directory or ''
        self.class_mode = class_mode
        self.dtype = dtype
        self.seed = image_data_generator.seed

        # check that inputs match the required class_mode
        self._check_params(df, x_col, y_col, weight_col, classes)
        if validate_filenames:  # check which image files are valid and keep them
            df = self._filter_valid_filepaths(df, x_col)
        if class_mode not in ["input", "multi_output", "raw", "color_target", 'grayscale_target', None]:
            df, classes = self._filter_classes(df, y_col, classes)
            num_classes = len(classes)
            # build an index of all the unique classes
            self.class_indices = dict(zip(classes, range(len(classes))))
            self.num_classes = num_classes

        # retrieve only training or validation set
        if self.split:
            num_files = len(df)
            start = int(self.split[0] * num_files)
            stop = int(self.split[1] * num_files)
            df = df.iloc[start: stop, :]
        # get labels for each observation
        if class_mode not in ["input", "multi_output", "raw", "color_target", 'grayscale_target', None]:
            self.classes = self.get_classes(df, y_col)
        self.filenames = df[x_col].tolist()
        self._sample_weight = df[weight_col].values if weight_col else None

        if class_mode == "multi_output":
            self._targets = [np.array(df[col].tolist()) for col in y_col]
        elif class_mode == "raw":
            self._targets = df[y_col].values
        elif class_mode in ["color_target", 'grayscale_target', ]:
            self._targets = df[y_col].tolist()

        self.samples = len(self.filenames)
        validated_string = 'validated' if validate_filenames else 'non-validated'
        if class_mode in ["input", "multi_output", "raw", "color_target", 'grayscale_target', None]:
            print('Found {} {} image filenames.'
                  .format(self.samples, validated_string))
        else:
            print('Found {} {} image filenames belonging to {} classes.'
                  .format(self.samples, validated_string, num_classes))
        self._filepaths = [
            os.path.join(self.directory, fname) for fname in self.filenames
        ]
        super(DataFrameIterator, self).__init__(self.samples,
                                                batch_size,
                                                shuffle,
                                                self.seed
                                                )

    def _check_params(self, df, x_col, y_col, weight_col, classes):
        # check class mode is one of the currently supported
        if self.class_mode not in self.allowed_class_modes:
            raise ValueError('Invalid class_mode: {}; expected one of: {}'
                             .format(self.class_mode, self.allowed_class_modes))
        # check that y_col has several column names if class_mode is multi_output
        if (self.class_mode == 'multi_output') and not isinstance(y_col, list):
            raise TypeError(
                'If class_mode="{}", y_col must be a list. Received {}.'
                    .format(self.class_mode, type(y_col).__name__)
            )
        # check that filenames/filepaths column values are all strings
        if not all(df[x_col].apply(lambda x: isinstance(x, str))):
            raise TypeError('All values in column x_col={} must be strings.'
                            .format(x_col))
        # check labels are string if class_mode is binary or sparse
        if self.class_mode in {'binary', 'sparse'}:
            if not all(df[y_col].apply(lambda x: isinstance(x, str))):
                raise TypeError('If class_mode="{}", y_col="{}" column '
                                'values must be strings.'
                                .format(self.class_mode, y_col))
        # check that if binary there are only 2 different classes
        if self.class_mode == 'binary':
            if classes:
                classes = set(classes)
                if len(classes) != 2:
                    raise ValueError('If class_mode="binary" there must be 2 '
                                     'classes. {} class/es were given.'
                                     .format(len(classes)))
            elif df[y_col].nunique() != 2:
                raise ValueError('If class_mode="binary" there must be 2 classes. '
                                 'Found {} classes.'.format(df[y_col].nunique()))
        # check values are string, list or tuple if class_mode is categorical
        if self.class_mode == 'categorical':
            types = (str, list, tuple)
            if not all(df[y_col].apply(lambda x: isinstance(x, types))):
                raise TypeError('If class_mode="{}", y_col="{}" column '
                                'values must be type string, list or tuple.'
                                .format(self.class_mode, y_col))
        # raise warning if classes are given but will be unused
        if classes and self.class_mode in {"input", "multi_output", "raw", "image", "mask", None}:
            warnings.warn('`classes` will be ignored given the class_mode="{}"'
                          .format(self.class_mode))
        # check that if weight column that the values are numerical
        if weight_col and not issubclass(df[weight_col].dtype.type, np.number):
            raise TypeError('Column weight_col={} must be numeric.'
                            .format(weight_col))

    def get_classes(self, df, y_col):
        labels = []
        for label in df[y_col]:
            if isinstance(label, (list, tuple)):
                labels.append([self.class_indices[lbl] for lbl in label])
            else:
                labels.append(self.class_indices[label])
        return labels

    @staticmethod
    def _filter_classes(df, y_col, classes):
        df = df.copy()

        def remove_classes(labels, classes):
            if isinstance(labels, (list, tuple)):
                labels = [cls for cls in labels if cls in classes]
                return labels or None
            elif isinstance(labels, str):
                return labels if labels in classes else None
            else:
                raise TypeError(
                    "Expect string, list or tuple but found {} in {} column "
                        .format(type(labels), y_col)
                )

        if classes:
            classes = set(classes)  # sort and prepare for membership lookup
            df[y_col] = df[y_col].apply(lambda x: remove_classes(x, classes))
        else:
            classes = set()
            for v in df[y_col]:
                if isinstance(v, (list, tuple)):
                    classes.update(v)
                else:
                    classes.add(v)
        return df.dropna(subset=[y_col]), sorted(classes)

    def _filter_valid_filepaths(self, df, x_col):
        """Keep only dataframe rows with valid filenames

        # Arguments
            df: Pandas dataframe containing filenames in a column
            x_col: string, column in `df` that contains the filenames or filepaths

        # Returns
            absolute paths to image files
        """
        filepaths = df[x_col].map(
            lambda fname: os.path.join(self.directory, fname)
        )
        mask = filepaths.apply(validate_filename, args=(self.white_list_formats,))
        n_invalid = (~mask).sum()
        if n_invalid:
            warnings.warn(
                'Found {} invalid image filename(s) in x_col="{}". '
                'These filename(s) will be ignored.'
                    .format(n_invalid, x_col)
            )
        return df[mask]

    @property
    def filepaths(self):
        return self._filepaths

    @property
    def labels(self):
        if self.class_mode in {"multi_output", "raw", "color_target", 'grayscale_target', }:
            return self._targets
        else:
            return self.classes

    @property
    def sample_weight(self):
        return self._sample_weight

    @property
    def sample_weight(self):
        return self._sample_weight
    
    #hello
    
@property
    def sample_weight(self):
        return self._sample_weight
