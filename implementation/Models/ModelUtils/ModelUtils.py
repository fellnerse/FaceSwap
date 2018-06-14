from abc import abstractmethod, ABCMeta
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn


class CustomModule(nn.Module):
    @abstractmethod
    def forward(self, *input):
        raise NotImplementedError

    @property
    def is_cuda(self):
        """
        Check if model parameters are allocated on the GPU.
        """
        return next(self.parameters()).is_cuda

    def save(self, path):
        """
        Save model with its parameters to the given path. Conventionally the
        path should end with "*.model".

        Inputs:
        - path: path string
        """
        print('Saving model... %s' % path)
        torch.save(self.state_dict(), path)

    def load(self, path):
        """
        Load model with its parameters from the given path. Conventionally the
        path should end with "*.model".

        Inputs:
        - path: path string
        """
        print('Loading model... %s' % path)
        self.load_state_dict(torch.load(path, map_location=lambda storage, loc: storage))

    @staticmethod
    def weights_init(m):
        classname = m.__class__.__name__
        if classname.find('Conv') != -1:
            m.weight.data.normal_(0.0, 0.02)
        elif classname.find('BatchNorm') != -1:
            m.weight.data.normal_(1.0, 0.02)
            m.bias.data.fill_(0)


class CombinedModel(metaclass=ABCMeta):
    @abstractmethod
    def get_models(self):
        raise NotImplementedError

    @abstractmethod
    def get_model_names(self):
        raise NotImplementedError

    @abstractmethod
    def get_remaining_modules(self):
        raise NotImplementedError

    @abstractmethod
    def train(self, train_data_loader, batch_size, validate, **kwargs):
        raise NotImplementedError

    @abstractmethod
    def anonymize(self, extracted_face, extracted_information):
        raise NotImplementedError

    @abstractmethod
    def log_images(self, logger, epoch, images, validation):
        raise NotImplementedError

    def __str__(self):
        string = str()
        for model in self.get_models():
            string += str(model) + '\n'

        for module in self.get_remaining_modules():
            string += str(module) + '\n'

        # tensorbord uses markup to display text
        string = string.replace('\n', '\n\n')

        return string

    def set_train_mode(self, mode):
        """
        TODO
        :param mode:
        :return:
        """
        for model in self.get_models():
            model.train(mode)
        torch.set_grad_enabled(mode)

    def save_model(self, path):
        """
        TODO
        :param path:
        :return:
        """
        path = Path(path)
        path = path / 'model'
        path.mkdir(parents=True, exist_ok=True)
        for name, model in zip(self.get_model_names(), self.get_models()):
            model.save(path / (name + '.model'))

    def load_model(self, path):
        """
        TODO
        :param path:
        :return:
        """
        path = Path(path)
        for name, model in zip(self.get_model_names(), self.get_models()):
            model.load(path / (name + '.model'))

    def log(self, logger, epoch, log_info, images, log_images=False):
        """
        use logger to log current loss etc...
        :param logger: logger used to log
        :param epoch: current epoch
        """
        logger.log_values(epoch=epoch, values=log_info)
        logger.log_fps(epoch=epoch)

        # log images
        if log_images:
            self.log_images(logger, epoch, images, validation=False)
        logger.save_model(epoch)

    def log_validation(self, logger, epoch, log_info, images):
        logger.log_values(epoch=epoch, values=log_info)
        self.log_images(logger, epoch, images, validation=True)


class ConvBlock(nn.Module):
    """Convolution followed by a LeakyReLU"""

    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size=5,
                 stride=2):
        """
        Initialize a ConvBlock.

        Inputs:
        - in_channels: Number of channels of the input
        - out_channels: Number of filters
        - kernel_size: Size of a convolution filter
        - stride: Stride of the convolutions
        """
        super(ConvBlock, self).__init__()
        # spatial size preserving padding: Padding = (Filter-1)/2
        self.conv = nn.Conv2d(in_channels=in_channels,
                              out_channels=out_channels,
                              kernel_size=kernel_size,
                              stride=stride,
                              padding=(kernel_size - 1) // 2)
        self.leaky = nn.LeakyReLU(negative_slope=0.1,
                                  inplace=True)

    def forward(self, x):
        """
        Forward pass of the ConvBlock. Should not be called
        manually but by calling a model instance directly.

        Inputs:
        - x: PyTorch input Variable
        """
        x = self.conv(x)
        x = self.leaky(x)

        return x


class UpscaleBlock(nn.Module):
    """Scales image up"""

    def __init__(self,
                 in_channels,
                 out_channels,
                 kernel_size=3,
                 stride=1):
        """
        Initialize a UpscaleBlock.

        Inputs:
        - in_channels: Number of channels of the input
        - out_channels: Number of filters
        - kernel_size: Size of a convolution filter
        - stride: Stride of the convolutions
        """
        super(UpscaleBlock, self).__init__()
        self.conv = nn.Conv2d(in_channels=in_channels,
                              out_channels=out_channels * 4,  # compensate PixelShuffle dimensionality reduction
                              kernel_size=kernel_size,
                              stride=stride,
                              padding=(kernel_size - 1) // 2)
        self.leaky = nn.LeakyReLU(negative_slope=0.1,
                                  inplace=True)
        # TODO: Compare pixelshuffle from FaceSwap to the one from PyTorch
        self.pixel_shuffle = nn.PixelShuffle(2)

    def forward(self, x):
        """
        Forward pass of the UpscaleBlock. Should not be called
        manually but by calling a model instance directly.

        Inputs:
        - x: PyTorch input Variable
        """
        x = self.conv(x)
        x = self.leaky(x)
        x = self.pixel_shuffle(x)
        return x


class Flatten(nn.Module):
    """Flatten images"""

    def forward(self, input):
        return input.view(input.size(0), -1)


class View(nn.Module):
    """
    Reshape tensor
    https://discuss.pytorch.org/t/equivalent-of-np-reshape-in-pytorch/144/5
    """

    def __init__(self, *shape):
        super(View, self).__init__()
        self.shape = shape

    def forward(self, input):
        return input.view(self.shape)


class ConvBlockBlock(nn.Sequential):
    def __init__(self, channels_in, num_channels_first_layer=128, depth=4):
        block_list = [ConvBlock(channels_in, num_channels_first_layer)]
        for i in range(1, depth):
            block_list.append(
                ConvBlock(num_channels_first_layer * (2 ** (i - 1)), num_channels_first_layer * (2 ** i)))
        super().__init__(*block_list)


class UpscaleBlockBlock(nn.Sequential):
    def __init__(self, channels_in, num_channels_first_layer=256, depth=3):
        block_list = [UpscaleBlock(channels_in, num_channels_first_layer)]
        for i in range(1, depth):
            block_list.append(
                UpscaleBlock(num_channels_first_layer // (2 ** (i - 1)), num_channels_first_layer // (2 ** i)))
        super().__init__(*block_list)


class RandomNoiseGenerator():
    def __init__(self, size, noise_type='gaussian'):
        self.size = size
        self.noise_type = noise_type.lower()
        assert self.noise_type in ['gaussian', 'uniform']
        self.generator_map = {'gaussian': np.random.randn, 'uniform': np.random.uniform}
        if self.noise_type == 'gaussian':
            self.generator = lambda s: np.random.randn(*s)
        elif self.noise_type == 'uniform':
            self.generator = lambda s: np.random.uniform(-1, 1, size=s)

    def __call__(self, batch_size):
        return torch.from_numpy(self.generator([batch_size, self.size]).astype(np.float32))
