import torch
import torch.nn as nn


class Encoder(nn.Module):
    def __init__(self, input_dim, encoder_dim):
        """
        Initialize a new encoder network.

        Inputs:
        - input_dim: Tuple (C, H, W) giving size of input data.
        - encoder_dim: Int giving the size of the latent space
        """
        super(Encoder, self).__init__()
        C, H, W = input_dim
        self.conv_block_1 = ConvBlock(C, 128)
        self.conv_block_2 = ConvBlock(128, 256)
        self.conv_block_3 = ConvBlock(256, 512)
        self.conv_block_4 = ConvBlock(512, 1024)
        self.flat = Flatten()
        self.fc_1 = nn.Linear(in_features=H*W*1024,
                              out_features=encoder_dim)
        self.fc_2 = nn.Linear(in_features=encoder_dim,
                              out_features=4*4*1024)
        self.view = View(4,4,1024)
        self.upscale = UpscaleBlock(1024, 512)

    def forward(self, x):
        """
        Forward pass of the encoder network. Should not be called
        manually but by calling a model instance directly.

        Inputs:
        - x: PyTorch input Variable
        """
        x = self.conv_block_1(x)
        x = self.conv_block_2(x)
        x = self.conv_block_3(x)
        x = self.conv_block_4(x)
        x = self.flat(x)
        x = self.fc_1(x)
        x = self.fc_2(x)
        x = self.view(x)
        x = self.upscale(x)

        return x

    # TODO: Maybe superclass with is_cuda, save & load
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


# TODO: own file for utils
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
                              padding=(kernel_size+stride-1)//2)
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
                              out_channels=out_channels,
                              kernel_size=kernel_size,
                              stride=stride,
                              padding=(kernel_size+stride-1)//2)
        self.leaky = nn.LeakyReLU(negative_slope=0.1,
                                  inplace=True)
        self.pixel_shuffle = nn.PixelShuffle(2) # TODO: Compare pixelshuffle from FaceSwap to the one from PyTorch

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
